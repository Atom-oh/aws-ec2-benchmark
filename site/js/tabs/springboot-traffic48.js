// 48시간 트래픽 탭 — 수치는 scripts/traffic48_report.py가 만든 site/data/springboot-traffic48.json에서만 읽는다.
// 이 파일은 그리기·문장 조립만 한다(하드코딩 수치 없음). 기준선 = m7i.xlarge.
import { fmt, archColor, summaryCards } from '../shared.js';
import { x, short } from '../report.js';
import { renderStability } from './traffic48-stability.js';

const REPO = 'https://github.com/Atom-oh/aws-ec2-benchmark/blob/92b5d5092ba5c94e3664a9f9f58e773ff0b36c82/reports/traffic48-final/';
const BASE = 'm7i.xlarge';
const BAND = 0.05;
const cell = (v, d = 3) => (v == null ? '—' : fmt(v, d));
// 같은 아키텍처 안에서도 구분되도록 flex는 점선, 세대는 진하기
const style = (n, arch) => ({
  borderColor: archColor(arch, /8/.test(n) ? 0.95 : 0.55), backgroundColor: archColor(arch, /8/.test(n) ? 0.95 : 0.55),
  borderDash: /flex/.test(n) ? [6, 4] : [],
});

export async function render(root, { rows, envelope: e }) {
  const response = await fetch('data/springboot-flex-stability.json');
  if (!response.ok) throw new Error(`Flex stability data: HTTP ${response.status}`);
  const stability = await response.json();
  if (stability.source_sha256 !== e.source_sha256) throw new Error('Flex stability source mismatch');
  const handles = [];
  const slot = (k) => root.querySelector(`[data-slot="${k}"]`);
  const meta = Object.fromEntries(rows.map((r) => [r.name, r]));
  const names = Object.keys(e.instances);
  const arch = (n) => meta[n]?.arch || (/g\./.test(n) ? 'graviton' : 'intel');
  const C = e.comparisons;
  const cmp = (g, m, n) => (C[g]?.[m] || []).find((r) => r.instance === n);

  // ---------- 핵심 결과 ----------
  const pk = (n) => cmp('peak90', 'observed', n);
  const lowQ = (n) => cmp('day2_low', 'idle_qualified', n);
  const best = names.filter((n) => pk(n)?.target).sort((a, b) => pk(b).target.success_rps - pk(a).target.success_rps)[0];
  const lossless = names.filter((n) => (pk(n)?.target?.drop_pct ?? 100) < 1);
  handles.push(summaryCards(slot('cards'), [
    best && { label: '90k 목표 피크 · 성공 처리량 1위', value: short(best), detail: `${fmt(pk(best).target.success_rps)} RPS · m7i 대비 ${x(pk(best).rps_ratio)} · 미발생 ${fmt(pk(best).target.drop_pct, 1)}%` },
    pk('m7i-flex.xlarge') && { label: '피크: m7i-flex ÷ m7i', value: x(pk('m7i-flex.xlarge').rps_ratio), detail: `처리량 · p99 ${x(pk('m7i-flex.xlarge').p99_ratio)}` },
    pk('m8i-flex.xlarge') && { label: '피크: m8i-flex ÷ m7i', value: x(pk('m8i-flex.xlarge').rps_ratio), detail: `처리량 · p99 ${x(pk('m8i-flex.xlarge').p99_ratio)}` },
    lowQ('m7i-flex.xlarge')?.target && { label: '둘째 날 평상시 p99: m7i-flex ÷ m7i', value: x(lowQ('m7i-flex.xlarge').p99_ratio), detail: `${fmt(lowQ('m7i-flex.xlarge').target.p99_ms, 2)}ms · 장시간 부하 뒤 느려지는지` },
  ].filter(Boolean)));
  const flexLow = ['m7i-flex.xlarge', 'm8i-flex.xlarge'].map((n) => lowQ(n)?.p99_ratio).filter((v) => v != null);
  const flexOk = flexLow.length && flexLow.every((v) => v <= 1 + BAND);
  slot('lead').innerHTML = `<p><strong>${flexOk ? '장시간 부하 뒤에도 Flex가 평상시에 느려지는 현상은 이 호스트들에서 보이지 않았습니다.' : '장시간 부하 뒤 평상시 구간에서 Flex의 p99가 m7i보다 5% 넘게 높았습니다.'}</strong> 둘째 날 평상시 구간(같은 구간 교집합)에서 m7i-flex의 p99는 m7i의 ${x(lowQ('m7i-flex.xlarge')?.p99_ratio)}, m8i-flex는 ${x(lowQ('m8i-flex.xlarge')?.p99_ratio)}입니다.</p>`
    + `<p><strong>90k 목표 피크에서는 세대 차이가 큽니다.</strong> 성공 처리량은 ${names.filter((n) => pk(n)).sort((a, b) => pk(b).rps_ratio - pk(a).rps_ratio).map((n) => `${short(n)} ${x(pk(n).rps_ratio)}`).join(', ')}(m7i = 1.00배)입니다. `
    + `${lossless.length ? `미발생 1% 미만으로 처리한 인스턴스는 ${lossless.map(short).join(', ')}입니다.` : '90k 목표를 손실 없이(미발생 1% 미만) 처리한 인스턴스는 없습니다 — 피크 비교는 손실을 함께 보세요.'}</p>`;

  // ---------- m7i와 같은 구간 비교 (선택) ----------
  const group = root.querySelector('[data-select="group"]');
  const mode = root.querySelector('[data-select="mode"]');
  let barHandles = [];
  const bars = (host, items, { title, lowerBetter }) => {
    host.innerHTML = `<div class="chart-box" style="height:${Math.max(200, items.length * 34 + 70)}px"><canvas></canvas></div>`;
    const good = (v) => (lowerBetter ? v <= 1 - BAND : v >= 1 + BAND), bad = (v) => (lowerBetter ? v >= 1 + BAND : v <= 1 - BAND);
    const color = (v) => (v == null ? '#cbd5e1' : good(v) ? 'rgba(5,150,105,0.85)' : bad(v) ? 'rgba(217,119,6,0.85)' : '#94a3b8');
    const band = { id: 'band', beforeDatasetsDraw(ch) {
      const { ctx, chartArea: a, scales: { x: sx } } = ch; ctx.save(); ctx.fillStyle = 'rgba(148,163,184,0.18)';
      ctx.fillRect(sx.getPixelForValue(1 - BAND), a.top, sx.getPixelForValue(1 + BAND) - sx.getPixelForValue(1 - BAND), a.bottom - a.top);
      ctx.strokeStyle = '#475569'; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(sx.getPixelForValue(1), a.top); ctx.lineTo(sx.getPixelForValue(1), a.bottom); ctx.stroke(); ctx.restore(); } };
    const ch = new Chart(host.querySelector('canvas'), {
      type: 'bar', data: { labels: items.map((i) => i.label), datasets: [{ data: items.map((i) => i.value), backgroundColor: items.map((i) => color(i.value)), borderRadius: 2 }] },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
        scales: { x: { min: 0, suggestedMax: 1.4, title: { display: true, text: title } }, y: { ticks: { autoSkip: false } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${x(c.parsed.x)} · ${items[c.dataIndex].detail}` } } } },
      plugins: [band],
    });
    return { destroy() { ch.destroy(); } };
  };
  function comparison() {
    const list = C[group.value][mode.value];
    slot('comparison-note').textContent = mode.value === 'observed'
      ? '품질 플래그를 포함한 전체 관측입니다. 서버 성능의 확정 순위가 아닙니다.'
      : '각 대상과 m7i 양쪽이 판정을 통과한 같은 구간만 합산합니다. 비교 가능한 구간이 없으면 —로 표시합니다.';
    slot('comparison').innerHTML = `<div class="table-scroll" tabindex="0"><table class="report-table"><thead><tr><th>인스턴스</th><th>구간 / 시간</th><th>성공 RPS</th><th>m7i 대비</th><th>p99 ms</th><th>p99 배수</th><th>미발생 %</th></tr></thead><tbody>${list.map((r) => {
      const a = r.target;
      return `<tr><td><strong>${r.instance}</strong></td><td>${a ? `${a.phases} / ${cell(a.hours, 2)}h` : '0 / 0h'}</td><td>${cell(a?.success_rps, 0)}</td><td><strong>${r.rps_ratio == null ? '—' : x(r.rps_ratio)}</strong></td><td>${cell(a?.p99_ms)}</td><td><strong>${r.p99_ratio == null ? '—' : x(r.p99_ratio)}</strong></td><td>${cell(a?.drop_pct, 2)}</td></tr>`;
    }).join('')}</tbody></table></div>`;
    barHandles.forEach((h) => h.destroy());
    const it = (k, det) => list.filter((r) => r.instance !== BASE).map((r) => ({ label: short(r.instance), value: r[k], detail: r.target ? det(r.target) : '비교 구간 없음' }));
    barHandles = [
      bars(slot('cmp-rps'), it('rps_ratio', (a) => `${fmt(a.success_rps)} RPS · 미발생 ${fmt(a.drop_pct, 2)}%`), { title: '성공 처리량 ÷ m7i (높을수록 유리)' }),
      bars(slot('cmp-p99'), it('p99_ratio', (a) => `p99 ${fmt(a.p99_ms, 2)}ms`), { title: 'p99 ÷ m7i (낮을수록 유리)', lowerBetter: true }),
    ];
  }
  group.addEventListener('change', comparison); mode.addEventListener('change', comparison); comparison();
  handles.push({ destroy() { group.removeEventListener('change', comparison); mode.removeEventListener('change', comparison); barHandles.forEach((h) => h.destroy()); } });

  // ---------- 피크 길이별 (둘째 날 1/5/15/60분 피크) ----------
  const PEAKS = [['peak_60s', '1분 피크'], ['peak_300s', '5분 피크'], ['peak_900s', '15분 피크'], ['peak_3600s', '60분 피크']].filter(([g]) => C[g]);
  const others = names.filter((n) => n !== BASE);
  const peakChart = (host, key, title, lowerBetter) => {
    host.innerHTML = '<div class="chart-box" style="height:320px"><canvas></canvas></div>';
    const ch = new Chart(host.querySelector('canvas'), {
      type: 'line',
      data: { labels: PEAKS.map(([, l]) => l), datasets: others.map((n) => ({ label: short(n), inst: n, data: PEAKS.map(([g]) => cmp(g, 'observed', n)?.[key] ?? null), ...style(n, arch(n)), pointRadius: 4, pointHoverRadius: 7, tension: 0 }))
        .concat([{ label: 'm7i = 1.00배', data: PEAKS.map(() => 1), borderColor: '#475569', borderDash: [2, 4], pointRadius: 0 }]) },
      options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
        scales: { y: { title: { display: true, text: title } }, x: { title: { display: true, text: '피크 지속 시간 (각 6회 합산, 전체 관측)' } } },
        plugins: { legend: { position: 'bottom' }, tooltip: {
          itemSort: (a, b) => (lowerBetter ? a.parsed.y - b.parsed.y : b.parsed.y - a.parsed.y),
          callbacks: { label: (c) => {
            const r = c.dataset.inst ? cmp(PEAKS[c.dataIndex][0], 'observed', c.dataset.inst) : null;
            return r?.target ? `${c.dataset.label}: ${x(c.parsed.y)} · ${fmt(r.target.success_rps)} RPS · p99 ${fmt(r.target.p99_ms, 1)}ms · 미발생 ${fmt(r.target.drop_pct, 1)}%` : c.dataset.label;
          } } } } },
    });
    handles.push({ destroy() { ch.destroy(); } });
  };
  peakChart(slot('peak-rps'), 'rps_ratio', '성공 처리량 ÷ m7i', false);
  peakChart(slot('peak-p99'), 'p99_ratio', 'p99 ÷ m7i', true);
  const trend = (n) => { const v = PEAKS.map(([g]) => cmp(g, 'observed', n)?.rps_ratio).filter((q) => q != null); return v.length > 1 ? `${short(n)} ${x(v[0])} → ${x(v[v.length - 1])}` : ''; };
  slot('peak-lead').innerHTML = `<p>Flex 인스턴스가 긴 피크에서 따로 밀리는지 보는 그림입니다. 1분 → 60분 피크로 갈 때 m7i 대비 처리량은 ${['m7i-flex.xlarge', 'm8i-flex.xlarge', 'm8i.xlarge'].map(trend).filter(Boolean).join(', ')}입니다. 피크 길이별 합산만으로 시간에 따른 저하를 판단할 수 없어, 아래 안정성 분석에서 같은 길이의 반복을 전반·후반으로 나눠 비교합니다. Flex의 내부 제한 원인이나 T 계열 CPU 크레딧 고갈을 입증하는 측정은 아닙니다.</p>`;

  // ---------- 48시간 변화 (구간 종류·지표·표시 선택) ----------
  const PH = e.phases.filter((p) => p.finished);
  const maxRate = Math.max(...PH.map((q) => q.rate_rps)), minRate = Math.min(...PH.map((q) => q.rate_rps));
  const KIND = {
    peak: { label: '피크 구간 (목표 ≥ 최고의 90%)', test: (p) => p.rate_rps >= 0.9 * maxRate },
    low: { label: '평상시 구간 (가장 낮은 단계)', test: (p) => p.rate_rps <= 1.01 * minRate },
    all: { label: '모든 구간', test: () => true },
  };
  const MET = {
    rps: { label: '성공 RPS', get: (r) => r.success_rps, axis: '성공 RPS' },
    p99: { label: 'p99 (ms)', get: (r) => r.p99_ms, axis: 'p99 ms (예정 시각부터 완료)' },
    p95: { label: 'p95 (ms)', get: (r) => r.p95_ms, axis: 'p95 ms' },
    drop: { label: '미발생 %', get: (r) => (r.offered ? (100 * r.dropped) / r.offered : null), axis: '미발생 요청 %' },
    cpu: { label: 'JVM CPU %', get: (r) => r.memory_gc?.jvm_cpu_mean_pct ?? null, axis: 'JVM CPU % (수집값)' },
    heap: { label: '최대 힙 (GiB)', get: (r) => (r.memory_gc?.heap_used_max_bytes != null ? r.memory_gc.heap_used_max_bytes / 2 ** 30 : null), axis: '관측 최대 힙 GiB' },
    gc: { label: '최대 GC pause (ms)', get: (r) => r.memory_gc?.gc_log_pause_max_ms ?? null, axis: '관측 최대 GC pause ms' },
  };
  const tsHost = slot('charts');
  tsHost.innerHTML = `<div class="ts-controls"><label>구간 <select data-ts="kind">${Object.entries(KIND).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}</select></label>`
    + `<label>지표 <select data-ts="metric">${Object.entries(MET).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}</select></label>`
    + '<label>표시 <select data-ts="view"><option value="ratio">m7i 대비 배수</option><option value="abs">원래 값</option></select></label></div>'
    + '<div class="chart-box" style="height:380px"><canvas aria-label="48시간 변화"></canvas></div>';
  const sel = (k) => tsHost.querySelector(`[data-ts="${k}"]`);
  const tsData = () => {
    const kind = KIND[sel('kind').value], m = MET[sel('metric').value], ratio = sel('view').value === 'ratio';
    const phs = PH.filter(kind.test);
    const ds = names.filter((n) => !(ratio && n === BASE)).map((n) => ({
      label: short(n), ...style(n, arch(n)), pointRadius: 3, pointHoverRadius: 6, tension: 0, spanGaps: true, borderWidth: n === BASE ? 3 : 2,
      data: phs.map((p) => { const v = m.get(p.instances[n]), b = m.get(p.instances[BASE]); return { x: p.hour_end, y: ratio ? (v != null && b ? v / b : null) : v, p, n }; }).filter((q) => q.y != null),
    }));
    if (ratio) ds.push({ label: 'm7i = 1.00배', data: [{ x: 0, y: 1 }, { x: 48, y: 1 }], borderColor: '#475569', borderDash: [2, 4], pointRadius: 0 });
    return { ds, y: ratio ? `${m.label} ÷ m7i` : m.axis };
  };
  const first = tsData();
  const ts = new Chart(tsHost.querySelector('canvas'), {
    type: 'line', data: { datasets: first.ds },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'nearest', intersect: false },
      scales: { x: { type: 'linear', min: 0, max: 48, title: { display: true, text: '측정 시작 후 시간 · 구간 종료' } }, y: { title: { display: true, text: first.y } } },
      plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: {
        title: (it) => (it[0]?.raw?.p ? `${it[0].raw.p.name} · ${fmt(it[0].raw.p.hour_end, 2)}h · 목표 ${fmt(it[0].raw.p.rate_rps)} RPS` : ''),
        label: (c) => { const q = c.raw; if (!q.p) return c.dataset.label; const r = q.p.instances[q.n];
          return `${c.dataset.label}: ${fmt(c.parsed.y, 3)} · ${fmt(r.success_rps)} RPS · p99 ${fmt(r.p99_ms, 2)}ms · 미발생 ${fmt(100 * (r.dropped_fraction || 0), 2)}%`; },
        afterLabel: (c) => (c.raw.p ? (c.raw.p.instances[c.raw.n].validation_errors || []).slice(0, 2).map((f) => `  · ${f}`) : []),
      } } } },
  });
  const onTs = () => { const d = tsData(); ts.data.datasets = d.ds; ts.options.scales.y.title.text = d.y; ts.update(); };
  ['kind', 'metric', 'view'].forEach((k) => sel(k).addEventListener('change', onTs));
  handles.push({ destroy() { ['kind', 'metric', 'view'].forEach((k) => sel(k).removeEventListener('change', onTs)); ts.destroy(); } });

  // ---------- 품질·메모리·보조 실험 표 ----------
  const cpu80 = (n) => PH.filter((p) => (p.instances[n].client_cpu_pct ?? 0) >= 80).length;
  slot('quality').innerHTML = `<div class="table-scroll" tabindex="0"><table class="report-table"><thead><tr><th>인스턴스</th><th>원래 판정 통과 /96</th><th>휴지 예외 후 /96</th><th>dispatch 지연 >25ms 구간</th><th>클라이언트 CPU ≥80% 구간</th><th>JVM 재시작</th></tr></thead><tbody>${Object.entries(e.quality).map(([n, q]) => `<tr><td><strong>${n}</strong></td><td>${q.original_valid}</td><td>${q.idle_qualified}</td><td>${q.dispatch_flag_phases ?? '—'}</td><td>${cpu80(n)}</td><td>${q.uptime_resets}</td></tr>`).join('')}</tbody></table></div>`;
  slot('memory').innerHTML = `<div class="table-scroll" tabindex="0"><table class="report-table"><thead><tr><th>인스턴스</th><th>평균 / 최대 힙 GiB</th><th>GC 횟수 ≥</th><th>GC 정지 합계 ≥ 초</th><th>최대 GC pause ms</th><th>JVM CPU 평균</th></tr></thead><tbody>${names.map((n) => { const i = e.instances[n];
    return `<tr><td><strong>${n}</strong></td><td>${cell(i.heap_mean_gib, 2)} / ${cell(i.heap_max_gib, 2)}</td><td>${fmt(i.gc_count_lower_bound)}</td><td>${cell(i.gc_pause_seconds_lower_bound, 1)}</td><td>${cell(i.gc_pause_max_ms, 1)}</td><td>${i.cpu_pct != null ? `${fmt(i.cpu_pct, 0)}%` : '—'}</td></tr>`; }).join('')}</tbody></table></div>`;
  const S = e.supplemental_flex48 || {};
  slot('flex48').innerHTML = Object.keys(S).length ? `<div class="table-scroll" tabindex="0"><table class="report-table"><thead><tr><th>인스턴스</th><th>표본 (마지막 경과)</th><th>첫 1시간 평균 RPS</th><th>마지막 30표본 평균 RPS</th><th>변화</th><th>마지막 30표본 p99 중앙값</th></tr></thead><tbody>${Object.entries(S).map(([n, s]) => `<tr><td><strong>${n}</strong></td><td>${fmt(s.samples)} (${fmt(s.last_elapsed_seconds / 3600, 1)}h)</td><td>${fmt(s.first_hour_probe_rps_mean)}</td><td>${fmt(s.last30_probe_rps_mean)}</td><td><strong>${s.change_pct > 0 ? '+' : ''}${fmt(s.change_pct, 1)}%</strong></td><td>${cell(s.last30_per_probe_p99_median_ms, 2)}ms</td></tr>`).join('')}</tbody></table></div>` : '';
  slot('downloads').innerHTML = [['README.md', '전체 리포트'], ['phases.csv', '구간 CSV'], ['comparisons.csv', '비교 CSV'], ['tables.md', '전체 비교표'], ['raw/manifest.json', '원본 체크섬'], ['raw', '원본 조각'], ['timeseries.png', '차트 PNG']].map(([p, n]) => `<a href="${REPO + p}">${n}</a>`).join(' · ');
  handles.push(renderStability(root, stability));
  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
