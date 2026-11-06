"""Aggregate arrival-load histograms, calibrate m7i and compare matched phases."""
import datetime as dt
import json
import math
import re
import statistics
import struct
from bisect import bisect_left, bisect_right
from heapq import nlargest
from collections import Counter
from collections.abc import Mapping
from pathlib import Path


def epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    value = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', value.replace('Z', '+00:00'))
    return dt.datetime.fromisoformat(value).timestamp()


# A packed bin uses two bytes for its index and eight for the exact Go count.
# Unusual indices/counts and malformed histograms remain ordinary dictionaries.
_HISTOGRAM_BIN = struct.Struct('=HQ')


class _CompactHistogram(Mapping):
    """Read-only canonical string keys in original insertion order."""
    __slots__ = ('_data',)

    def __init__(self, data):
        self._data = data

    def __len__(self):
        return len(self._data) // _HISTOGRAM_BIN.size

    def __iter__(self):
        return (str(index) for index, count in self._bins())

    def __getitem__(self, key):
        if isinstance(key, str):
            for index, count in self._bins():
                if str(index) == key:
                    return count
        raise KeyError(key)

    def _bins(self):
        return _HISTOGRAM_BIN.iter_unpack(self._data)

    def items(self):
        return ((str(index), count) for index, count in self._bins())

    def values(self):
        return (count for index, count in self._bins())

    def without_zeros(self):
        if all(self.values()):
            return self
        return _CompactHistogram(b''.join(_HISTOGRAM_BIN.pack(index, count)
            for index, count in self._bins() if count))


def _compact_histogram(histogram):
    if not isinstance(histogram, dict):
        return histogram
    packed = bytearray(len(histogram) * _HISTOGRAM_BIN.size)
    for offset, (key, count) in enumerate(histogram.items()):
        try:
            index = int(key)
        except (TypeError, ValueError):
            return histogram
        if (str(index) != key or not 0 <= index <= 65535
                or not _count(count) or count >= 2**64):
            return histogram
        _HISTOGRAM_BIN.pack_into(packed, offset * _HISTOGRAM_BIN.size, index, count)
    return _CompactHistogram(bytes(packed))


# Preserve str.splitlines' legacy handling of non-JSONL separators without
# allocating the complete file or a list of its lines. CR is translated by open.
_EXTRA_LINE_BREAK = re.compile(r'[\v\f\x1c-\x1e\x85\u2028\u2029]')


def _text_lines(stream):
    for physical in stream:
        start = 0
        for match in _EXTRA_LINE_BREAK.finditer(physical):
            yield physical[start:match.end()]
            start = match.end()
        if start < len(physical):
            yield physical[start:]


def _json_object_hook():
    # Fixed schema keys are shared globally. Repeated schema string values have
    # a bounded, per-file lifetime; unknown keys/values never enter either pool.
    strings = {}

    def share(obj):
        if _JSON_KEY_SET.isdisjoint(obj):
            return obj
        obj = {_JSON_KEYS.get(key, key): value for key, value in obj.items()}
        for key in _JSON_STRING_FIELDS:
            value = obj.get(key)
            if isinstance(value, str) and len(value) <= 256:
                obj[key] = (strings.setdefault(value, value) if len(strings) < 256
                            else strings.get(value, value))
        return obj

    return share


def read_jsonl(path):
    """A live snapshot may contain an incomplete final line; don't hide other errors."""
    path = Path(path)
    if not path.exists():
        return []
    out = []
    object_hook = _json_object_hook()
    with path.open() as stream:
        lines = _text_lines(stream)
        for line in lines:
            try:
                row = json.loads(line, object_hook=object_hook)
            except json.JSONDecodeError:
                if line.endswith('\n') or next(lines, None) is not None:
                    raise
                break
            if isinstance(row, dict) and 'histogram' in row:
                row['histogram'] = _compact_histogram(row['histogram'])
            out.append(row)
    return out


def histogram_upper(index):
    index = int(index)
    if index < 64:
        return index
    shift, mantissa = divmod(index - 64, 64)
    return ((mantissa + 65) << shift) - 1


def percentile(histogram, quantile):
    total = sum(histogram.values())
    if not total:
        return None
    target = math.ceil(total * quantile)
    cumulative = 0
    if isinstance(histogram, _CompactHistogram):
        bins = sorted(histogram._bins())
    else:
        bins = ((key, histogram[key]) for key in sorted(histogram, key=int))
    for key, count in bins:
        cumulative += count
        if cumulative >= target:
            return histogram_upper(key) / 1000


def summarize(rows, seconds):
    histogram = Counter()
    for row in rows:
        histogram.update({str(k): int(v) for k, v in row.get('histogram', {}).items()})
    counts = {key: sum(int(row.get(key, 0)) for row in rows) for key in (
        'offered', 'started', 'completed', 'success', 'http_errors',
        'transport_errors', 'timeouts', 'dropped')}
    completed = counts['completed']
    offered = counts['offered']
    cpu_values = [r['client_cpu_pct'] for r in rows if 'client_cpu_pct' in r]
    return dict(counts, seconds=seconds,
                success_rps=counts['success'] / seconds if seconds > 0 else None,
                success_fraction=counts['success'] / offered if offered else None,
                error_fraction=(completed-counts['success']) / completed if completed else None,
                dropped_fraction=counts['dropped'] / offered if offered else None,
                p50_ms=percentile(histogram, .50), p95_ms=percentile(histogram, .95),
                p99_ms=percentile(histogram, .99),
                mean_ms=sum(row.get('latency_sum_us', 0) for row in rows) / sum(histogram.values()) / 1000 if sum(histogram.values()) else None,
                histogram=dict(histogram),
                client_cpu_pct=statistics.mean(cpu_values) if cpu_values else None,
                max_dispatch_lag_ms=max((r.get('max_dispatch_lag_ms', 0) for r in rows), default=None))


def relative(value, baseline):
    if not baseline:
        return None
    def ratio(key):
        b, v = baseline.get(key), value.get(key)
        return v / b if b and v is not None else None
    v, b = value.get('error_fraction'), baseline.get('error_fraction')
    return {'success_rps_ratio': ratio('success_rps'), 'p95_ratio': ratio('p95_ms'),
            'p99_ratio': ratio('p99_ms'), 'error_difference_pp': (v-b)*100 if v is not None and b is not None else None}


def metric_value(row, statistic='VALUE'):
    return next((v['value'] for v in row.get('data', {}).get('measurements', [])
                 if v['statistic'] == statistic), None)


COUNT_FIELDS = ('offered', 'started', 'completed', 'success', 'http_errors',
                'transport_errors', 'timeouts', 'dropped', 'latency_count', 'latency_sum_us')
_JSON_KEYS = {key: key for key in COUNT_FIELDS + (
    'phase', 'timestamp', 'elapsed_sec', 'interval_start_sec', 'interval_end_sec',
    'histogram', 'client_cpu_pct', 'max_dispatch_lag_ms', 'inflight', 'metric',
    'data', 'error', 'name', 'description', 'baseUnit', 'measurements',
    'availableTags', 'statistic', 'value', 'tag', 'values')}
_JSON_KEY_SET = frozenset(_JSON_KEYS)
_JSON_STRING_FIELDS = ('phase', 'metric', 'name', 'description', 'baseUnit', 'statistic', 'tag')
INTERVAL_TOLERANCE = 1e-6
COVERAGE_TOLERANCE = .01


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _interval(row):
    lo, hi = row.get('interval_start_sec'), row.get('interval_end_sec')
    return (lo, hi) if _finite(lo) and _finite(hi) and hi > lo else None


def _union(intervals, lo, hi):
    merged = []
    for a, b in sorted((max(lo, a), min(hi, b)) for a, b in intervals
                       if _finite(a) and _finite(b) and b > a and b > lo and a < hi):
        if merged and a <= merged[-1][1] + INTERVAL_TOLERANCE:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    gaps, cursor = [], lo
    for a, b in merged:
        if a > cursor:
            gaps.append([cursor, a])
        cursor = b
    if cursor < hi:
        gaps.append([cursor, hi])
    covered = sum(b-a for a, b in merged)
    return {'covered_seconds': covered, 'fraction': covered/(hi-lo) if hi > lo else 0,
            'gaps': gaps, 'maxgap': max((b-a for a, b in gaps), default=0)}


def coverage(rows, lo, hi):
    """Union of actual sample intervals, clipped to the requested window."""
    return _union([interval for row in rows if (interval := _interval(row))], lo, hi)


def validate_accounting(rows, status=None):
    """Return diagnostics without coercing counters or trusting terminal status."""
    errors, by_phase, frames = [], {}, {}
    totals = Counter()
    for i, row in enumerate(rows):
        label = f"row {i} phase {row.get('phase')!r}"
        counts_valid = True
        for key in COUNT_FIELDS:
            if not _count(row.get(key)):
                errors.append(f'{label}: {key} must be a nonnegative integer')
                counts_valid = False
        histogram = row.get('histogram')
        hist_valid = isinstance(histogram, (dict, _CompactHistogram))
        if isinstance(histogram, dict):
            for key, value in histogram.items():
                try:
                    index = int(key)
                    if str(index) != str(key) or index < 0 or not _count(value):
                        hist_valid = False
                except (TypeError, ValueError):
                    hist_valid = False
        if not hist_valid:
            errors.append(f'{label}: histogram bins/counts must be nonnegative integers')
        if counts_valid:
            totals.update({key: row[key] for key in COUNT_FIELDS})
            if row['offered'] != row['started'] + row['dropped']:
                errors.append(f'{label}: offered != started + dropped')
            if row['completed'] != sum(row[key] for key in ('success', 'http_errors', 'transport_errors', 'timeouts')):
                errors.append(f'{label}: completed != success + http_errors + transport_errors + timeouts')
            if row['completed'] != row['latency_count'] or (hist_valid and sum(histogram.values()) != row['completed']):
                errors.append(f'{label}: histogram count != completed != latency_count')
        interval = _interval(row)
        if not interval or interval[0] < 0:
            errors.append(f'{label}: interval must have finite nonnegative start and positive duration')
        elif not _finite(row.get('elapsed_sec')) or abs(interval[1]-row['elapsed_sec']) > INTERVAL_TOLERANCE:
            errors.append(f'{label}: interval_end_sec != elapsed_sec')
        if 'inflight' in row and (not _count(row['inflight']) or row['inflight'] > 2048):
            errors.append(f'{label}: inflight outside 0..2048')
        if interval and counts_valid:
            by_phase.setdefault(row.get('phase'), []).append(row)
            frames.setdefault(interval[1], []).append(row)
    for phase, section in by_phase.items():
        started, completed, last_end = 0, 0, None
        for row in sorted(section, key=lambda r: (r['interval_end_sec'], r['interval_start_sec'])):
            lo, hi = _interval(row)
            if last_end is not None and lo < last_end - INTERVAL_TOLERANCE:
                errors.append(f'phase {phase!r}: overlapping sample intervals at {lo}')
            last_end = hi
            started += row['started']
            completed += row['completed']
            if completed > started:
                errors.append(f'phase {phase!r}: cumulative completed {completed} > started {started} at {hi}')
    started = completed = 0
    for end, section in sorted(frames.items()):
        # All original-phase rows in a flush share one frame. Check after the
        # whole frame, so a late old completion can free a new phase's slot.
        if len({r['interval_start_sec'] for r in section}) > 1:
            errors.append(f'frame ending {end}: phase rows have different interval starts')
        started += sum(r['started'] for r in section)
        completed += sum(r['completed'] for r in section)
        outstanding = started-completed
        if not 0 <= outstanding <= 2048:
            errors.append(f'frame ending {end}: total outstanding {outstanding} outside 0..2048')
    if status and status.get('outcome') in ('COMPLETE', 'FAILED'):
        final = status.get('totals')
        if not isinstance(final, dict):
            errors.append('final status: missing totals')
        else:
            for key in COUNT_FIELDS:
                if not _count(final.get(key)) or final[key] != totals[key]:
                    errors.append(f'final status: {key} total {final.get(key)!r} != raw samples {totals[key]}')
        if status['outcome'] == 'COMPLETE':
            if totals['completed'] != totals['started']:
                errors.append('COMPLETE status: outstanding started requests remain')
            if (not _finite(status.get('actual_end')) or not _finite(status.get('scheduled_end'))
                    or status['actual_end'] < status['scheduled_end'] - INTERVAL_TOLERANCE):
                errors.append('COMPLETE status: actual_end has not reached scheduled_end horizon')
    return errors


def expected_offered(phase):
    """Mirror the scheduler's float operation order before the exact ceiling."""
    duration = float(phase['duration_seconds'])
    ramp = float(phase.get('ramp_seconds', 0))
    rate = phase['rate_rps']
    initial = phase.get('from_rate_rps', rate)
    if not ramp:
        return math.ceil(duration*rate)
    x = min(duration,ramp)
    # Keep phasePlan.integral's exact floating-point operation order: an
    # equivalent trapezoid expression can cross an integer before ceil().
    return math.ceil(x*initial + (rate-initial)*x*x/(2*ramp) + max(0,duration-ramp)*rate)


def _planned_errors(samples, phases, status, start_epoch):
    if not status or status.get('outcome') != 'COMPLETE':
        return []
    errors = []
    duration = sum(p['duration_seconds'] for p in phases)
    if not _finite(status.get('actual_end')) or status['actual_end'] < start_epoch+duration-INTERVAL_TOLERANCE:
        errors.append('COMPLETE status: actual_end has not reached planned horizon')
    offered = sum(r['offered'] for r in samples if _count(r.get('offered')))
    planned = sum(expected_offered(p) for p in phases)
    if offered != planned:
        errors.append(f'COMPLETE status: offered {offered} != planned total {planned}')
    return errors


def _telemetry(metrics, name, lo, hi):
    points = {}
    for row in metrics:
        if row.get('metric') != name or row.get('error'):
            continue
        value = metric_value(row)
        if not _finite(value) or value < 0 or (name == 'process.cpu.usage' and value > 1):
            continue
        try:
            timestamp = epoch(row['timestamp'])
        except (KeyError, TypeError, ValueError):
            continue
        if lo <= timestamp < hi:
            points[timestamp] = value
    ordered = sorted(points.items())
    result = _union([(t, t+10) for t in points], lo, hi)
    result['samples'] = len(points)
    result['expected_samples'] = math.ceil(max(0, hi-lo)/10)
    result['uptime_resets'] = sum(b[1] < a[1] for a, b in zip(ordered, ordered[1:])) if name == 'process.uptime' else 0
    return [value for _, value in ordered], result


def _telemetry_valid(result):
    return (result['fraction'] >= .8 and result['samples'] >= .8*result['expected_samples']
            and not result['uptime_resets'])


def _client_errors(rows, calibration=False):
    errors = []
    cpu = [r.get('client_cpu_pct') for r in rows]
    lag = [r.get('max_dispatch_lag_ms') for r in rows]
    if not cpu or any(not _finite(v) or not 0 <= v <= 100 for v in cpu):
        errors.append('missing or invalid client CPU telemetry')
    elif (statistics.mean(cpu) if calibration else max(cpu)) >= 80:
        errors.append('client CPU >=80%')
    if not lag or any(not _finite(v) or v < 0 for v in lag):
        errors.append('missing or invalid dispatch lag telemetry')
    elif (sorted(lag)[min(len(lag)-1, math.ceil(len(lag)*.95)-1)] if calibration else max(lag)) > 25:
        errors.append('dispatch lag >25ms')
    if calibration:
        offered = sum(r['offered'] for r in rows)
        if not offered or sum(r['dropped'] for r in rows)/offered >= .01:
            errors.append('calibration drop ratio >=1% or no offered requests')
    return errors


def calibrate(samples, metrics, phases, start_epoch, status=None):
    errors = validate_accounting(samples, status)
    errors += _planned_errors(samples, phases, status, start_epoch)
    configured = {p['name']:p for p in phases}
    observed = Counter()
    for row in samples:
        if row.get('phase') not in configured:
            errors.append(f"Unknown calibration phase {row.get('phase')!r}")
        if _count(row.get('offered')):
            observed[row.get('phase')] += row['offered']
    for name,phase in configured.items():
        expected = expected_offered(phase)
        if observed[name] != expected:
            errors.append(f'Calibration phase {name}: offered {observed[name]} != planned {expected}')
    if status and (status.get('outcome') == 'FAILED' or not _finite(status.get('start_lateness_ms'))
                   or status['start_lateness_ms'] > 1000):
        errors.append('Calibration failed or start lateness exceeds 1s/is missing')
    _, uptime = _telemetry(metrics, 'process.uptime', start_epoch,
                           start_epoch+sum(p['duration_seconds'] for p in phases))
    if uptime['uptime_resets']:
        errors.append('Calibration JVM uptime reset')
    if errors:
        raise ValueError('Calibration accounting/quality: ' + '; '.join(errors))
    measured, offset = [], 0
    rejected = []
    for phase in phases:
        duration = phase['duration_seconds']
        lo, hi = offset + 30, offset + duration - 2
        rows = [s for s in samples if s['phase'] == phase['name']
                and s['interval_start_sec'] >= lo and s['interval_end_sec'] <= hi]
        cpus, cpu_coverage = _telemetry(metrics, 'process.cpu.usage', start_epoch+lo, start_epoch+hi)
        _, uptime_coverage = _telemetry(metrics, 'process.uptime', start_epoch+lo, start_epoch+hi)
        offset += duration
        if phase['name'].startswith('warmup'):
            continue
        row_coverage = coverage(rows, lo, hi)
        # A continuous block must cover at least 80% of the settled window.
        cursor, longest = lo, 0
        for a, b in row_coverage['gaps'] + [[hi, hi]]:
            longest = max(longest, a-cursor)
            cursor = b
        phase_errors = _client_errors(rows, calibration=True)
        if hi <= lo or row_coverage['fraction'] < .8 or longest < .8*(hi-lo):
            phase_errors.append('continuous sample interval coverage <80%')
        if not _telemetry_valid(cpu_coverage):
            phase_errors.append('CPU telemetry coverage <80%')
        if not _telemetry_valid(uptime_coverage):
            phase_errors.append('uptime telemetry coverage <80% or reset')
        if phase_errors:
            rejected.append({'phase': phase['name'], 'errors': phase_errors})
            continue
        measured.append({'phase': phase['name'], 'rate_rps': phase['rate_rps'],
                         'cpu': statistics.median(cpus),
                         'success_rps': sum(r['success'] for r in rows)/sum(r['interval_end_sec']-r['interval_start_sec'] for r in rows),
                         'coverage': row_coverage, 'cpu_coverage': cpu_coverage,
                         'uptime_coverage': uptime_coverage})
    lower = [r for r in measured if r['cpu'] <= .4]
    upper = [r for r in measured if r['cpu'] >= .4]
    saturated = [r for r in measured if r['cpu'] >= .9]
    if not lower or not upper or not saturated:
        raise ValueError('Need valid CPU 40% bracket and >=90% CPU capacity sample; rejected: ' + json.dumps(rejected))
    a, b = max(lower, key=lambda r:r['cpu']), min(upper, key=lambda r:r['cpu'])
    low = a['rate_rps'] if a['cpu'] == b['cpu'] else a['rate_rps'] + (.4-a['cpu'])/(b['cpu']-a['cpu'])*(b['rate_rps']-a['rate_rps'])
    capacity = max(r['success_rps'] for r in saturated)
    if low <= 0 or capacity <= 0 or low >= capacity or not math.isfinite(capacity):
        raise ValueError('Invalid calibrated low/capacity ordering')
    return {'baseline': 'm7i.xlarge', 'low_rps': low, 'capacity_rps': capacity,
            'peak_rps': capacity*1.1, 'valid_steps': measured, 'rejected_steps': rejected,
            'method': 'CPU 40% interpolated; max successful RPS at >=90% JVM CPU; client health checked'}


GC_PATTERN = re.compile(r'^\[([^\]]+)\].*\[gc\s*\]\s+GC\((\d+)\)\s+(Pause .*)\s+([\d.]+)ms\s*$')


def parse_gc(content):
    return _parse_gc_lines(content.splitlines())


def _parse_gc_lines(lines):
    events = {}
    for line in lines:
        match = GC_PATTERN.match(line)
        if match:
            stamp, ident, detail, pause = match.groups()
            try:
                timestamp = epoch(stamp.strip())
            except ValueError:
                continue
            events[(timestamp, ident)] = {'timestamp': timestamp, 'gc_id': int(ident),
                                          'pause_ms': float(pause), 'detail': detail}
    return sorted(events.values(), key=lambda e:e['timestamp'])


def _read_gc_files(paths):
    def lines():
        for path in paths:
            with path.open(errors='replace') as stream:
                yield from _text_lines(stream)
    return _parse_gc_lines(lines())


def _gc_coverage(gc_coverage, lo, hi):
    if gc_coverage is None:
        return None
    intervals = [tuple(pair) for pair in gc_coverage.get('intervals', [])
                 if isinstance(pair, (list, tuple)) and len(pair) == 2
                 and all(_finite(v) for v in pair) and pair[1] > pair[0]]
    for gap in gc_coverage.get('gaps', []):
        if not isinstance(gap, (list, tuple)) or len(gap) != 2 or not all(_finite(v) for v in gap):
            continue
        a, b = gap
        pieces = []
        for start, end in intervals:
            if b <= start or a >= end or b <= a:
                pieces.append((start, end))
            else:
                if start < a:
                    pieces.append((start, a))
                if end > b:
                    pieces.append((b, end))
        intervals = pieces
    return _union(intervals, lo, hi)


def memory_gc(metrics, events, lo, hi, gc_coverage=None):
    section = sorted([m for m in metrics if lo <= epoch(m['timestamp']) < hi],
                     key=lambda m: epoch(m['timestamp']))
    heap = [metric_value(m) for m in section if m['metric']=='jvm.memory.used.heap' and metric_value(m) is not None]
    cpus = [metric_value(m) for m in section if m['metric']=='process.cpu.usage' and metric_value(m) is not None]
    pauses = [e['pause_ms'] for e in events if lo <= e['timestamp'] < hi]
    def delta(name, statistic):
        vals = [metric_value(m, statistic) for m in section if m['metric']==name and metric_value(m, statistic) is not None]
        return max(0, vals[-1]-vals[0]) if len(vals)>1 and vals[-1]>=vals[0] else None
    collected = _gc_coverage(gc_coverage, lo, hi)
    complete = collected is not None and hi > lo and hi-lo-collected['covered_seconds'] <= COVERAGE_TOLERANCE
    return {'heap_used_mean_bytes': statistics.mean(heap) if heap else None,
            'heap_used_max_bytes': max(heap) if heap else None,
            'jvm_cpu_mean_pct': statistics.mean(cpus)*100 if cpus else None,
            'gc_log_pause_count': len(pauses), 'gc_log_pause_total_ms': sum(pauses),
            'gc_log_pause_max_ms': max(pauses) if pauses else None,
            'gc_actuator_count_delta': delta('jvm.gc.pause','COUNT'),
            'gc_actuator_seconds_delta': delta('jvm.gc.pause','TOTAL_TIME'),
            'allocated_bytes_delta': delta('jvm.gc.memory.allocated','COUNT'),
            'promoted_bytes_delta': delta('jvm.gc.memory.promoted','COUNT'),
            'metrics_fetch_errors': sum('error' in m for m in section),
            'gc_log_coverage': 'unknown' if collected is None else ('estimated_complete' if complete else 'estimated_partial'),
            'gc_log_coverage_fraction': collected['fraction'] if collected is not None else None,
            'gc_log_interval_coverage': collected,
            # This non-atomic rotating-file collector supplies retention
            # estimates, never proof that every pause record was preserved.
            'gc_log_counts_lower_bound': True,
            'gc_log_zero_verified': False,
            'gc_log_continuity_verified': False}


def recovery(samples, phases):
    """First sustained 30 s return to previous low p99/success, after a peak."""
    results, previous_low, offset = [], None, 0
    for i, phase in enumerate(phases):
        end = offset + phase['duration_seconds']
        if '-l40-' in phase['name']:
            previous_low = phase
        elif '-l100-' in phase['name'] and previous_low and i+1 < len(phases):
            next_phase = phases[i+1]
            if '-l40-' in next_phase['name']:
                prior = [r for r in samples if r['phase']==previous_low['name'] and r.get('offered',0)>0]
                b = summarize(prior, sum(r['interval_end_sec']-r['interval_start_sec'] for r in prior))
                future = sorted([r for r in samples if r['phase']==next_phase['name'] and r.get('offered',0)>0],key=lambda r:r['elapsed_sec'])
                streak, found, prev_end, streak_start = 0, None, None, None
                for row in future:
                    lo, now = row['interval_start_sec'], row['interval_end_sec']
                    v = summarize([row], now-lo)
                    good = (b['p99_ms'] is not None and v['p99_ms'] is not None
                            and v['p99_ms']<=b['p99_ms']*1.1 and b['success_fraction'] is not None
                            and v['success_fraction'] is not None and v['success_fraction']>=b['success_fraction']-.01)
                    if good:
                        if prev_end is None or abs(lo-prev_end) > COVERAGE_TOLERANCE or not streak:
                            streak, streak_start = 0, lo
                        streak += now-lo
                    else:
                        streak, streak_start = 0, None
                    prev_end = now
                    if streak >= 30:
                        found = max(0, streak_start-end)
                        break
                results.append({'peak_phase':phase['name'], 'recovery_seconds':found,
                                'comparison_low_phase':previous_low['name']})
        offset = end
    return results


def _observed_summary(rows, seconds):
    """Preserve valid observed counts while flagging malformed fields as unknown."""
    cleaned = []
    for row in rows:
        item = dict(row)
        for key in COUNT_FIELDS:
            item[key] = row[key] if _count(row.get(key)) else 0
        histogram = row.get('histogram')
        item['histogram'] = histogram.without_zeros() if isinstance(histogram, _CompactHistogram) else {}
        if isinstance(histogram, dict):
            for key, count in histogram.items():
                try:
                    index = int(key)
                except (ValueError, TypeError):
                    continue
                if index >= 0 and _count(count) and count:
                    item['histogram'][str(index)] = count
        if not _finite(row.get('client_cpu_pct')):
            item.pop('client_cpu_pct', None)
        if not _finite(row.get('max_dispatch_lag_ms')):
            item['max_dispatch_lag_ms'] = 0
        cleaned.append(item)
    result = summarize(cleaned, seconds)
    for key in COUNT_FIELDS:
        if key in result and any(not _count(r.get(key)) for r in rows):
            result[key] = None
    if result['success'] is None:
        result['success_rps'] = result['success_fraction'] = result['error_fraction'] = None
    return result


def _base_report(run_dir, common_end_limit=None, all_sources_complete=True, historical_before=None,
                 _raw_sources=None):
    root = Path(run_dir)
    metadata = json.loads((root/'metadata.json').read_text())
    phases = metadata.get('phases', [])
    if not phases:
        raise ValueError('No calibrated measurement phases')
    warmup = metadata.get('warmup_seconds', 0)
    horizon = sum(p['duration_seconds'] for p in phases)
    start = metadata['start_epoch']
    loaded, quality = {}, {}
    planned_phases = list(phases)
    if warmup:
        planned_phases.insert(0, dict(name='warmup', duration_seconds=warmup,
                                     rate_rps=phases[0].get('from_rate_rps', phases[0]['rate_rps'])))
    for name in metadata['instances']:
        directory = root/name
        raw = read_jsonl(directory/'samples.ndjson')
        if _raw_sources is not None:
            _raw_sources[name] = raw
        status_path = directory/'status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {}
        accounting = validate_accounting(raw, status)
        # Final totals include warmup and all original-phase late completions.
        config_path = directory/'config.json'
        configured = json.loads(config_path.read_text()) if config_path.exists() else {}
        accounting += _planned_errors(raw, configured.get('phases', planned_phases), status, start-warmup)
        known_phases = {p['name'] for p in planned_phases}
        for unknown in sorted({r.get('phase', '') for r in raw}-known_phases):
            accounting.append(f'unknown original phase {unknown!r}')
        samples = []
        for row in raw:
            if row.get('phase') == 'warmup' or not _finite(row.get('elapsed_sec')) or row['elapsed_sec'] < warmup:
                continue
            adjusted = dict(row, elapsed_sec=row['elapsed_sec']-warmup)
            for key in ('interval_start_sec', 'interval_end_sec'):
                if _finite(row.get(key)):
                    adjusted[key] = row[key]-warmup
            samples.append(adjusted)
        quality[name] = dict(accounting_errors=accounting, phase_coverage={},
            start_lateness_ms=status.get('start_lateness_ms'), outcome=status.get('outcome', 'UNKNOWN'),
            drop_reasons=status.get('drop_reasons'), warnings=status.get('warnings', []),
            gc_rotated_files=len(list((directory/'gc').glob('gc.log*'))))
        if not samples:
            quality[name]['validation_errors'] = accounting + ['missing measurement samples']
            continue
        metrics = read_jsonl(directory/'metrics.ndjson')
        gc_files = list((directory/'gc').glob('gc.log*'))+list((directory/'gc').glob('all.log'))
        events = _read_gc_files(gc_files)
        coverage_path = directory/'gc'/'coverage.json'
        gc_coverage = json.loads(coverage_path.read_text()) if coverage_path.exists() else None
        loaded[name] = dict(raw=raw, samples=samples, metrics=metrics, gc=events,
                            gc_coverage=gc_coverage, status=status)
    base_complete = (len(loaded) == len(metadata['instances']) and bool(loaded)
                     and all(item['status'].get('outcome') == 'COMPLETE' for item in loaded.values()))
    final_complete = base_complete and all_sources_complete
    observed_end = min((max(s['elapsed_sec'] for s in item['samples']) for item in loaded.values()), default=0)
    # Complete snapshots retain bounded drain rows even when the final flag is
    # rejected by accounting. Live snapshots share the same conservative cutoff.
    common_end = horizon if final_complete else min(horizon, max(0, int(observed_end)-3))
    historical_end = horizon if base_complete else common_end
    if common_end_limit is not None:
        common_end = min(common_end, common_end_limit)
    output = dict(baseline='m7i.xlarge', common_elapsed_seconds=common_end, complete=False,
        missing_instances=sorted(set(metadata['instances'])-set(loaded)), phases=[], recovery={}, quality=quality,
        note='Latency includes failures, scheduled-to-completion time; histogram upper-bin error <1.563% above 64us; one host per type.')
    windowed, sample_cutoffs = {}, {}
    for name, item in loaded.items():
        q = quality[name]
        live_rows = [r for r in item['samples'] if r['elapsed_sec'] <= common_end]
        windowed[name] = live_rows
        # Counts are whole frames. The excluded frame crossing the live cutoff
        # identifies the last expected complete frame boundary. Using its start
        # (rather than the last retained row) still exposes a missing tail row.
        sample_cutoffs[name] = min((interval[0] for r in item['samples']
            if (interval := _interval(r)) and interval[0] <= common_end < interval[1]),
            default=common_end)
        _, uptime = _telemetry(item['metrics'], 'process.uptime', start, start+common_end)
        q.update(uptime_resets=uptime['uptime_resets'],
                 metrics_errors=sum('error' in m for m in item['metrics'] if start <= epoch(m['timestamp']) < start+common_end),
                 cpu_over_80_samples=sum(_finite(r.get('client_cpu_pct')) and r['client_cpu_pct'] >= 80 for r in live_rows),
                 dispatch_lag_over_25ms_samples=sum(_finite(r.get('max_dispatch_lag_ms')) and r['max_dispatch_lag_ms'] > 25 for r in live_rows))
        run_errors = list(q['accounting_errors'])
        lateness = q['start_lateness_ms']
        if not _finite(lateness) or lateness > 1000:
            run_errors.append('start lateness exceeds 1s or is missing')
        if q['outcome'] not in ('RUNNING', 'COMPLETE'):
            run_errors.append('client outcome is not RUNNING/COMPLETE')
        if uptime['uptime_resets']:
            run_errors.append('JVM uptime reset')
        q['validation_errors'] = run_errors
    offset = 0
    phase_integrity = []
    for phase in phases:
        end = offset+phase['duration_seconds']
        historical = historical_before is not None and offset < historical_before
        phase_cutoff = historical_end if historical else common_end
        phase_final = base_complete if historical else final_complete
        observed_seconds = min(phase['duration_seconds'], max(0, phase_cutoff-offset))
        if not observed_seconds:
            break
        finished = phase_final or phase_cutoff >= end+2-INTERVAL_TOLERANCE
        entries = {}
        for name, item in loaded.items():
            # Keep every original-phase record through the live cutoff, including
            # completions after its request-scheduling interval has ended (F2).
            rows = [r for r in item['samples'] if r['phase'] == phase['name']
                    and (phase_final or r['elapsed_sec'] <= phase_cutoff)]
            raw_rows = [r for r in item['raw'] if r.get('phase') == phase['name']
                        and (phase_final or (_finite(r.get('elapsed_sec')) and r['elapsed_sec']-warmup <= phase_cutoff))]
            span_end = end if finished else max(offset, min(end, sample_cutoffs[name]))
            covered = coverage(rows, offset, span_end)
            errors = validate_accounting(raw_rows)
            expected = expected_offered(phase) if finished else None
            if finished:
                actual_offered = sum(r['offered'] for r in raw_rows if _count(r.get('offered')))
                if actual_offered != expected:
                    errors.append(f"phase {phase['name']}: offered {actual_offered} != exact planned {expected}")
                if span_end-offset-covered['covered_seconds'] > COVERAGE_TOLERANCE:
                    errors.append(f"phase {phase['name']}: incomplete sample coverage ({covered['fraction']:.6f})")
                if sum(r['completed'] for r in raw_rows if _count(r.get('completed'))) != sum(r['started'] for r in raw_rows if _count(r.get('started'))):
                    errors.append(f"phase {phase['name']}: outstanding requests after drain")
            else:
                if span_end-offset-covered['covered_seconds'] > COVERAGE_TOLERANCE:
                    errors.append(f"phase {phase['name']}: incomplete observed sample coverage")
            integrity_valid = not errors and not quality[name]['accounting_errors']
            seconds = phase['duration_seconds'] if finished else covered['covered_seconds']
            summary = _observed_summary(rows, seconds)
            cpus, cpu_cov = _telemetry(item['metrics'], 'process.cpu.usage', start+offset, start+span_end)
            _, uptime_cov = _telemetry(item['metrics'], 'process.uptime', start+offset, start+span_end)
            phase_errors = errors + _client_errors(rows)
            if not _telemetry_valid(cpu_cov):
                phase_errors.append('CPU telemetry coverage <80%')
            if not _telemetry_valid(uptime_cov):
                phase_errors.append('uptime telemetry coverage <80% or reset')
            phase_errors += quality[name]['validation_errors']
            valid = integrity_valid and not phase_errors
            summary.update(coverage=covered, cpu_coverage=cpu_cov, uptime_coverage=uptime_cov,
                           expected_offered=expected, accounting_valid=integrity_valid,
                           valid=valid, invalid=not valid, validation_errors=phase_errors,
                           vs_m7i=None)
            summary['memory_gc'] = memory_gc(item['metrics'], item['gc'], start+offset, start+span_end,
                                              gc_coverage=item['gc_coverage'])
            entries[name] = summary
            quality[name]['phase_coverage'][phase['name']] = dict(samples=covered, cpu=cpu_cov, uptime=uptime_cov,
                gc=summary['memory_gc']['gc_log_interval_coverage'], finished=finished,
                accounting_valid=integrity_valid, valid=valid, errors=phase_errors)
            phase_integrity.append(finished and integrity_valid)
        baseline = entries.get('m7i.xlarge')
        if finished and baseline and baseline['valid']:
            for value in entries.values():
                if value['valid']:
                    value['vs_m7i'] = relative(value, baseline)
        output['phases'].append(dict(name=phase['name'], rate_rps=phase['rate_rps'],
                                    duration_seconds=observed_seconds, partial=not finished, finished=finished, instances=entries))
        offset = end
    output['complete'] = (final_complete and len(output['phases']) == len(phases)
                          and bool(phase_integrity) and all(phase_integrity)
                          and all(not quality[n]['accounting_errors'] for n in loaded))
    for name, item in loaded.items():
        # Recovery and spike correlation share the report's actual common cutoff.
        rows = windowed[name]
        # Isolated late-completion rows can have completed > started; use their
        # full original phase's integrity rather than invalidating those rows.
        supported_rows = [r for r in rows if quality[name]['phase_coverage'].get(r['phase'], {}).get('valid')]
        recovered = recovery(supported_rows, phases)
        phase_names = [p['name'] for p in phases]
        for value in recovered:
            peak_index = phase_names.index(value['peak_phase'])
            related = [value['comparison_low_phase'], value['peak_phase'], phase_names[peak_index+1]]
            value['valid'] = all(quality[name]['phase_coverage'].get(p, {}).get('valid', False) for p in related)
            value['validation_errors'] = [] if value['valid'] else ['unsupported recovery phase accounting/telemetry']
            if not value['valid']:
                value['recovery_seconds'] = None
        output['recovery'][name] = recovered
        # nlargest is stable for equal keys and keeps only twenty candidates.
        # Validate timestamps even for discarded rows, preserving input errors.
        def candidates():
            for row in rows:
                try:
                    p99 = percentile(row.get('histogram', {}), .99)
                except (TypeError, ValueError):
                    p99 = None
                if p99 is not None:
                    yield p99, row, epoch(row['timestamp'])
        top = nlargest(20, candidates(), key=lambda candidate: candidate[0])
        events = item['gc']
        event_times = [event['timestamp'] for event in events]
        spikes = []
        for p99, row, stamp in top:
            supported = quality[name]['phase_coverage'].get(row['phase'], {}).get('valid', False)
            gc_cov = _gc_coverage(item['gc_coverage'], max(start, stamp-2), min(start+common_end, stamp+2))
            gc_estimated_complete = gc_cov is not None and gc_cov['fraction'] >= 1-INTERVAL_TOLERANCE
            flags = ([] if supported else ['unsupported phase accounting/telemetry']) + [
                'GC log retention is estimated; collection continuity is unverified' if gc_estimated_complete
                else 'GC log estimated coverage incomplete or unknown']
            # Round the search bounds outwards: subtraction in the original
            # abs(event-stamp) <= 2 can round to 2 even just outside stamp +/- 2.
            # The original predicates below remain the authority for inclusion.
            lower = math.nextafter(math.nextafter(stamp, -math.inf)-2, -math.inf)
            upper = math.nextafter(math.nextafter(stamp, math.inf)+2, math.inf)
            lo = bisect_left(event_times, max(start, lower))
            hi = bisect_right(event_times, min(start+common_end, upper))
            spikes.append(dict(timestamp=row['timestamp'], elapsed_sec=row['elapsed_sec'], p99_ms=p99,
                               nearby_gc_pauses=[events[i] for i in range(lo, hi)
                                   if start <= events[i]['timestamp'] <= start+common_end
                                   and abs(events[i]['timestamp']-stamp) <= 2],
                               gc_estimated_coverage=gc_cov, gc_collection_continuity_verified=False,
                               valid=not flags, validation_errors=flags))
        output.setdefault('latency_spikes', {})[name] = spikes
    output['comparison_valid'] = (bool(loaded) and 'm7i.xlarge' in loaded and not output['missing_instances']
        and bool(output['phases']) and all(not quality[n]['validation_errors'] for n in loaded)
        and all(value['valid'] for phase in output['phases'] for value in phase['instances'].values()))
    return output


def _boost_metadata_errors(metadata):
    boost = metadata['boost']
    errors = []
    activation = boost.get('measurement_offset_seconds')
    if not _finite(activation) or activation < 0:
        return ['invalid boost measurement_offset_seconds']
    if not _finite(boost.get('start_epoch')) or abs(boost['start_epoch']-metadata['start_epoch']-activation) > INTERVAL_TOLERANCE:
        errors.append('boost start_epoch does not match measurement offset')
    offset, remaining = 0, []
    for phase in metadata['phases']:
        if offset >= activation:
            remaining.append(phase)
        offset += phase['duration_seconds']
    if not remaining or sum(p['duration_seconds'] for p in remaining) != offset-activation:
        errors.append('boost activation is not an original phase boundary')
    extras = boost.get('phases', [])
    if [(p.get('name'), p.get('duration_seconds')) for p in extras] != [(p['name'], p['duration_seconds']) for p in remaining]:
        errors.append('boost phases do not match the remaining original phase IDs/durations')
    peak, base_peak = boost.get('peak_rps'), boost.get('base_peak_rps')
    if not _finite(peak) or not _finite(base_peak) or not 0 < base_peak < peak:
        errors.append('invalid boost peak/base_peak rates')
    else:
        calibrated_peak = metadata.get('calibrated', {}).get('peak_rps', base_peak)
        if calibrated_peak != base_peak:
            errors.append('boost base_peak_rps differs from original calibration')
        # Derive from the entire original sequence, not the supplied boost tail:
        # the transition immediately before activation determines its from-rate.
        # Match additional_phases semantics without importing the runner.
        delta, previous, offset, canonical = peak-base_peak, 0.0, 0, []
        for base in metadata['phases']:
            rate = delta if '-l100-' in base['name'] else 0.0
            if rate and base['rate_rps'] != base_peak:
                errors.append(f"original peak differs from boost base_peak_rps for {base['name']}")
            ramp = base.get('ramp_seconds', 0) if rate != previous else 0
            if offset >= activation:
                canonical.append(dict(name=base['name'], duration_seconds=base['duration_seconds'],
                                      rate_rps=rate, from_rate_rps=previous, ramp_seconds=ramp))
            previous = rate
            offset += base['duration_seconds']
        if canonical and (canonical[0]['rate_rps'] or
                          (canonical[0]['ramp_seconds'] and canonical[0]['from_rate_rps'])):
            errors.append('boost activation must be an idle additional-traffic phase')
        if not any(p['rate_rps'] for p in canonical):
            errors.append('no future peak remains to increase')
        for expected, extra in zip(canonical, extras):
            rate, initial, ramp = extra.get('rate_rps'), extra.get('from_rate_rps', extra.get('rate_rps')), extra.get('ramp_seconds', 0)
            if not _finite(rate) or not _finite(initial) or rate < 0 or initial < 0 or not _finite(ramp) or not 0 <= ramp <= extra['duration_seconds']:
                errors.append(f"invalid boost schedule for {extra.get('name')}")
            for key in ('rate_rps', 'from_rate_rps', 'ramp_seconds'):
                observed = extra.get(key, 0) if key == 'ramp_seconds' else extra.get(key)
                if observed != expected[key]:
                    errors.append(f"noncanonical boost {key} for {expected['name']}: {observed!r} != required {expected[key]!r}")
    return errors


def _load_boost(root, metadata):
    boost = metadata['boost']
    activation = boost.get('measurement_offset_seconds', 0)
    if not _finite(activation):
        activation = 0
    metadata_errors = _boost_metadata_errors(metadata)
    loaded = {}
    for name in metadata['instances']:
        directory = root/name/'boost'
        raw = read_jsonl(directory/'samples.ndjson')
        path = directory/'status.json'
        status = json.loads(path.read_text()) if path.exists() else {}
        errors = validate_accounting(raw, status)
        if not metadata_errors:
            errors += _planned_errors(raw, boost['phases'], status, boost['start_epoch'])
        config_path = directory/'config.json'
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        if not config or config.get('phases') != boost.get('phases') or config.get('start_epoch') != boost.get('start_epoch'):
            errors.append('missing boost config or config differs from metadata schedule')
        allowed = {p['name'] for p in boost.get('phases', [])}
        if any(r.get('phase') not in allowed for r in raw):
            errors.append('unknown original phase in boost samples')
        shifted = []
        for row in raw:
            if not _finite(row.get('elapsed_sec')):
                continue
            adjusted = dict(row, elapsed_sec=row['elapsed_sec']+activation)
            for key in ('interval_start_sec', 'interval_end_sec'):
                if _finite(row.get(key)):
                    adjusted[key] = row[key]+activation
            shifted.append(adjusted)
        run_errors = errors + metadata_errors
        if not shifted:
            run_errors.append('missing boost measurement samples')
        if status.get('outcome') not in ('RUNNING', 'COMPLETE'):
            run_errors.append('boost outcome is not RUNNING/COMPLETE')
        if not _finite(status.get('start_lateness_ms')) or status['start_lateness_ms'] > 1000:
            run_errors.append('boost start lateness exceeds 1s or is missing')
        loaded[name] = dict(raw=raw, samples=shifted, status=status,
            quality=dict(accounting_errors=errors, validation_errors=run_errors,
                         outcome=status.get('outcome', 'UNKNOWN'), start_lateness_ms=status.get('start_lateness_ms'),
                         drop_reasons=status.get('drop_reasons'), phase_coverage={}))
    return loaded, activation


def report(run_dir):
    """Retain the original experiment; add independently checked boost sources."""
    root = Path(run_dir)
    metadata = json.loads((root/'metadata.json').read_text())
    if not metadata.get('boost'):
        return _base_report(root)
    extras, activation = _load_boost(root, metadata)
    all_complete = bool(extras) and all(s['status'].get('outcome') == 'COMPLETE' for s in extras.values())
    # Future empty sources cannot hold back historical progress. Once samples
    # exist, their elapsed clock is translated to the original measurement clock.
    freshness = [max(r['elapsed_sec'] for r in s['samples']) for s in extras.values() if s['samples']]
    limit = None if all_complete or not freshness else max(activation, int(min(freshness))-3)
    main_rows = {}
    output = _base_report(root, common_end_limit=limit, all_sources_complete=all_complete,
                          historical_before=activation, _raw_sources=main_rows)
    common_end = output['common_elapsed_seconds']
    output['boost'] = dict(metadata['boost'])
    for name, source in extras.items():
        q = output['quality'][name]
        q['sources'] = {'base': dict(q, phase_coverage={key: dict(value)
            for key, value in q['phase_coverage'].items()}), 'boost': source['quality']}
    original = {p['name']: p for p in metadata['phases']}
    extra_phases = {p['name']: p for p in metadata['boost'].get('phases', [])}
    warmup = metadata.get('warmup_seconds', 0)
    offset = 0
    combined_valid, combined_complete = True, True
    affected = set()
    for phase in output['phases']:
        base_phase = original[phase['name']]
        end = offset+base_phase['duration_seconds']
        phase['base_rate_rps'] = base_phase['rate_rps']
        phase['from_rate_rps'] = base_phase.get('from_rate_rps', base_phase['rate_rps'])
        phase['boost_active'] = offset >= activation
        if not phase['boost_active']:
            offset = end
            continue
        affected.add(phase['name'])
        extra_phase = extra_phases.get(phase['name'])
        extra_rate = extra_phase['rate_rps'] if extra_phase else 0
        phase['boost_rate_rps'] = extra_rate
        phase['rate_rps'] = base_phase['rate_rps']+extra_rate
        phase['from_rate_rps'] += extra_phase.get('from_rate_rps', extra_rate) if extra_phase else 0
        finished = phase['finished']
        for name, base in list(phase['instances'].items()):
            source = extras[name]
            samples = source['samples']
            include_drain = (finished and all_complete
                             and all(q['outcome'] == 'COMPLETE' for q in output['quality'].values()))
            rows = [r for r in samples if r['phase'] == phase['name'] and (include_drain or r['elapsed_sec'] <= common_end)]
            raw_rows = [r for r in source['raw'] if r.get('phase') == phase['name']
                        and (include_drain or (_finite(r.get('elapsed_sec')) and r['elapsed_sec']+activation <= common_end))]
            cutoff = min((interval[0] for r in samples
                if (interval := _interval(r)) and interval[0] <= common_end < interval[1]), default=common_end)
            span_end = end if finished else max(offset, min(end, cutoff))
            covered = coverage(rows, offset, span_end)
            errors = validate_accounting(raw_rows)
            expected = expected_offered(extra_phase) if extra_phase and finished else None
            if not extra_phase:
                errors.append('missing boost phase schedule')
            if span_end-offset-covered['covered_seconds'] > COVERAGE_TOLERANCE:
                errors.append('incomplete boost sample coverage')
            if finished:
                offered = sum(r['offered'] for r in raw_rows if _count(r.get('offered')))
                if offered != expected:
                    errors.append(f'boost offered {offered} != exact planned {expected}')
                if sum(r['started'] for r in raw_rows if _count(r.get('started'))) != sum(r['completed'] for r in raw_rows if _count(r.get('completed'))):
                    errors.append('boost outstanding requests after drain')
            accounting_valid = not errors and not source['quality']['accounting_errors']
            errors += _client_errors(rows) + source['quality']['validation_errors']
            extra_summary = _observed_summary(rows, base_phase['duration_seconds'] if finished else covered['covered_seconds'])
            extra_summary.update(coverage=covered, expected_offered=expected, accounting_valid=accounting_valid,
                                 valid=not errors, invalid=bool(errors), validation_errors=errors)
            source['quality']['phase_coverage'][phase['name']] = dict(samples=covered, valid=not errors,
                accounting_valid=accounting_valid, finished=finished, errors=errors)
            source['quality']['cpu_over_80_samples'] = sum(_finite(r.get('client_cpu_pct')) and r['client_cpu_pct'] >= 80 for r in samples if r['elapsed_sec'] <= common_end)
            source['quality']['dispatch_lag_over_25ms_samples'] = sum(_finite(r.get('max_dispatch_lag_ms')) and r['max_dispatch_lag_ms'] > 25 for r in samples if r['elapsed_sec'] <= common_end)
            # Each source is checked separately: their overlapping frames are
            # never passed to accounting validation or used to union away gaps.
            primary = [r for r in main_rows[name] if r.get('phase') == phase['name']
                and (include_drain or (_finite(r.get('elapsed_sec')) and r['elapsed_sec']-warmup <= common_end))]
            seconds = base_phase['duration_seconds'] if finished else max(base['seconds'], extra_summary['seconds'])
            merged = _observed_summary(primary+rows, seconds)
            source_cpu = {'base': base['client_cpu_pct'], 'boost': extra_summary['client_cpu_pct']}
            merged['source_client_cpu_pct'] = source_cpu
            merged['client_cpu_pct'] = max((v for v in source_cpu.values() if _finite(v)), default=None)
            valid = base['valid'] and extra_summary['valid']
            merged_errors = list(base['validation_errors']) + ['boost: '+error for error in errors]
            merged_coverage = dict(covered_seconds=min(base['coverage']['covered_seconds'], covered['covered_seconds']),
                fraction=min(base['coverage']['fraction'], covered['fraction']),
                gaps=sorted({tuple(gap) for c in (base['coverage'], covered) for gap in c['gaps']}),
                maxgap=max(base['coverage']['maxgap'], covered['maxgap']))
            merged.update(sources={'base': {k:v for k,v in base.items() if k not in ('memory_gc', 'vs_m7i')}, 'boost': extra_summary},
                memory_gc=base['memory_gc'], cpu_coverage=base['cpu_coverage'], uptime_coverage=base['uptime_coverage'],
                coverage=merged_coverage, source_coverage={'base': base['coverage'], 'boost': covered},
                expected_offered=(base['expected_offered']+expected if finished and expected is not None else None),
                accounting_valid=base['accounting_valid'] and accounting_valid, valid=valid, invalid=not valid,
                validation_errors=merged_errors, vs_m7i=None)
            phase['instances'][name] = merged
            output['quality'][name]['phase_coverage'][phase['name']].update(valid=valid, errors=merged_errors,
                sources={'base': base['coverage'], 'boost': covered})
            combined_valid = combined_valid and valid
            combined_complete = combined_complete and merged['accounting_valid'] and finished
        baseline = phase['instances'].get('m7i.xlarge')
        if finished and baseline and baseline['valid']:
            for merged in phase['instances'].values():
                if merged['valid']:
                    merged['vs_m7i'] = relative(merged, baseline)
        offset = end
    output['complete'] = (output['complete'] and all_complete and combined_complete
                          and all(not s['quality']['validation_errors'] for s in extras.values()))
    output['comparison_valid'] = output['comparison_valid'] and combined_valid
    # Peak-only boost traffic is idle in both day-two low phases. Once each
    # source's coverage and zero low counters are verified, their combined low
    # histogram/success fraction is exactly the primary low observation. Retain
    # its existing per-row sustained-30-second recovery, without overlapping or
    # double-counting the independent generators' sample intervals.
    phase_names = [p['name'] for p in metadata['phases']]
    phase_results = {p['name']: p for p in output['phases']}
    for name, values in output.get('recovery', {}).items():
        for value in values:
            next_name = phase_names[phase_names.index(value['peak_phase'])+1]
            lows = [value['comparison_low_phase'], next_name]
            related = [value['peak_phase']] + lows
            if not any(p in affected for p in related):
                continue
            errors = []
            for phase_name in related:
                phase_result = phase_results.get(phase_name, {})
                observed = phase_result.get('instances', {}).get(name, {})
                if not phase_result.get('finished') or not observed.get('valid'):
                    errors.append(f'recovery phase {phase_name}: source coverage/quality incomplete or invalid')
            for phase_name in lows:
                if phase_name not in affected:
                    continue
                configured = extra_phases.get(phase_name, {})
                if (configured.get('rate_rps') != 0 or
                        (configured.get('ramp_seconds', 0) != 0 and
                         configured.get('from_rate_rps', configured.get('rate_rps')) != 0)):
                    errors.append(f'recovery low {phase_name}: boost schedule is not zero-rate idle')
                low_rows = [r for r in extras[name]['samples'] if r.get('phase') == phase_name]
                if any(r.get(key) != 0 for r in low_rows
                       for key in ('offered', 'started', 'completed', 'latency_count', 'latency_sum_us')):
                    errors.append(f'recovery low {phase_name}: unexpected boost traffic/latency counts')
            value.update(valid=not errors, validation_errors=errors)
            if errors:
                value['recovery_seconds'] = None
    for name, spikes in output.get('latency_spikes', {}).items():
        for spike in spikes:
            spike['source'] = 'base'
            if any(p['name'] in affected and not p['instances'][name]['valid']
                   and sum(original[q['name']]['duration_seconds'] for q in output['phases'][:i]) < spike['elapsed_sec'] <= sum(original[q['name']]['duration_seconds'] for q in output['phases'][:i+1])
                   for i,p in enumerate(output['phases'])):
                spike['valid'] = False
                spike['validation_errors'].append('unsupported combined-source phase accounting/quality')
    return output
