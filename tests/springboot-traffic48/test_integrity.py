"""Integrity regressions using real counter frames and on-disk run snapshots."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import traffic48_analysis as analysis


COUNTS = ('offered', 'started', 'completed', 'success', 'http_errors',
          'transport_errors', 'timeouts', 'dropped', 'latency_count', 'latency_sum_us')


def frame(phase, lo, hi, count=10, success=None, **changes):
    success = count if success is None else success
    row = dict(phase=phase, timestamp=1000 + hi, elapsed_sec=hi,
               interval_start_sec=lo, interval_end_sec=hi,
               offered=count, started=count, completed=count, success=success,
               http_errors=0, transport_errors=0, timeouts=changes.get('completed', count)-success, dropped=0,
               latency_count=count, latency_sum_us=count*10, histogram={'10': count},
               client_cpu_pct=20, max_dispatch_lag_ms=2, inflight=0)
    row.update(changes)
    return row


def metric(name, when, value):
    return dict(metric=name, timestamp=when,
                data={'measurements': [{'statistic': 'VALUE', 'value': value}]})


def telemetry(lo, hi, cpu=.4):
    return [m for t in range(math.ceil(lo), math.ceil(hi), 10)
            for m in (metric('process.cpu.usage', 1000+t, cpu),
                      metric('process.uptime', 1000+t, 100+t))]


def final_status(rows, end, outcome='COMPLETE'):
    return dict(outcome=outcome, start_lateness_ms=0, scheduled_start=1000,
                scheduled_end=1000+end, actual_end=1000+end+2,
                totals={key: sum(r[key] for r in rows) for key in COUNTS})


class AccountingTests(unittest.TestCase):
    def errors(self, rows, status=None):
        # An absent validator must fail an assertion, not obscure the regression.
        self.assertTrue(callable(getattr(analysis, 'validate_accounting', None)),
                        'Explicit accounting validation is required')
        return analysis.validate_accounting(rows, status)

    def test_counter_and_histogram_contracts(self):
        good = frame('x', 0, 1)
        self.assertEqual(self.errors([good]), [])
        for changes in [dict(offered=11), dict(completed=11), dict(latency_count=11),
                        dict(histogram={'10': 9}), dict(success=-1), dict(started=1.5),
                        dict(dropped=True), dict(histogram={'10': -1}),
                        dict(interval_start_sec=1), dict(interval_end_sec=math.inf),
                        dict(elapsed_sec=2), dict(interval_start_sec=-1)]:
            with self.subTest(changes=changes):
                self.assertTrue(self.errors([dict(good, **changes)]))

    def test_overlap_and_cumulative_completions_are_rejected(self):
        self.assertTrue(self.errors([frame('x', 0, 2), frame('x', 1, 3)]))
        rows = [frame('x', 0, 1, completed=20, success=20,
                      latency_count=20, latency_sum_us=200, histogram={'10': 20}),
                frame('x', 1, 2, completed=0, success=0,
                      latency_count=0, latency_sum_us=0, histogram={})]
        self.assertTrue(self.errors(rows), 'A later start cannot repair an earlier completion')

    def test_shared_frame_outstanding_bound_and_late_completion(self):
        rows = [frame('old', 0, 1, 2000, completed=0, success=0,
                      latency_count=0, latency_sum_us=0, histogram={}, inflight=2000),
                frame('old', 1, 2, 0, completed=2000, success=0, timeouts=2000,
                      latency_count=2000, latency_sum_us=20000, histogram={'10': 2000}),
                frame('new', 1, 2, 2000, completed=0, success=0,
                      latency_count=0, latency_sum_us=0, histogram={}, inflight=2000)]
        self.assertEqual(self.errors(list(reversed(rows))), [])
        rows[2].update(offered=2049, started=2049, inflight=2049)
        self.assertTrue(self.errors(rows))
        rows = [frame(p, 0, 1, 1100, completed=0, success=0,
                      latency_count=0, latency_sum_us=0, histogram={}, inflight=1100)
                for p in ('a', 'b')]
        self.assertTrue(self.errors(rows), 'The bound applies across phases')

    def test_only_final_status_totals_reconcile(self):
        rows = [frame('warmup', 0, 1), frame('x', 1, 2)]
        status = final_status(rows, 2)
        self.assertEqual(self.errors(rows, status), [])
        status['totals']['success'] -= 1
        for outcome in ('COMPLETE', 'FAILED'):
            status['outcome'] = outcome
            self.assertTrue(self.errors(rows, status))
        status['outcome'] = 'RUNNING'
        self.assertEqual(self.errors(rows, status), [])

    def test_union_coverage_clips_and_exposes_head_internal_tail_gaps(self):
        self.assertTrue(callable(getattr(analysis, 'coverage', None)))
        result = analysis.coverage([frame('x', -2, 2), frame('x', 1, 4),
                                    frame('x', 6, 8), frame('x', 7, 9)], 0, 10)
        self.assertEqual(result['covered_seconds'], 7)
        self.assertEqual(result['fraction'], .7)
        self.assertEqual(result['gaps'], [[4, 6], [9, 10]])
        self.assertEqual(result['maxgap'], 2)


def calibration_frames(step=2):
    phases = [dict(name=name, duration_seconds=120, rate_rps=rate)
              for name, rate in [('low', 100), ('mid', 200), ('high', 400)]]
    rows, metrics = [], []
    for i, phase in enumerate(phases):
        offset = i*120
        for t in range(0, 120, step):
            rows.append(frame(phase['name'], offset+t, offset+t+step,
                              phase['rate_rps']*step, [100, 200, 300][i]*step))
        metrics += telemetry(offset, offset+120, [.3, .6, .95][i])
    return rows, metrics, phases


class CalibrationIntegrityTests(unittest.TestCase):
    def test_balanced_total_cannot_hide_phase_count_redistribution(self):
        rows, metrics, phases=calibration_frames()
        altered=[]
        for row in rows:
            rate={'low':90,'mid':180,'high':430}[row['phase']]
            count=rate*int(row['interval_end_sec']-row['interval_start_sec'])
            altered.append(frame(row['phase'],row['interval_start_sec'],row['interval_end_sec'],count))
        status=final_status(altered,360)
        self.assertEqual(status['totals']['offered'],84000)
        for supplied in (None,status):
            with self.subTest(status=supplied is not None),self.assertRaises(ValueError):
                analysis.calibrate(altered,metrics,phases,1000,status=supplied)

    def test_unknown_calibration_phase_is_rejected(self):
        rows,metrics,phases=calibration_frames()
        rows[0]['phase']='unconfigured'
        with self.assertRaises(ValueError):
            analysis.calibrate(rows,metrics,phases,1000,status=final_status(rows,360))

    def test_capacity_uses_actual_two_second_intervals(self):
        rows, metrics, phases = calibration_frames()
        result = analysis.calibrate(rows, metrics, phases, 1000)
        self.assertAlmostEqual(result['low_rps'], 400/3)
        self.assertEqual(result['capacity_rps'], 300)
        self.assertEqual(result['peak_rps'], 330)

    def test_rejects_missing_or_out_of_window_cpu_and_uptime(self):
        rows, metrics, phases = calibration_frames(1)
        for name in ('process.cpu.usage', 'process.uptime'):
            for bad in ('outside', 'sparse', 'duplicate'):
                altered = [m for m in metrics if m['metric'] != name]
                affected = [m for m in metrics if m['metric'] == name]
                if bad == 'outside':
                    altered += [dict(m, timestamp=m['timestamp']+10000) for m in affected]
                elif bad == 'duplicate':
                    altered += [dict(m, timestamp=1030+(j//12)*120) for j, m in enumerate(affected)]
                else:
                    altered += [m for j, m in enumerate(affected) if j % 4 == 0]
                with self.subTest(name=name, bad=bad), self.assertRaises(ValueError):
                    analysis.calibrate(rows, altered, phases, 1000)

    def test_rejects_missing_rows_impossible_counts_and_uptime_reset(self):
        rows, metrics, phases = calibration_frames(1)
        for bad in ('gap', 'count', 'reset', 'overlap', 'client_cpu', 'drops', 'lag'):
            changed, ms = copy.deepcopy(rows), copy.deepcopy(metrics)
            if bad == 'gap':
                changed = [r for r in changed if not (270 <= r['elapsed_sec'] <= 310)]
            elif bad == 'count':
                changed[0]['offered'] += 1
            elif bad == 'reset':
                next(m for m in ms if m['metric'] == 'process.uptime' and m['timestamp']==1310)['data']['measurements'][0]['value'] = 1
            elif bad == 'overlap':
                changed[35]['interval_start_sec'] -= 1
            elif bad == 'client_cpu':
                for r in changed:
                    r['client_cpu_pct'] = 80
            elif bad == 'lag':
                for r in changed:
                    r['max_dispatch_lag_ms'] = 26
            else:
                for r in changed:
                    r.update(started=r['started']-1, dropped=1, completed=r['completed']-1,
                             success=r['success']-1, latency_count=r['latency_count']-1,
                             latency_sum_us=r['latency_sum_us']-10,
                             histogram={'10': r['latency_count']-1})
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                analysis.calibrate(changed, ms, phases, 1000)

    def test_final_status_checks_raw_warmup_and_planned_counts(self):
        rows, metrics, phases = calibration_frames()
        warmup = dict(name='warmup', duration_seconds=10, rate_rps=100)
        shifted = [dict(r, interval_start_sec=r['interval_start_sec']+10,
                        interval_end_sec=r['interval_end_sec']+10,
                        elapsed_sec=r['elapsed_sec']+10, timestamp=r['timestamp']+10) for r in rows]
        rows = [frame('warmup', t, t+2, 200) for t in range(0, 10, 2)] + shifted
        metrics = [dict(m, timestamp=m['timestamp']+10) for m in metrics]
        status = final_status(rows, 370)
        result = analysis.calibrate(rows, metrics, [warmup]+phases, 1000, status=status)
        self.assertEqual(result['capacity_rps'], 300)
        for bad in ('totals', 'horizon', 'planned', 'redistributed_warmup'):
            altered, sts = copy.deepcopy(rows), copy.deepcopy(status)
            if bad == 'totals':
                sts['totals']['offered'] -= 1000
            elif bad == 'horizon':
                sts['actual_end'] = 1369
            else:
                altered[0] = frame('warmup', 0, 2, 199)
                if bad == 'redistributed_warmup':
                    row=altered[5]
                    altered[5]=frame(row['phase'],row['interval_start_sec'],row['interval_end_sec'],row['offered']+1)
                sts = final_status(altered, 370)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                analysis.calibrate(altered, metrics, [warmup]+phases, 1000, status=sts)


class ReportIntegrityTests(unittest.TestCase):
    def snapshot(self, rows=None, phases=None, metrics=None, status=None, warmup=0, gc_coverage=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        phases = phases or [dict(name='low', duration_seconds=60, rate_rps=10)]
        if rows is None:
            rows = [frame('low', t, t+1) for t in range(60)]
        if metrics is None:
            metrics = telemetry(warmup, warmup+sum(p['duration_seconds'] for p in phases))
        if status is None:
            status = final_status(rows, warmup+sum(p['duration_seconds'] for p in phases))
        (root/'metadata.json').write_text(json.dumps(dict(instances=['m7i.xlarge'],
            start_epoch=1000+warmup, warmup_seconds=warmup, phases=phases)))
        target = root/'m7i.xlarge'
        target.mkdir()
        (target/'samples.ndjson').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (target/'metrics.ndjson').write_text(''.join(json.dumps(m)+'\n' for m in metrics))
        (target/'status.json').write_text(json.dumps(status))
        if gc_coverage is not None:
            (target/'gc').mkdir()
            (target/'gc'/'coverage.json').write_text(json.dumps(gc_coverage))
        return root

    def test_valid_complete_and_warmup_reconciliation(self):
        rows = [frame('warmup', t, t+1) for t in range(5)]
        rows += [frame('low', t, t+1) for t in range(5, 65)]
        result = analysis.report(self.snapshot(rows=rows, warmup=5))
        self.assertTrue(result['complete'])
        self.assertTrue(result['comparison_valid'])
        value = result['phases'][0]['instances']['m7i.xlarge']
        self.assertEqual(value['success_rps'], 10)
        self.assertEqual(value['vs_m7i']['success_rps_ratio'], 1)

    def test_complete_status_cannot_hide_missing_head_tail_or_internal_rows(self):
        rows = [frame('low', t, t+1) for t in range(60)]
        for missing in (0, 30, 59):
            subset = [r for j, r in enumerate(rows) if j != missing]
            result = analysis.report(self.snapshot(rows=subset, status=final_status(rows, 60)))
            with self.subTest(missing=missing):
                self.assertFalse(result['complete'])
                self.assertFalse(result['comparison_valid'])
                self.assertIsNone(result['phases'][0]['instances']['m7i.xlarge']['vs_m7i'])
                self.assertTrue(result['quality']['m7i.xlarge']['accounting_errors'])

    def test_missing_telemetry_and_unhealthy_client_block_ratios(self):
        for bad in ('cpu', 'uptime', 'reset', 'client_cpu', 'lag', 'late_start'):
            rows = [frame('low', t, t+1) for t in range(60)]
            metrics = telemetry(0, 60)
            status = final_status(rows, 60)
            if bad in ('cpu', 'uptime'):
                missing = 'process.cpu.usage' if bad == 'cpu' else 'process.uptime'
                metrics = [m for m in metrics if m['metric'] != missing]
            elif bad == 'reset':
                metrics[-1]['data']['measurements'][0]['value'] = 1
            elif bad == 'late_start':
                status['start_lateness_ms'] = 1001
            else:
                rows[20]['client_cpu_pct' if bad == 'client_cpu' else 'max_dispatch_lag_ms'] = 80 if bad == 'client_cpu' else 26
            result = analysis.report(self.snapshot(rows=rows, metrics=metrics, status=status))
            with self.subTest(bad=bad):
                self.assertFalse(result['comparison_valid'])
                self.assertIsNone(result['phases'][0]['instances']['m7i.xlarge']['vs_m7i'])

    def test_partial_uses_observed_time_and_has_no_relative_ratio(self):
        rows = [frame('low', t, t+2, 20) for t in range(0, 24, 2)]
        status = dict(outcome='RUNNING', start_lateness_ms=0)
        result = analysis.report(self.snapshot(rows=rows, status=status))
        value = result['phases'][0]['instances']['m7i.xlarge']
        self.assertEqual(result['common_elapsed_seconds'], 21)
        self.assertEqual(value['success'], 200)
        self.assertEqual(value['seconds'], 20)
        self.assertEqual(value['success_rps'], 10)
        self.assertIsNone(value['vs_m7i'])

    def test_live_fractional_frames_do_not_create_artificial_tail_gap(self):
        # The frame ending 21.0002 is excluded by cutoff 21. Its start,
        # 20.0002, is the last complete frame boundary, not a missing second.
        rows = [frame('low', 0 if t == 0 else t+.0002, t+1+.0002)
                for t in range(24)]
        result = analysis.report(self.snapshot(rows=rows,
            status=dict(outcome='RUNNING', start_lateness_ms=0)))
        value = result['phases'][0]['instances']['m7i.xlarge']
        self.assertEqual(result['common_elapsed_seconds'], 21)
        self.assertEqual(value['success'], 200)
        self.assertAlmostEqual(value['seconds'], 20.0002)
        self.assertEqual(value['coverage']['gaps'], [])
        self.assertEqual(value['coverage']['fraction'], 1)
        self.assertTrue(value['valid'], value['validation_errors'])
        self.assertTrue(result['comparison_valid'])
        self.assertIsNone(value['vs_m7i'])

    def test_live_frame_boundary_preserves_real_head_internal_and_tail_gaps(self):
        rows = [frame('low', 0 if t == 0 else t+.0002, t+1+.0002)
                for t in range(24)]
        for missing, gap in [(0, [0, 1.0002]), (10, [10.0002, 11.0002]),
                             (19, [19.0002, 20.0002])]:
            subset = [r for i, r in enumerate(rows) if i != missing]
            result = analysis.report(self.snapshot(rows=subset,
                status=dict(outcome='RUNNING', start_lateness_ms=0)))
            value = result['phases'][0]['instances']['m7i.xlarge']
            with self.subTest(missing=missing):
                self.assertEqual(value['coverage']['gaps'], [gap])
                self.assertFalse(value['valid'])
                self.assertFalse(result['comparison_valid'])
                self.assertIsNone(value['vs_m7i'])

    def test_live_gap_spanning_cutoff_is_not_trimmed_away(self):
        rows = [frame('low', 0 if t == 0 else t+.0002, t+1+.0002)
                for t in range(24) if t not in (19, 20)]
        result = analysis.report(self.snapshot(rows=rows,
            status=dict(outcome='RUNNING', start_lateness_ms=0)))
        value = result['phases'][0]['instances']['m7i.xlarge']
        self.assertEqual(value['coverage']['gaps'], [[19.0002, 21]])
        self.assertFalse(value['valid'])
        self.assertFalse(result['comparison_valid'])
        self.assertIsNone(value['vs_m7i'])

    def test_original_phase_timeout_is_counted_after_transition_and_final_drain(self):
        phases = [dict(name='a', duration_seconds=2, rate_rps=10),
                  dict(name='b', duration_seconds=2, rate_rps=10)]
        rows = [frame('a', 0, 1), frame('a', 1, 2, completed=0, success=0,
            latency_count=0, latency_sum_us=0, histogram={}, inflight=10),
            frame('a', 2, 3, 0, completed=10, success=0, timeouts=10,
                  latency_count=10, latency_sum_us=100, histogram={'10': 10}),
            frame('b', 2, 3), frame('b', 3, 4, completed=0, success=0,
            latency_count=0, latency_sum_us=0, histogram={}, inflight=10),
            frame('b', 4, 5, 0, completed=10, success=0, timeouts=10,
                  latency_count=10, latency_sum_us=100, histogram={'10': 10})]
        result = analysis.report(self.snapshot(rows=rows, phases=phases))
        self.assertTrue(result['complete'])
        for phase in result['phases']:
            value = phase['instances']['m7i.xlarge']
            self.assertEqual(value['completed'], 20)
            self.assertEqual(value['timeouts'], 10)
            self.assertEqual(value['histogram'], {'10': 20})

    def test_ramp_offered_must_match_exact_ceil_integral(self):
        phases = [dict(name='low', duration_seconds=60, rate_rps=10.01,
                       from_rate_rps=9.01, ramp_seconds=60)]
        rows = [frame('low', t, t+1, 9) for t in range(60)]
        rows[-1] = frame('low', 59, 60, 40)  # 59*9+40 = ceil(570.6) = 571
        self.assertTrue(analysis.report(self.snapshot(rows=rows, phases=phases))['complete'])
        rows[-1] = frame('low', 59, 60, 39)
        result = analysis.report(self.snapshot(rows=rows, phases=phases))
        self.assertFalse(result['complete'])
        self.assertIsNone(result['phases'][0]['instances']['m7i.xlarge']['vs_m7i'])

    def test_recovery_and_spikes_obey_cutoff_and_validation(self):
        rows = [frame('low', t, t+1) for t in range(60)]
        rows[-1]['histogram'] = {'100': 10}
        result = analysis.report(self.snapshot(rows=rows, metrics=[],
                                 status=dict(outcome='RUNNING', start_lateness_ms=0)))
        for spike in result['latency_spikes']['m7i.xlarge']:
            self.assertLessEqual(spike['elapsed_sec'], result['common_elapsed_seconds'])
            self.assertFalse(spike['valid'])


class GCCoverageTests(unittest.TestCase):
    def test_interval_coverage_remains_an_estimate(self):
        cases = [(None, 'unknown', None, False),
                 ({'intervals': [[1000, 1010]], 'gaps': []}, 'estimated_partial', .5, False),
                 ({'intervals': [[1000, 1020]], 'gaps': []}, 'estimated_complete', 1, False),
                 ({'intervals': [[900, 950]], 'gaps': []}, 'estimated_partial', 0, False),
                 ({'intervals': [[1000, 1020]], 'gaps': [[1005, 1010]]}, 'estimated_partial', .75, False)]
        for supplied, label, fraction, verified in cases:
            with self.subTest(label=label, supplied=supplied):
                value = analysis.memory_gc([], [], 1000, 1020, gc_coverage=supplied)
                self.assertEqual(value['gc_log_coverage'], label)
                self.assertEqual(value['gc_log_coverage_fraction'], fraction)
                self.assertEqual(value['gc_log_zero_verified'], verified)
                self.assertTrue(value['gc_log_counts_lower_bound'])

    def test_events_do_not_prove_collection_and_padded_timestamp_parses(self):
        text = '[ 2026-11-04T10:00:00.123+0000 ][12.0s][info][gc ] GC(1) Pause Young 7.123ms\n'
        events = analysis.parse_gc(text)
        self.assertEqual(len(events), 1)
        value = analysis.memory_gc([], events, events[0]['timestamp']-1, events[0]['timestamp']+1)
        self.assertEqual(value['gc_log_coverage'], 'unknown')
        self.assertEqual(value['gc_log_pause_count'], 1)
        self.assertTrue(value['gc_log_counts_lower_bound'])

    def test_report_loads_coverage_json_for_each_phase(self):
        fixture = ReportIntegrityTests()
        self.addCleanup(fixture.doCleanups)
        root = fixture.snapshot(gc_coverage={'intervals': [[1000, 1060]], 'gaps': []})
        value = analysis.report(root)['phases'][0]['instances']['m7i.xlarge']['memory_gc']
        self.assertEqual(value['gc_log_coverage'], 'estimated_complete')
        self.assertFalse(value['gc_log_zero_verified'])

    def test_inferred_torn_and_rotation_captures_never_certify_zero(self):
        import springboot_traffic48 as runner
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            start=analysis.epoch('2026-11-04T10:00:00+00:00')
            for raw in (
                '[2026-11-04T10:00:00.000+0000][info][gc] init\n',
                '[2026-11-04T10:00:00.000+0000][info][gc] init\n[2026-11-04T10:00:05.000+0000][info][gc] GC(1) Pause Young 7.',
                '[2026-11-04T10:00:00.000+0000][info][gc] retained slot after another was rotated away\n'):
                (directory/'gc.log').write_text(raw)
                runner.archive_gc(directory,collected_at=start+20)
                supplied=json.loads((directory/'coverage.json').read_text())
                value=analysis.memory_gc([],[],start,start+20,gc_coverage=supplied)
                self.assertEqual(value['gc_log_coverage'],'estimated_complete')
                self.assertTrue(value['gc_log_counts_lower_bound'])
                self.assertFalse(value['gc_log_zero_verified'])


if __name__ == '__main__':
    unittest.main()
