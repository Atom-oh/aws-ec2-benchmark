// Derived values are computed in Python; the browser only formats observations.
import { fmt } from '../shared.js';
import { short } from '../report.js';

const PAIRS = [['m7i-flex.xlarge', 'm7i.xlarge'], ['m8i-flex.xlarge', 'm8i.xlarge']];
const number = (v, digits = 2) => v == null ? '—' : fmt(v, digits);
const table = (head, rows) => `<div class="table-scroll" tabindex="0"><table class="report-table"><thead><tr>${head.map(h => `<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;

export function renderStability(root, d) {
  const slot = name => root.querySelector(`[data-stability="${name}"]`);
  const find = (n, base, seconds, window, mode = 'observed') => d.windows.find(r =>
    r.instance === n && r.baseline_instance === base && r.peak_seconds === seconds && r.window === window && r.mode === mode);
  slot('early-late').innerHTML = table(
    ['Flex / 같은 세대 기준', '피크', '성공 RPS 전반 → 후반 ↑', 'p99 ms 전반 → 후반 ↓', '후반 미발생 % ↓', '원래 판정 교집합 전반 / 후반'],
    PAIRS.flatMap(([n, base]) => [60, 300, 900, 3600].map(sec => {
      const a = find(n, base, sec, '24–36h'), b = find(n, base, sec, '36–48h');
      const qa = find(n, base, sec, '24–36h', 'strict'), qb = find(n, base, sec, '36–48h', 'strict');
      return [short(n), `${sec / 60}분`, `${number(a.target.success_rps, 0)} → ${number(b.target.success_rps, 0)}`,
        `${number(a.target.p99_ms, 3)} → ${number(b.target.p99_ms, 3)}`, number(b.target.drop_pct),
        `${qa.target?.phases ?? 0} / ${qb.target?.phases ?? 0} (각 3개 중)`];
    })));
  slot('low').innerHTML = table(
    ['동일 구간 비교', '전반 / 후반 통과 구간', '성공 RPS 전반 → 후반 ↑', 'Flex p99 ms 전반 → 후반 ↓', '후반 p99 ÷ 기준 ↓'],
    PAIRS.map(([n, base]) => {
      const a = find(n, base, null, '24–36h', 'idle_qualified'), b = find(n, base, null, '36–48h', 'idle_qualified');
      return [`${short(n)} ÷ ${short(base)}`, `${a.target.phases} / ${b.target.phases}`,
        `${number(a.target.success_rps, 0)} → ${number(b.target.success_rps, 0)}`,
        `${number(a.target.p99_ms, 3)} → ${number(b.target.p99_ms, 3)}`, `${number(b.p99_ratio, 3)}배`];
    }));
  slot('health').innerHTML = table(
    ['Flex', 'JVM 재시작', 'HTTP / 전송 오류', 'timeout', '전체 예정 요청 중 미발생', '최대 힙 GiB', '최대 GC pause ms ↓'],
    PAIRS.map(([n]) => {
      const h = d.health[n];
      return [short(n), h.uptime_resets, `${h.http_errors} / ${h.transport_errors}`, fmt(h.timeouts),
        `${number(h.drop_pct)}%`, number(h.heap_max_gib, 3), number(h.gc_pause_max_ms, 3)];
    }));
  slot('sustained').innerHTML = table(
    ['별도 지속 부하 경과', 'm7i-flex probe RPS ↑', 'm7i-flex probe p99 중앙값 ms ↓', 'm8i-flex probe RPS ↑', 'm8i-flex probe p99 중앙값 ms ↓'],
    d.sustained[PAIRS[0][0]].windows.map((a, i) => {
      const b = d.sustained[PAIRS[1][0]].windows[i];
      return [`${number(a.start_hour, 0)}–${number(a.end_hour, i === 5 ? 2 : 0)}h`,
        number(a.probe_rps_mean, 0), number(a.per_probe_p99_median_ms, 2),
        number(b.probe_rps_mean, 0), number(b.per_probe_p99_median_ms, 2)];
    }));
  slot('cycles').innerHTML = table(
    ['60분 피크 반복', 'm7i-flex 성공 RPS ↑', 'p99 ms ↓', 'm8i-flex 성공 RPS ↑', 'p99 ms ↓'],
    Array.from({ length: 6 }, (_, i) => {
      const get = ([n, base]) => d.cycles.find(r => r.instance === n && r.baseline_instance === base && r.peak_seconds === 3600 && r.cycle === i + 1).target;
      const a = get(PAIRS[0]), b = get(PAIRS[1]);
      return [`${i + 1}회 (${24 + i * 4}–${28 + i * 4}h 주기)`, number(a.success_rps, 0), number(a.p99_ms, 3), number(b.success_rps, 0), number(b.p99_ms, 3)];
    }));
  return { destroy() {} };
}
