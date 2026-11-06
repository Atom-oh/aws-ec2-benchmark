"""Bounded analyzer storage/work and exact parity with the frozen pre-change module."""
import collections
from collections.abc import Mapping
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import traffic48_analysis as analysis
import test_integrity as integrity
import test_boost_analysis as boost_fixture

REFERENCE = Path(os.environ.get('TRAFFIC48_MEMORY_REFERENCE',
    '/tmp/traffic48-memory-reference/traffic48_analysis.py'))
REFERENCE_SHA256 = 'db2f11fe4a8155e10e39e2a78447cc1d8e7198aef249954040860f049b9292a3'


def reference_module(test):
    if not REFERENCE.exists():
        test.skipTest('Frozen analyzer unavailable; set TRAFFIC48_MEMORY_REFERENCE')
    test.assertEqual(hashlib.sha256(REFERENCE.read_bytes()).hexdigest(), REFERENCE_SHA256)
    spec = importlib.util.spec_from_file_location('traffic48_memory_reference', REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measured(call):
    tracemalloc.start()
    try:
        value = call()
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return value, peak


class MemoryAnalysisTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write_rows(self, rows):
        path = self.root/'rows.ndjson'
        with path.open('w') as stream:
            for row in rows:
                stream.write(json.dumps(row)+'\n')
        return path

    def snapshot(self, **kwargs):
        fixture = integrity.ReportIntegrityTests()
        self.addCleanup(fixture.doCleanups)
        return fixture.snapshot(**kwargs)

    def test_sample_schema_key_storage_is_shared_without_expanding_unknown_keys(self):
        rows = [integrity.frame('d1-c1-l40-memory-probe', t, t+1) for t in range(3000)]
        path = self.write_rows(rows)
        result, peak = measured(lambda: analysis.read_jsonl(path))
        self.assertLess(peak, 3.5*1024**2, f'sample strings consume {peak/1024**2:.2f} MiB')
        self.assertEqual(result, rows)
        self.assertEqual(list(result[0]), list(rows[0]))
        self.assertIs(next(k for k in result[0] if k == 'interval_start_sec'),
                      next(k for k in result[-1] if k == 'interval_start_sec'))

    def test_nested_actuator_keys_and_values_are_shared(self):
        row = dict(timestamp='2026-11-06T04:20:00+00:00', metric='jvm.memory.used.heap',
            data=dict(name='jvm.memory.used', description='The amount of used memory in bytes',
                baseUnit='bytes', measurements=[dict(statistic='VALUE', value=123.25)],
                availableTags=[dict(tag='id', values=['G1 Eden Space', 'G1 Old Gen'])]))
        path = self.write_rows(row for _ in range(3000))
        rows, peak = measured(lambda: analysis.read_jsonl(path))
        self.assertLess(peak, 5*1024**2, f'metric strings consume {peak/1024**2:.2f} MiB')
        self.assertEqual(rows, [row]*3000)
        first, last = rows[0]['data'], rows[-1]['data']
        self.assertEqual(list(first), list(row['data']))
        for key in ('name', 'description', 'baseUnit'):
            self.assertIs(first[key], last[key])
        self.assertIs(first['measurements'][0]['statistic'], last['measurements'][0]['statistic'])
        self.assertIs(next(k for k in first if k == 'measurements'),
                      next(k for k in last if k == 'measurements'))

    def test_string_value_cache_is_bounded_per_file_and_ignores_unknown_fields(self):
        supplied = [dict(phase=f'phase-name-{i:04}', unknown_field=f'unknown-value-{i:04}')
                    for i in range(600) for _ in range(2)]
        path = self.write_rows(supplied)
        rows = analysis.read_jsonl(path)
        self.assertEqual(rows, supplied)
        shared = sum(rows[i]['phase'] is rows[i+1]['phase'] for i in range(0, len(rows), 2))
        self.assertGreater(shared, 0)
        self.assertLessEqual(shared, 256)
        for i in range(0, len(rows), 2):
            self.assertIsNot(rows[i]['unknown_field'], rows[i+1]['unknown_field'])
            self.assertIsNot(next(k for k in rows[i] if k == 'unknown_field'),
                             next(k for k in rows[i+1] if k == 'unknown_field'))
        again = analysis.read_jsonl(path)
        self.assertIsNot(rows[0]['phase'], again[0]['phase'], 'cache must not outlive this read')
        long_value = 'x'*257
        rows = analysis.read_jsonl(self.write_rows([{'phase': long_value}]*2))
        self.assertIsNot(rows[0]['phase'], rows[1]['phase'])

    def test_string_sharing_preserves_duplicate_keys_order_types_and_malformed_values(self):
        old = reference_module(self)
        path = self.root/'rows.ndjson'
        lines = ['{"phase":"first","offered":1,"phase":"last","offered":2}',
                 '{"metric":false,"data":{"name":null,"description":[],"baseUnit":1.0,"measurements":[{"statistic":true,"value":-0.0}]}}',
                 '{"phase":{"unexpected":"object"},"histogram":{"010":true}}',
                 '{"phase":"", "data":{"description":"é\\u2028a","availableTags":[]}}']
        path.write_text('\n'.join(lines)+'\n')
        before, after = old.read_jsonl(path), analysis.read_jsonl(path)
        self.assertEqual(json.dumps(after, sort_keys=False), json.dumps(before, sort_keys=False))

    def test_jsonl_reads_without_a_whole_file_text_allocation(self):
        path = self.write_rows([{'value': i} for i in range(4)])
        with patch.object(Path, 'read_text', side_effect=AssertionError('whole-file read')):
            rows = analysis.read_jsonl(path)
        self.assertEqual(rows, [{'value': i} for i in range(4)])

    def test_retained_histogram_storage_is_bounded_and_mapping_is_exact(self):
        histogram = {str(k): k+1000 for k in reversed(range(128))}
        path = self.write_rows({'histogram': histogram} for _ in range(1500))
        rows, peak = measured(lambda: analysis.read_jsonl(path))
        self.assertLess(peak, 5*1024**2, f'{peak/1024**2:.2f} MiB for 192000 bins')
        value = rows[0]['histogram']
        self.assertIsInstance(value, Mapping)
        self.assertEqual(list(value.items()), list(histogram.items()))
        self.assertEqual(list(value.values()), list(histogram.values()))
        self.assertEqual(dict(value), histogram)
        self.assertEqual(value.get('absent'), None)
        for key in histogram:
            self.assertEqual(value[key], histogram[key])

    def test_observed_summary_does_not_expand_all_compact_histograms(self):
        histogram = {str(k): k+1000 for k in range(128)}
        count = sum(histogram.values())
        path = self.write_rows(integrity.frame('low', t, t+1, count, histogram=histogram)
                               for t in range(1500))
        rows = analysis.read_jsonl(path)
        value, peak = measured(lambda: analysis._observed_summary(rows, 1500))
        self.assertLess(peak, 3*1024**2, f'summary expanded to {peak/1024**2:.2f} MiB')
        self.assertEqual(value['histogram'], {k: 1500*v for k,v in histogram.items()})
        self.assertEqual(value['success_rps'], count)

    def test_only_top_twenty_spikes_do_gc_coverage_work(self):
        root = self.snapshot(gc_coverage={'intervals': [[1000, 1060]], 'gaps': []})
        with patch.object(analysis, '_gc_coverage', wraps=analysis._gc_coverage) as calls:
            result = analysis.report(root)
        self.assertLessEqual(calls.call_count, 21, 'one phase plus twenty retained spikes')
        spikes = result['latency_spikes']['m7i.xlarge']
        self.assertEqual([s['elapsed_sec'] for s in spikes], list(range(1, 21)))

    def test_gc_files_are_streamed_with_duplicate_and_torn_event_parity(self):
        old = reference_module(self)
        root = self.snapshot(gc_coverage={'intervals': [[1000, 1060]], 'gaps': []})
        directory = root/'m7i.xlarge'/'gc'
        line = '[1970-01-01T00:16:41+00:00][info][gc] GC(1) Pause Young 1.25ms'
        (directory/'gc.log').write_text(line+'\n[unfinished')
        (directory/'all.log').write_text(line.replace('1.25ms', '2.5ms'))
        expected = old.report(root)
        read_text = Path.read_text
        def guarded(path, *args, **kwargs):
            if path.name.startswith('gc.log') or path.name == 'all.log':
                raise AssertionError('GC whole-file read')
            return read_text(path, *args, **kwargs)
        with patch.object(Path, 'read_text', guarded):
            actual = analysis.report(root)
        self.assertEqual(actual, expected)
        self.assertEqual(actual['latency_spikes']['m7i.xlarge'][0]['nearby_gc_pauses'][0]['pause_ms'], 2.5)

    def test_boost_report_decodes_each_primary_source_once(self):
        old = reference_module(self)
        fixture = boost_fixture.BoostAnalysisTests()
        self.addCleanup(fixture.doCleanups)
        root = fixture.fixture()
        with patch.object(analysis, 'read_jsonl', wraps=analysis.read_jsonl) as reads:
            result = analysis.report(root)
        paths = [Path(call.args[0]) for call in reads.call_args_list]
        self.assertEqual(paths.count(root/'m7i.xlarge'/'samples.ndjson'), 1)
        self.assertEqual(result, old.report(root))

    def test_partial_invalid_and_warmup_reports_match_reference(self):
        old = reference_module(self)
        fixture = boost_fixture.BoostAnalysisTests()
        self.addCleanup(fixture.doCleanups)
        for case in ('partial', 'bad_histogram', 'late', 'missing_boost', 'failed_status'):
            root = fixture.fixture()
            target = root/'m7i.xlarge'/'boost'
            rows = fixture.read_rows(target/'samples.ndjson')
            status = json.loads((target/'status.json').read_text())
            if case == 'partial':
                rows = rows[:35]
                status['outcome'] = 'RUNNING'
            elif case == 'bad_histogram':
                rows[20]['histogram'] = {'0100': rows[20]['completed']}
            elif case == 'late':
                status['start_lateness_ms'] = 1001
            elif case == 'missing_boost':
                rows = rows[:20] + rows[21:]
            else:
                status['outcome'] = 'FAILED'
            fixture.jsonl(target/'samples.ndjson', rows)
            fixture.write(target/'status.json', status)
            with self.subTest(case=case):
                self.assertEqual(json.dumps(analysis.report(root), sort_keys=True),
                                 json.dumps(old.report(root), sort_keys=True))
        rows = [integrity.frame('warmup' if t < 10 else 'low', t, t+1) for t in range(70)]
        root = self.snapshot(rows=rows, warmup=10)
        self.assertEqual(analysis.report(root), old.report(root))

    def test_calibration_with_compact_histograms_matches_reference(self):
        old = reference_module(self)
        rows, metrics, phases = integrity.calibration_frames()
        path = self.write_rows(rows)
        self.assertEqual(analysis.calibrate(analysis.read_jsonl(path), metrics, phases, 1000),
                         old.calibrate(old.read_jsonl(path), metrics, phases, 1000))

    def test_gc_spike_index_preserves_rounded_inclusive_boundary(self):
        old = reference_module(self)
        rows = [integrity.frame('low', t, t+1) for t in range(60)]
        rows[0]['timestamp'] = 2.000001
        root = self.snapshot(rows=rows)
        metadata = json.loads((root/'metadata.json').read_text())
        metadata['start_epoch'] = 0
        (root/'metadata.json').write_text(json.dumps(metadata))
        directory = root/'m7i.xlarge'/'gc'
        directory.mkdir()
        (directory/'gc.log').write_text(
            '[1970-01-01T00:00:00.000001+00:00][info][gc] GC(1) Pause Young 1ms\n')
        expected = old.report(root)
        self.assertEqual(len(expected['latency_spikes']['m7i.xlarge'][0]['nearby_gc_pauses']), 1)
        self.assertEqual(analysis.report(root), expected)

    def test_gc_spike_lookup_does_not_scan_all_events_per_candidate(self):
        root = self.snapshot()
        directory = root/'m7i.xlarge'/'gc'
        directory.mkdir()
        with (directory/'gc.log').open('w') as stream:
            for index in range(300):
                stamp = analysis.dt.datetime.fromtimestamp(index*10, analysis.dt.timezone.utc).isoformat()
                stream.write(f'[{stamp}][info][gc] GC({index}) Pause Young 1ms\n')
        class CountedEvent(dict):
            timestamp_reads = 0
            def __getitem__(self, key):
                if key == 'timestamp':
                    CountedEvent.timestamp_reads += 1
                return super().__getitem__(key)
        read_events = analysis._read_gc_files
        def counted(paths):
            return [CountedEvent(event) for event in read_events(paths)]
        with patch.object(analysis, '_read_gc_files', counted):
            result = analysis.report(root)
        self.assertLess(CountedEvent.timestamp_reads, 900)
        self.assertEqual([e['gc_id'] for e in result['latency_spikes']['m7i.xlarge'][0]['nearby_gc_pauses']], [100])

    def test_parser_torn_lines_and_nonstandard_line_breaks_match_reference(self):
        old = reference_module(self)
        path = self.root/'lines.ndjson'
        for content in ['{}\n{"torn":', '{}\n{}', '{}\n{bad}\n', '{}\n{bad}\n{}',
                        '{}\n', '\n', '  ', '{}\r\n{}\r\n', '{}\r{bad}',
                        '{}\u2028{}', '{}\v{bad}\v{}', '{"x":"a\u2028b"}\n']:
            path.write_text(content)
            with self.subTest(content=content):
                try:
                    expected = old.read_jsonl(path)
                except Exception as exc:
                    with self.assertRaises(type(exc)) as raised:
                        analysis.read_jsonl(path)
                    self.assertEqual(str(raised.exception), str(exc))
                else:
                    self.assertEqual(analysis.read_jsonl(path), expected)

    def test_malformed_and_large_histograms_keep_validation_and_summary_semantics(self):
        old = reference_module(self)
        cases = [{'10': 10}, {'10': 10, '0': 0}, {'010': 10}, {'+10': 10},
                 {' 10': 10}, {'1.0': 10}, {'-1': 10}, {'10': True}, {'10': 10.0},
                 {'10': -1}, {'10': None}, {'10': '10'}, {'10': 2**80},
                 {str(2**80): 0}, {'10': 0, '010': 10}, {'010': 10, '10': 0},
                 [], None, 'histogram', {'oops': 10}, {'10': float('nan')}]
        for histogram in cases:
            path = self.write_rows([integrity.frame('low', 0, 1, histogram=histogram)])
            with self.subTest(histogram=histogram):
                before, after = old.read_jsonl(path), analysis.read_jsonl(path)
                self.assertEqual(old.validate_accounting(before), analysis.validate_accounting(after))
                # A zero count in an enormous bin is skipped before percentile conversion.
                self.assertEqual(old._observed_summary(before, 1), analysis._observed_summary(after, 1))
        # Broadening dict checks to every Mapping would accept previously invalid input.
        row = integrity.frame('low', 0, 1, histogram=collections.UserDict({'10': 10}))
        self.assertEqual(old.validate_accounting([row]), analysis.validate_accounting([row]))
        self.assertEqual(old._observed_summary([row], 1), analysis._observed_summary([row], 1))

    def test_exact_base_and_boost_reports_match_frozen_reference(self):
        old = reference_module(self)
        fixture = boost_fixture.BoostAnalysisTests()
        self.addCleanup(fixture.doCleanups)
        boost_root = fixture.fixture()
        base_root = self.snapshot(gc_coverage={'intervals': [[1000, 1060]], 'gaps': [[1005, 1008]]})
        gc_dir = base_root/'m7i.xlarge'/'gc'
        # Inclusive +/-2s, duplicate identities, padded timestamps and stable ties.
        events = [(999, 0), (1000, 1), (1003, 2), (1003.000001, 3), (1022, 4), (1061, 5)]
        lines = [f'[ {analysis.dt.datetime.fromtimestamp(t, analysis.dt.timezone.utc).isoformat()} ][info][gc] GC({i}) Pause Young {i+1}.25ms\n'
                 for t, i in events]
        (gc_dir/'gc.log').write_text(''.join(lines))
        (gc_dir/'all.log').write_text(lines[2])
        for root in (base_root, boost_root):
            with self.subTest(root=root):
                expected = json.dumps(old.report(root), sort_keys=True, allow_nan=False)
                actual = json.dumps(analysis.report(root), sort_keys=True, allow_nan=False)
                self.assertEqual(actual, expected)
        spike = analysis.report(base_root)['latency_spikes']['m7i.xlarge'][0]
        self.assertEqual([e['gc_id'] for e in spike['nearby_gc_pauses']], [1, 2])


if __name__ == '__main__':
    unittest.main()
