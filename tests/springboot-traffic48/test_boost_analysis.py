"""Combined-generator regressions against real on-disk report inputs."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import traffic48_analysis as analysis

FIELDS = ('offered', 'started', 'completed', 'success', 'http_errors',
          'transport_errors', 'timeouts', 'dropped', 'latency_count', 'latency_sum_us')
BASE_PEAK = 10.25
DELTA = 89989.75


def row(phase, lo, hi, count, bucket='10'):
    return dict(phase=phase, timestamp=1000+hi, elapsed_sec=hi,
        interval_start_sec=lo, interval_end_sec=hi, offered=count, started=count,
        completed=count, success=count, http_errors=0, transport_errors=0,
        timeouts=0, dropped=0, latency_count=count, latency_sum_us=count*int(bucket),
        histogram={bucket: count} if count else {}, client_cpu_pct=20,
        max_dispatch_lag_ms=2, inflight=0)


def samples(phases, shift=0, bucket='10'):
    rows, offset = [], shift
    for phase in phases:
        rate = phase['rate_rps']
        ramp = phase.get('ramp_seconds', 0)
        initial = phase.get('from_rate_rps', rate)
        def integral(t):
            if not ramp:
                return rate*t
            x = min(t, ramp)
            return initial*x + (rate-initial)*x*x/(2*ramp) + max(0, t-ramp)*rate
        for t in range(phase['duration_seconds']):
            count = math.ceil(integral(t+1))-math.ceil(integral(t))
            rows.append(row(phase['name'], offset+t, offset+t+1, count, bucket))
        offset += phase['duration_seconds']
    return rows


def status(rows, start, duration, outcome='COMPLETE'):
    return dict(outcome=outcome, start_lateness_ms=0, scheduled_start=start,
        scheduled_end=start+duration, actual_end=start+duration+2,
        totals=dict({key: sum(r[key] for r in rows) for key in FIELDS}, histogram=None))


def metrics(duration, heap=100):
    return [dict(timestamp=1000+t, metric=name,
        data={'measurements': [{'statistic': 'VALUE', 'value': value}]})
        for t in range(0, duration, 10)
        for name, value in [('process.cpu.usage', .4), ('process.uptime', 100+t),
                            ('jvm.memory.used.heap', heap)]]


class BoostAnalysisTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        phases = [
            dict(name='d2-c1-l100-s1', duration_seconds=10, rate_rps=BASE_PEAK),
            dict(name='d2-c1-l40-s2', duration_seconds=10, rate_rps=5.25),
            dict(name='d1-c2-l100-s3', duration_seconds=60, rate_rps=BASE_PEAK,
                 from_rate_rps=5.25, ramp_seconds=60),
            dict(name='d1-c2-l80-s4', duration_seconds=60, rate_rps=8.25,
                 from_rate_rps=BASE_PEAK, ramp_seconds=60),
            dict(name='d2-c2-l100-s5', duration_seconds=10, rate_rps=BASE_PEAK)]
        extra = [dict(p, rate_rps=rate, from_rate_rps=initial)
                 for p, rate, initial in zip(phases[1:], [0, DELTA, 0, DELTA], [DELTA, 0, DELTA, 0])]
        metadata = dict(instances=['m7i.xlarge'], start_epoch=1000, phases=phases,
            boost=dict(peak_rps=90000, base_peak_rps=BASE_PEAK, start_epoch=1010,
                measurement_offset_seconds=10, phases=extra, client_digest='sha256:test',
                status='LAUNCHED', manifest_sha256='test'))
        self.write(root/'metadata.json', metadata)
        self.source(root/'m7i.xlarge', phases, 1000, samples(phases), metrics(150))
        boost_rows = samples(extra, bucket='100')
        for item in boost_rows:
            item['timestamp'] += 10
        self.source(root/'m7i.xlarge'/'boost', extra, 1010, boost_rows, metrics(150, heap=999999))
        return root

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def source(self, directory, phases, start, rows, ms):
        duration = sum(p['duration_seconds'] for p in phases)
        self.write(directory/'config.json', dict(start_epoch=start, phases=phases, allow_idle=True))
        self.write(directory/'status.json', status(rows, start, duration))
        self.jsonl(directory/'samples.ndjson', rows)
        self.jsonl(directory/'metrics.ndjson', ms)

    def jsonl(self, path, rows):
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def read_rows(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_merged_peak_sums_counts_histograms_over_one_wall_time(self):
        result = analysis.report(self.fixture())
        phase = result['phases'][-1]
        value = phase['instances']['m7i.xlarge']
        self.assertEqual(value['success'], 900001)
        self.assertEqual(value['expected_offered'], 900001)
        self.assertEqual(value['seconds'], 10)
        self.assertEqual(value['success_rps'], 90000.1)
        self.assertEqual(value['histogram'], {'10': 103, '100': 899898})
        self.assertEqual(value['p99_ms'], .100)
        self.assertEqual(value['memory_gc']['heap_used_mean_bytes'], 100)
        self.assertEqual(set(value['sources']), {'base', 'boost'})
        self.assertEqual(value['vs_m7i']['success_rps_ratio'], 1)
        self.assertTrue(result['complete'])

    def test_activation_preserves_history_and_mid_level_steady_rates(self):
        result = analysis.report(self.fixture())
        self.assertEqual([p['rate_rps'] for p in result['phases']], [10.25, 5.25, 90000, 8.25, 90000])
        peak, down = result['phases'][2:4]
        self.assertEqual(peak['base_rate_rps'], 10.25)
        self.assertEqual(peak['from_rate_rps'], 5.25)
        self.assertEqual(down['from_rate_rps'], 90000)
        value = down['instances']['m7i.xlarge']
        self.assertEqual(value['offered'], 2700248)  # ceil(555) + ceil(2699692.5)
        self.assertGreater(value['sources']['boost']['offered'], 0)

    def test_missing_boost_invalidates_only_activated_phases(self):
        root = self.fixture()
        (root/'m7i.xlarge'/'boost'/'samples.ndjson').unlink()
        result = analysis.report(root)
        old = result['phases'][0]['instances']['m7i.xlarge']
        self.assertTrue(old['valid'])
        self.assertEqual(old['vs_m7i']['success_rps_ratio'], 1)
        self.assertIsNone(result['phases'][2]['instances']['m7i.xlarge']['vs_m7i'])
        self.assertFalse(result['comparison_valid'])
        self.assertFalse(result['complete'])

    def test_future_empty_running_boost_does_not_change_original_progress(self):
        root = self.fixture()
        boost = root/'m7i.xlarge'/'boost'
        self.jsonl(boost/'samples.ndjson', [])
        self.write(boost/'status.json', dict(outcome='RUNNING', start_lateness_ms=0))
        main = root/'m7i.xlarge'
        self.jsonl(main/'samples.ndjson', self.read_rows(main/'samples.ndjson')[:8])
        self.write(main/'status.json', dict(outcome='RUNNING', start_lateness_ms=0))
        result = analysis.report(root)
        self.assertEqual(result['common_elapsed_seconds'], 5)
        self.assertTrue(result['comparison_valid'])
        self.assertTrue(result['phases'][0]['instances']['m7i.xlarge']['valid'])
        self.assertEqual(result['phases'][0]['rate_rps'], BASE_PEAK)

    def test_boost_head_internal_tail_gaps_are_not_hidden_by_base_union(self):
        for missing in (10, 35, 69):
            root = self.fixture()
            path = root/'m7i.xlarge'/'boost'/'samples.ndjson'
            rows = self.read_rows(path)
            rows.pop(missing)
            self.jsonl(path, rows)
            # Totals still reconcile: coverage itself must reject the missing row.
            self.write(path.parent/'status.json', status(rows, 1010, 140))
            result = analysis.report(root)
            value = result['phases'][2]['instances']['m7i.xlarge']
            with self.subTest(missing=missing):
                self.assertFalse(value['valid'])
                self.assertIsNone(value['vs_m7i'])
                self.assertLess(value['sources']['boost']['coverage']['fraction'], 1)
                self.assertEqual(value['sources']['base']['coverage']['fraction'], 1)

    def test_sources_reconcile_totals_independently_without_cancellation(self):
        root = self.fixture()
        for folder, change in [('m7i.xlarge', 1), ('m7i.xlarge/boost', -1)]:
            path = root/folder/'status.json'
            sts = json.loads(path.read_text())
            sts['totals']['success'] += change
            self.write(path, sts)
        result = analysis.report(root)
        self.assertFalse(result['complete'])
        self.assertFalse(result['comparison_valid'])
        for source in ('base', 'boost'):
            self.assertTrue(result['quality']['m7i.xlarge']['sources'][source]['accounting_errors'])

    def test_boost_client_cpu_lag_failure_and_lateness_block_only_new_phases(self):
        for bad in ('cpu', 'lag', 'failed', 'late', 'impossible'):
            root = self.fixture()
            path = root/'m7i.xlarge'/'boost'
            sts = json.loads((path/'status.json').read_text())
            rows = self.read_rows(path/'samples.ndjson')
            if bad == 'cpu':
                rows[20]['client_cpu_pct'] = 80
            elif bad == 'lag':
                rows[20]['max_dispatch_lag_ms'] = 26
            elif bad == 'failed':
                sts['outcome'] = 'FAILED'
            elif bad == 'late':
                sts['start_lateness_ms'] = 1001
            else:
                rows[20]['offered'] += 1
            self.jsonl(path/'samples.ndjson', rows)
            self.write(path/'status.json', sts)
            result = analysis.report(root)
            with self.subTest(bad=bad):
                self.assertTrue(result['phases'][0]['instances']['m7i.xlarge']['valid'])
                self.assertFalse(result['phases'][2]['instances']['m7i.xlarge']['valid'])
                self.assertIsNone(result['phases'][2]['instances']['m7i.xlarge']['vs_m7i'])
                if bad in ('cpu', 'lag'):
                    source_quality = result['quality']['m7i.xlarge']['sources']
                    self.assertTrue(source_quality['base']['phase_coverage']['d1-c2-l100-s3']['valid'])
                    self.assertFalse(source_quality['boost']['phase_coverage']['d1-c2-l100-s3']['valid'])

    def test_extra_freshness_limits_common_progress_and_partial_ratios_stay_null(self):
        root = self.fixture()
        path = root/'m7i.xlarge'/'boost'
        self.jsonl(path/'samples.ndjson', self.read_rows(path/'samples.ndjson')[:35])
        self.write(path/'status.json', dict(outcome='RUNNING', start_lateness_ms=0))
        result = analysis.report(root)
        self.assertEqual(result['common_elapsed_seconds'], 42)  # offset 10 + latest 35 - drain 3
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['phases']), 3)
        self.assertTrue(result['phases'][-1]['partial'])
        self.assertIsNone(result['phases'][-1]['instances']['m7i.xlarge']['vs_m7i'])

    def test_stale_boost_does_not_remove_historical_phase_completion(self):
        root = self.fixture()
        path = root/'m7i.xlarge'/'boost'
        self.jsonl(path/'samples.ndjson', self.read_rows(path/'samples.ndjson')[:1])
        self.write(path/'status.json', dict(outcome='RUNNING', start_lateness_ms=0))
        result = analysis.report(root)
        self.assertEqual(result['common_elapsed_seconds'], 10)
        old = result['phases'][0]
        self.assertTrue(old['finished'])
        self.assertTrue(old['instances']['m7i.xlarge']['valid'])
        self.assertEqual(old['instances']['m7i.xlarge']['vs_m7i']['success_rps_ratio'], 1)

    def test_each_source_final_drain_contributes_once(self):
        root = self.fixture()
        for folder, start, duration in [('m7i.xlarge', 1000, 150), ('m7i.xlarge/boost', 1010, 140)]:
            path = root/folder
            rows = self.read_rows(path/'samples.ndjson')
            last = rows[-1]
            last.update(completed=last['completed']-1, success=last['success']-1,
                        latency_count=last['latency_count']-1, latency_sum_us=last['latency_sum_us']-10,
                        histogram={'10': last['completed']-1}, inflight=1)
            drain = row(last['phase'], duration, duration+1, 0)
            drain.update(completed=1, success=1, latency_count=1, latency_sum_us=10,
                         histogram={'10': 1}, timestamp=start+duration+1)
            rows.append(drain)
            self.jsonl(path/'samples.ndjson', rows)
            self.write(path/'status.json', status(rows, start, duration))
        result = analysis.report(root)
        self.assertTrue(result['complete'])
        self.assertEqual(result['phases'][-1]['instances']['m7i.xlarge']['success'], 900001)

    def test_complete_requires_both_sources_reaching_original_horizon(self):
        root = self.fixture()
        path = root/'m7i.xlarge'/'boost'/'status.json'
        sts = json.loads(path.read_text())
        sts['actual_end'] = 1149
        self.write(path, sts)
        result = analysis.report(root)
        self.assertFalse(result['complete'])
        self.assertIsNone(result['phases'][-1]['instances']['m7i.xlarge']['vs_m7i'])

    def burst_fixture(self, boost_low_ramp=False):
        root = self.fixture()
        phases = [dict(name='d2-c1-l40-s1', duration_seconds=60, rate_rps=5.25),
                  dict(name='d2-c1-l40-s2', duration_seconds=60, rate_rps=5.25),
                  dict(name='d2-c1-l100-s3', duration_seconds=30, rate_rps=BASE_PEAK),
                  dict(name='d2-c1-l40-s4', duration_seconds=60, rate_rps=5.25)]
        extra = [dict(p, rate_rps=rate, from_rate_rps=initial, ramp_seconds=0)
                 for p, rate, initial in zip(phases[1:], [0, DELTA, 0], [0, 0, DELTA])]
        if boost_low_ramp:
            extra[-1].update(from_rate_rps=DELTA, ramp_seconds=30)
        metadata = json.loads((root/'metadata.json').read_text())
        metadata.update(phases=phases)
        metadata['boost'].update(start_epoch=1060, measurement_offset_seconds=60, phases=extra)
        self.write(root/'metadata.json', metadata)
        main = samples(phases)
        for item in main:
            if item['phase'] == phases[-1]['name'] and item['elapsed_sec'] <= 180:
                item.update(histogram={'100': item['completed']}, latency_sum_us=item['completed']*100)
        self.source(root/'m7i.xlarge', phases, 1000, main, metrics(210))
        added = samples(extra)
        for item in added:
            item['timestamp'] += 60
        self.source(root/'m7i.xlarge'/'boost', extra, 1060, added, metrics(210))
        return root

    def test_valid_revised_burst_retains_exact_primary_low_recovery(self):
        result = analysis.report(self.burst_fixture())
        value = result['recovery']['m7i.xlarge'][0]
        self.assertEqual(value['recovery_seconds'], 30)
        self.assertTrue(value['valid'], value['validation_errors'])
        self.assertEqual(value['comparison_low_phase'], 'd2-c1-l40-s2')
        self.assertTrue(result['comparison_valid'])

    def test_revised_recovery_rejects_unexpected_boost_low_traffic(self):
        result = analysis.report(self.burst_fixture(boost_low_ramp=True))
        # Internally reconciled counters cannot authorize a day-two low ramp
        # that differs from the unchanged original transition schedule.
        self.assertFalse(result['comparison_valid'])
        value = result['recovery']['m7i.xlarge'][0]
        self.assertIsNone(value['recovery_seconds'])
        self.assertFalse(value['valid'])
        self.assertTrue(value['validation_errors'])

    def rewrite_boost(self, root, metadata):
        self.write(root/'metadata.json', metadata)
        boost = metadata['boost']
        rows = samples(boost['phases'], bucket='100')
        for item in rows:
            item['timestamp'] += boost['measurement_offset_seconds']
        self.source(root/'m7i.xlarge'/'boost', boost['phases'], boost['start_epoch'], rows, metrics(150))
        sts = json.loads((root/'m7i.xlarge'/'boost'/'status.json').read_text())
        self.assertEqual(analysis.validate_accounting(rows, sts), [])

    def test_reconciled_noncanonical_transitions_cannot_authorize_comparison(self):
        cases = [
            ('entry_jump', 1, dict(ramp_seconds=0, from_rate_rps=DELTA)),
            ('entry_shortened', 1, dict(ramp_seconds=30)),
            ('entry_wrong_from', 1, dict(from_rate_rps=DELTA/2)),
            ('down_wrong_from', 2, dict(from_rate_rps=DELTA/2)),
            ('down_jump', 2, dict(ramp_seconds=0)),
            ('day2_smoothing', 3, dict(ramp_seconds=5)),
            ('activation_continuity', 0, dict(from_rate_rps=0)),
        ]
        for label, index, changes in cases:
            root = self.fixture()
            metadata = json.loads((root/'metadata.json').read_text())
            metadata['boost']['phases'][index].update(changes)
            self.rewrite_boost(root, metadata)
            result = analysis.report(root)
            with self.subTest(change=label):
                self.assertFalse(result['comparison_valid'])
                self.assertFalse(result['complete'])
                self.assertTrue(result['phases'][0]['instances']['m7i.xlarge']['valid'])
                self.assertEqual(result['phases'][0]['instances']['m7i.xlarge']['vs_m7i']['success_rps_ratio'], 1)
                affected = result['phases'][index+1]['instances']['m7i.xlarge']
                self.assertFalse(affected['valid'])
                self.assertIsNone(affected['vs_m7i'])
                self.assertTrue(analysis._boost_metadata_errors(metadata))

    def test_activation_cannot_start_a_canonical_peak_or_active_down_ramp(self):
        for offset, index in [(20, 1), (80, 2)]:
            root = self.fixture()
            metadata = json.loads((root/'metadata.json').read_text())
            boost = metadata['boost']
            boost.update(start_epoch=1000+offset, measurement_offset_seconds=offset,
                         phases=boost['phases'][index:])
            self.rewrite_boost(root, metadata)
            result = analysis.report(root)
            with self.subTest(activation=offset):
                self.assertFalse(result['comparison_valid'])
                self.assertFalse(result['complete'])
                self.assertTrue(result['phases'][0]['instances']['m7i.xlarge']['valid'])
                self.assertTrue(analysis._boost_metadata_errors(metadata))
    def test_revised_recovery_requires_valid_complete_source_coverage(self):
        for bad in ('missing', 'partial', 'baseline'):
            root = self.burst_fixture()
            main = root/'m7i.xlarge'
            boost = main/'boost'
            if bad == 'missing':
                rows = self.read_rows(boost/'samples.ndjson')
                rows.pop(100)  # a real hole in the following low phase
                self.jsonl(boost/'samples.ndjson', rows)
                self.write(boost/'status.json', status(rows, 1060, 150))
            elif bad == 'partial':
                rows = self.read_rows(boost/'samples.ndjson')[:130]
                self.jsonl(boost/'samples.ndjson', rows)
                self.write(boost/'status.json', dict(outcome='RUNNING', start_lateness_ms=0))
            else:
                rows = [r for r in self.read_rows(main/'samples.ndjson') if r['phase'] != 'd2-c1-l40-s2']
                self.jsonl(main/'samples.ndjson', rows)
                self.write(main/'status.json', status(rows, 1000, 210))
            result = analysis.report(root)
            with self.subTest(bad=bad):
                value = result['recovery']['m7i.xlarge'][0]
                self.assertIsNone(value['recovery_seconds'])
                self.assertFalse(value['valid'])

    def test_combined_cpu_is_maximum_source_mean_not_cross_source_average(self):
        root = self.fixture()
        for folder, cpu in [('m7i.xlarge', 80), ('m7i.xlarge/boost', 0)]:
            path = root/folder/'samples.ndjson'
            rows = self.read_rows(path)
            for item in rows:
                item['client_cpu_pct'] = cpu
            self.jsonl(path, rows)
        value = analysis.report(root)['phases'][2]['instances']['m7i.xlarge']
        self.assertEqual(value['client_cpu_pct'], 80)
        self.assertEqual(value['source_client_cpu_pct'], {'base': 80, 'boost': 0})
        self.assertFalse(value['valid'])


if __name__ == '__main__':
    unittest.main()
