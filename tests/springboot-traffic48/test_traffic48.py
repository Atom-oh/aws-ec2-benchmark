import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import springboot_traffic48 as runner
import traffic48_analysis as analysis


class ScheduleTests(unittest.TestCase):
    def test_running_gc_capture_needs_only_shell_and_cat(self):
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        logs = {'/gc/gc.log': b'current\n', '/gc/gc.log.0': b'rotated\n'}
        calls = []
        def remote(*args, **kwargs):
            calls.append(args)
            self.assertEqual(args[:5], ('exec', 'server-pod', '-c', 'springboot', '--'))
            if args[5] == 'sh':
                return SimpleNamespace(stdout='\n'.join(logs)+'\n')
            self.assertEqual(args[5], 'cat')
            kwargs['stdout'].write(logs[args[-1]])
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'kubectl', side_effect=remote):
            runner.copy_running_gc('server-pod', pathlib.Path(tmp))
            self.assertEqual((pathlib.Path(tmp)/'gc.log').read_bytes(), logs['/gc/gc.log'])
            self.assertEqual((pathlib.Path(tmp)/'gc.log.0').read_bytes(), logs['/gc/gc.log.0'])
        self.assertEqual(len(calls), 3)

    def test_running_gc_capture_rejects_empty_or_unsafe_listing_before_copy(self):
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        for listing in ('', '/gc/gc.log\n/gc/../outside\n', '/gc/gc.log;command\n'):
            with self.subTest(listing=listing), tempfile.TemporaryDirectory() as tmp, \
                 patch.object(runner, 'kubectl', return_value=SimpleNamespace(stdout=listing)) as remote:
                with self.assertRaises(ValueError):
                    runner.copy_running_gc('server-pod', pathlib.Path(tmp))
                self.assertEqual(remote.call_count, 1)
                self.assertEqual(list(pathlib.Path(tmp).iterdir()), [])

    def test_failed_running_gc_capture_preserves_previous_snapshot(self):
        import json
        import subprocess
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        pods = [{'metadata': {'name': role+'-pod', 'ownerReferences': [
                    {'name': 'sb-traffic48-test1-m7i-xlarge-'+role}]},
                 'status': {'phase': 'Running'}} for role in ('load', 'server')]
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp)/'test1'; output.mkdir()
            gc = output/'m7i.xlarge'/'gc'; gc.mkdir(parents=True)
            (gc/'gc.log').write_bytes(b'previous snapshot\n')
            def failed_capture(pod, directory):
                self.assertEqual(pod, 'server-pod')
                (directory/'gc.log').write_bytes(b'incomplete new capture')
                raise subprocess.CalledProcessError(1, ['cat'])
            with patch.object(runner, 'TYPES', ('m7i.xlarge',)), \
                 patch.object(runner, 'kubectl', return_value=SimpleNamespace(stdout=json.dumps({'items': pods}))) as remote, \
                 patch.object(runner, 'copy_running_gc', side_effect=failed_capture), \
                 patch.object(runner, 'archive_gc') as archive:
                runner.collect(output, 'sha256:'+'a'*64)
                archive.assert_not_called()
                self.assertEqual(remote.call_count, 2)  # pod listing and load copy only
            self.assertEqual((gc/'gc.log').read_bytes(), b'previous snapshot\n')
            self.assertEqual(list(gc.glob('capture-*')), [])
            errors = json.loads((output/'collection-latest.json').read_text())['errors']
            self.assertEqual([e['source'] for e in errors], ['gc'])

    def test_exact_48_hours_and_repeated_ramps_and_bursts(self):
        phases = runner.build_phases(20000, 60000)
        self.assertEqual(sum(x['duration_seconds'] for x in phases), 172800)
        self.assertEqual(len({x['name'] for x in phases}), len(phases))
        self.assertEqual(max(x['rate_rps'] for x in phases), 66000)
        self.assertTrue(any(x['ramp_seconds'] for x in phases[:42]))
        self.assertTrue(all(x['ramp_seconds'] == 0 for x in phases[42:]))
        self.assertEqual([x['duration_seconds'] for x in phases[42:] if x['rate_rps'] == 66000][:4], [60, 300, 900, 3600])
        self.assertEqual(phases[-1]['rate_rps'], 20000)

    def test_invalid_rates(self):
        for low, capacity in [(0, 5), (5, 0), (10, 5), (float('nan'), 5)]:
            with self.assertRaises(ValueError):
                runner.build_phases(low, capacity)

    def test_fractional_ramp_expected_count_matches_scheduler_operation_order(self):
        phase=runner.build_phases(33050,45000)[1]
        # Go phasePlan.integral gives 69,195,500 exactly. The algebraic
        # trapezoid formula rounds above that integer and wrongly adds one.
        self.assertEqual(analysis.expected_offered(phase),69195500)

    def test_invalid_run_label_and_digest(self):
        d='sha256:'+'a'*64
        for run_id in ('x-','-x','a/b','X'):
            with self.assertRaises(ValueError):
                runner.render(run_id,d,d,runner.build_phases(20,60),1800000000)
        with self.assertRaises(ValueError):
            runner.render('ok',None,d,[],1800000000)

    def test_manifest_exclusive_and_scoped_gc_persistence(self):
        digest = 'sha256:' + 'a' * 64
        phases = runner.build_phases(20000, 60000)
        servers, clients = runner.render('test1', digest, digest, phases, 1800000000)
        jobs = [x for x in servers if x['kind'] == 'Job']
        self.assertEqual(len(jobs), 6)
        self.assertEqual(len([x for x in clients if x['kind'] == 'Job']), 6)
        self.assertEqual(len([x for x in servers if x['kind'] == 'PersistentVolumeClaim']), 6)
        for x in jobs:
            spec = x['spec']['template']['spec']
            self.assertFalse(spec['automountServiceAccountToken'])
            self.assertEqual(spec['restartPolicy'], 'Never')
            self.assertEqual(x['spec']['backoffLimit'], 0)
            self.assertEqual(spec['nodeSelector']['karpenter.sh/capacity-type'], 'on-demand')
            self.assertEqual(spec['nodeSelector']['topology.kubernetes.io/zone'], runner.ZONE)
            self.assertNotIn('limits', spec['containers'][0]['resources'])
            self.assertIn('affinity', spec)
            env = {y['name']: y['value'] for y in spec['containers'][0]['env']}
            self.assertIn('-Xlog:gc*,safepoint:file=/gc/gc.log', env['JAVA_OPTS'])
            self.assertGreater(x['spec']['activeDeadlineSeconds'], 172800 + 3600)
        roles = [x for x in clients if x['kind'] == 'Role']
        self.assertEqual(len(roles), 6)
        for role in roles:
            for rule in role['rules']:
                self.assertEqual(len(rule['resourceNames']), 1)
                self.assertIn('sb-traffic48-test1-', rule['resourceNames'][0])
        configs = [x for x in clients if x['kind'] == 'ConfigMap']
        import json
        parsed = [json.loads(x['data']['config.json']) for x in configs]
        self.assertTrue(all(x['phases'] == phases for x in parsed))
        self.assertTrue(all(x['start_epoch'] == 1800000000 for x in parsed))


class CalibrationTests(unittest.TestCase):
    def test_cpu_bracket_and_actual_capacity(self):
        phases = [{'name': 'low', 'duration_seconds': 120, 'rate_rps': 20000},
                  {'name': 'mid', 'duration_seconds': 120, 'rate_rps': 40000},
                  {'name': 'high', 'duration_seconds': 120, 'rate_rps': 80000}]
        samples, metrics = [], []
        for i, p in enumerate(phases):
            for t in range(120):
                end=i*120+t+1
                stamp = 1000 + end
                success = [20000, 40000, 60000][i]
                samples.append(dict(timestamp=stamp, phase=p['name'], offered=p['rate_rps'], success=success,
                                    started=p['rate_rps'], dropped=0, client_cpu_pct=35, max_dispatch_lag_ms=2,
                                    completed=p['rate_rps'],http_errors=0,transport_errors=0,
                                    timeouts=p['rate_rps']-success,latency_count=p['rate_rps'],
                                    histogram={'10':p['rate_rps']},latency_sum_us=p['rate_rps']*10,
                                    elapsed_sec=end,interval_start_sec=end-1,interval_end_sec=end))
                if t % 10 == 0:
                    metrics.append(dict(timestamp=stamp-1, metric='process.cpu.usage',
                                        data={'measurements': [{'statistic': 'VALUE', 'value': [.30, .60, .95][i]}]}))
                    metrics.append(dict(timestamp=stamp-1,metric='process.uptime',
                                        data={'measurements':[{'statistic':'VALUE','value':end+4}]}))
        result = analysis.calibrate(samples, metrics, phases, start_epoch=1000)
        self.assertAlmostEqual(result['low_rps'], 26666.6666667, places=3)
        self.assertEqual(result['capacity_rps'], 60000)
        with self.assertRaises(ValueError):
            analysis.calibrate(samples, [], phases, start_epoch=1000)
        with self.assertRaises(ValueError):
            analysis.calibrate(samples,[m for m in metrics if m['metric']!='process.uptime'],phases,start_epoch=1000)
        for row in samples:
            row['client_cpu_pct'] = 99
        with self.assertRaises(ValueError):
            analysis.calibrate(samples, metrics, phases, start_epoch=1000)


class AnalysisTests(unittest.TestCase):
    def test_histogram_merged_not_mean_p99(self):
        # 99 fast responses and one slow: p99 must land in fast bucket.
        rows = [dict(phase='x', offered=99, success=99, completed=99, histogram={'10': 99}, latency_sum_us=990),
                dict(phase='x', offered=1, success=1, completed=1, histogram={'100': 1}, latency_sum_us=100)]
        summary = analysis.summarize(rows, 2)
        self.assertEqual(summary['p99_ms'], .010)
        self.assertEqual(summary['success_rps'], 50)
        reference = dict(summary, p99_ms=.02, success_rps=100)
        comparison = analysis.relative(summary, reference)
        self.assertEqual(comparison['success_rps_ratio'], .5)
        self.assertEqual(comparison['p99_ratio'], .5)
        self.assertIsNone(analysis.relative(summary, None))

    def test_gc_pause_parsing_and_absent_events(self):
        text = '[2026-11-04T10:00:00.123+0000][12.0s][info][gc] GC(1) Pause Young (Normal) (G1 Evacuation Pause) 1024M->512M(8192M) 7.123ms\n'
        events = analysis.parse_gc(text)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]['pause_ms'], 7.123)
        self.assertEqual(analysis.parse_gc(''), [])
        self.assertEqual(len(analysis.parse_gc(text.replace('[info][gc]', '[info ][gc           ]'))),1)

    def test_report_common_warmup_and_missing_baseline(self):
        import json
        import tempfile
        phases=[{'name':'d1-c1-l40-s1','duration_seconds':172800,'rate_rps':10}]
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            (root/'metadata.json').write_text(json.dumps(dict(instances=['m7i.xlarge','m7g.xlarge'],phases=phases,
                start_epoch=1300,warmup_seconds=300)))
            target=root/'m7g.xlarge';target.mkdir()
            (target/'samples.ndjson').write_text(json.dumps(dict(timestamp=1310,elapsed_sec=310,phase=phases[0]['name'],
                offered=10,started=10,completed=10,success=10,histogram={'10':10},latency_sum_us=100))+'\n')
            value=analysis.report(root)
            self.assertEqual(value['common_elapsed_seconds'],7)
            self.assertEqual(value['missing_instances'],['m7i.xlarge'])
            self.assertIsNone(value['phases'][0]['instances']['m7g.xlarge']['vs_m7i'])
            self.assertFalse(value['complete'])

    def test_archive_rotation_preserves_original_gc(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d=pathlib.Path(tmp);log=d/'gc.log'
            log.write_text('a\n'+'x'*4096+'\n')
            runner.archive_gc(d)
            log.write_text(log.read_text()+'b\n')
            runner.archive_gc(d)
            log.rename(d/'gc.log.0')
            log.write_text('c\n')
            runner.archive_gc(d)
            raw=(d/'all.log').read_text()
            self.assertEqual(raw.count('a\n'),1)
            self.assertEqual(raw.count('b\n'),1)
            self.assertEqual(raw.count('c\n'),1)

    def test_gc_retention_gap_is_recorded(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d=pathlib.Path(tmp)
            log=d/'gc.log'
            log.write_text('[2026-11-04T10:00:00.000+0000][info][gc] init\n')
            runner.archive_gc(d,collected_at=analysis.epoch('2026-11-04T10:10:00+00:00'))
            log.write_text('[2026-11-04T10:20:00.000+0000][info][gc] newer ring contents\n')
            runner.archive_gc(d,collected_at=analysis.epoch('2026-11-04T10:30:00+00:00'))
            meta=json.loads((d/'coverage.json').read_text())
            self.assertEqual(meta['gaps'],[[analysis.epoch('2026-11-04T10:10:00+00:00'),analysis.epoch('2026-11-04T10:20:00+00:00')]])

    def test_one_collection_failure_does_not_skip_other_instances(self):
        import json
        import tempfile
        from unittest.mock import patch
        from types import SimpleNamespace
        calls=[]
        def capture(pvc,directory,image,server_node=False):
            calls.append((pvc,image))
            if pvc.endswith('m7i-xlarge-load-results'):
                raise OSError('one unavailable volume')
        with tempfile.TemporaryDirectory() as tmp:
            output=pathlib.Path(tmp)/'test1';output.mkdir()
            with patch.object(runner,'kubectl',return_value=SimpleNamespace(stdout='{"items":[]}')), \
                 patch.object(runner,'copy_pvc',side_effect=capture):
                runner.collect(output,'sha256:'+'a'*64)
            self.assertEqual(len(calls),12)
            self.assertTrue(all(image==runner.READER_IMAGE for _,image in calls))
            value=json.loads((output/'collection-latest.json').read_text())
            self.assertEqual(value['errors'][0]['instance'],'m7i.xlarge')
            self.assertEqual(len(value['errors']),1)

    def test_complete_run_includes_bounded_final_response_drain(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            (root/'metadata.json').write_text(json.dumps(dict(instances=['m7i.xlarge'],start_epoch=1000,
                phases=[dict(name='last',duration_seconds=2,rate_rps=10)])))
            target=root/'m7i.xlarge';target.mkdir()
            rows=[]
            for t,(offered,completed) in enumerate(((10,0),(10,10),(0,10))):
                rows.append(dict(timestamp=1001+t,elapsed_sec=1+t,phase='last',
                    interval_start_sec=t,interval_end_sec=t+1,offered=offered,started=offered,
                    dropped=0,completed=completed,success=completed,http_errors=0,transport_errors=0,
                    timeouts=0,latency_count=completed,histogram={'10':completed} if completed else {},
                    latency_sum_us=completed*10,client_cpu_pct=20,max_dispatch_lag_ms=2,inflight=10 if t<2 else 0))
            totals={k:sum(r[k] for r in rows) for k in ('offered','started','dropped','completed','success',
                'http_errors','transport_errors','timeouts','latency_count','latency_sum_us')}
            (target/'status.json').write_text(json.dumps(dict(outcome='COMPLETE',start_lateness_ms=0,
                scheduled_start=1000,scheduled_end=1002,actual_end=1003,totals=totals)))
            (target/'samples.ndjson').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            (target/'metrics.ndjson').write_text(''.join(json.dumps(dict(timestamp=1000,metric=name,
                data={'measurements':[{'statistic':'VALUE','value':v}]}))+'\n' for name,v in
                [('process.cpu.usage',.4),('process.uptime',100)]))
            result=analysis.report(root)
            self.assertTrue(result['complete'])
            self.assertEqual(result['phases'][0]['instances']['m7i.xlarge']['success'],20)


if __name__ == '__main__':
    unittest.main()
