// 리포트형 렌더러 — scripts/dashboard/analysis.py가 만든 envelope.analysis.<metric> 블록을 그린다.
// 숫자 계산은 전부 Python 쪽에서 끝나 있어야 하고(검증 지점 단일화), 여기서는 정렬·표시·문장 조립만 한다.
// 구조 참고: graviton-intel-springboot-benchmark.pdf(핵심 결과표 → 신뢰도 → 기준선 배수 → 짝 비교 →
// 세대 향상 → 판정 → 권고). shared.js와 같은 계약: 각 함수는 (hostEl, ...) → {destroy()}.
import { ARCH_COLOR, ARCH_LABEL, archColor, fmt } from './shared.js';

const VERDICT_CLASS = { '비슷': 'verdict-even', '재측정 필요': 'verdict-hold' };

export const x = (v, d = 2) => (v == null ? '—' : `${v.toFixed(d)}배`);
export const pct = (v, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(d)}%`);
export const short = (name) => name.replace('.xlarge', '');
/** 값 목록의 범위를 'a~b배'로, 같으면 하나만. */
export const xRange = (vals, d = 2) => { const lo = Math.min(...vals), hi = Math.max(...vals); return lo.toFixed(d) === hi.toFixed(d) ? x(lo, d) : `${lo.toFixed(d)}~${x(hi, d)}`; };

function verdictBadge(v) {
  if (!v) return '—';
  const cls = VERDICT_CLASS[v] || (v.startsWith('Graviton') || v.startsWith('AMD') || v.startsWith('flex') ? 'verdict-left' : 'verdict-right');
  return `<span class="verdict ${cls}">${v}</span>`;
}

function table(hostEl, head, body, caption) {
  hostEl.innerHTML = `
    <div class="table-scroll"><table class="report-table">
      <thead><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr></thead>
      <tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div>
    ${caption ? `<p class="caption">${caption}</p>` : ''}`;
  return { destroy() { hostEl.innerHTML = ''; } };
}

function chartHost(hostEl, height) {
  hostEl.innerHTML = `<div class="chart-box" style="height:${height}px"><canvas></canvas></div>`;
  return hostEl.querySelector('canvas');
}

const rowMap = (rows) => Object.fromEntries(rows.map((r) => [r.name, r]));

/** 핵심 결과표: items = [{item, result, note}] */
export function keyFindings(hostEl, items) {
  return table(hostEl, ['항목', '결과', '비고'],
    items.map((i) => [i.item, `<strong>${i.result}</strong>`, i.note || '']));
}

/** 측정 대상 사양표 — instances.json의 hw(EC2/Pricing API) 사용. */
export function specTable(hostEl, rows, names) {
  const m = rowMap(rows);
  const body = names.filter((n) => m[n]?.hw).map((n) => {
    const r = m[n]; const h = r.hw;
    return [`<strong>${n}</strong>`, h.processor, h.cores, h.threads_per_core,
      h.clock_ghz ?? '—', h.mem_gib, `$${r.price.toFixed(4)}`];
  });
  return table(hostEl, ['인스턴스', '프로세서', '물리 코어', '코어당 스레드', '지속 클럭 (GHz)', '메모리 (GiB)', 'On-Demand (USD/시간)'],
    body, 'EC2 DescribeInstanceTypes(코어·스레드·클럭·메모리)와 Pricing API(프로세서명, 서울 리전 Linux On-Demand) 조회값입니다. xlarge의 vCPU 4개는 Graviton에서 물리 코어 4개, Intel/AMD에서 물리 코어 2개 × 하이퍼스레딩입니다.');
}

/** 신뢰도 표: 경고 인스턴스 먼저, 나머지는 요약 한 줄. */
export function reliability(hostEl, A, { unit, digits = 0, extra = [] } = {}) {
  const T = A.table;
  const names = Object.keys(T);
  const cvs = names.map((n) => T[n].cv).sort((a, b) => a - b);
  const median = cvs[Math.floor(cvs.length / 2)];
  const flagged = A.flagged.slice().sort((a, b) => T[b].cv - T[a].cv);
  const body = flagged.map((n) => [
    `<strong>${n}</strong>`, T[n].n, `${T[n].cv.toFixed(1)}%`,
    `${fmt(T[n].min, digits)} ~ ${fmt(T[n].max, digits)} ${unit}`,
    T[n].runs.map((v) => fmt(v, digits)).join(', '), T[n].flags.join(' · '),
  ]);
  const summary = `${names.length}개 인스턴스의 회차 간 변동계수 중앙값은 ${median.toFixed(1)}%입니다. `
    + `변동계수 3% 초과 또는 회차 최대/최소 1.10배 초과인 ${flagged.length}개를 아래에 표시했습니다. 이 인스턴스들의 순위는 단일 호스트의 특성일 수 있습니다.`;
  hostEl.innerHTML = `<p class="description">${summary}</p><div data-r></div>${extra.map((e) => `<p class="caption">${e}</p>`).join('')}`;
  const h = flagged.length
    ? table(hostEl.querySelector('[data-r]'), ['인스턴스', '회차', '변동계수', '범위', '회차 값', '경고'], body)
    : { destroy() {} };
  return { destroy() { h.destroy(); hostEl.innerHTML = ''; } };
}

/** 막대 = 회차 중앙값, 점 = 회차별 값. 최신 세대는 진하게, 이전 세대는 옅게(PDF 그림 2 방식). */
export function dotBar(hostEl, rows, A, { names, topN = 20, digits = 0, unit = '' } = {}) {
  const m = rowMap(rows);
  const T = A.table;
  const order = (names || A.rank_perf.slice(0, topN)).filter((n) => T[n] && m[n]);
  const canvas = chartHost(hostEl, Math.max(260, order.length * 24 + 60));
  const alpha = (n) => (m[n].gen >= 8 ? 0.9 : 0.4); // 8세대 이상(Intel 8th, Graviton4/5) 진하게
  const chart = new Chart(canvas, {
    data: {
      labels: order.map(short),
      datasets: [
        { type: 'bar', label: '회차 중앙값', data: order.map((n) => T[n].value),
          backgroundColor: order.map((n) => archColor(m[n].arch, alpha(n))), borderRadius: 2, order: 2 },
        { type: 'scatter', label: '회차별 값', pointRadius: 2.5, backgroundColor: '#1f2937', order: 1,
          data: order.flatMap((n) => T[n].runs.map((v) => ({ x: v, y: short(n) }))) },
      ],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
      scales: { x: { beginAtZero: true, title: { display: !!unit, text: unit } }, y: { type: 'category', ticks: { autoSkip: false } } },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => `${fmt(c.parsed.x, digits)} ${unit}` } },
      },
    },
  });
  return { destroy() { chart.destroy(); hostEl.innerHTML = ''; } };
}

/** 비율 막대 + ±band 음영 + 1.0 기준선. items = [{label, value, verdict}] */
export function ratioBars(hostEl, items, { band = 0.05, title = '', neutral = false, min = 0 } = {}) {
  const canvas = chartHost(hostEl, Math.max(200, items.length * 30 + 70));
  // neutral=true: 판정이 아닌 분포(재측정 드리프트 등) — 띠 밖은 주의색, 안은 회색
  const color = (v) => (v == null ? '#cbd5e1'
    : neutral ? (Math.abs(v - 1) > band ? 'rgba(217,119,6,0.8)' : '#94a3b8')
      : v >= 1 + band ? archColor('graviton', 0.85) : v <= 1 - band ? archColor('intel', 0.85) : '#94a3b8');
  const bandPlugin = {
    id: 'band',
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea: a, scales: { x: sx } } = chart;
      ctx.save();
      ctx.fillStyle = 'rgba(148,163,184,0.18)';
      ctx.fillRect(sx.getPixelForValue(1 - band), a.top, sx.getPixelForValue(1 + band) - sx.getPixelForValue(1 - band), a.bottom - a.top);
      ctx.strokeStyle = '#475569'; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(sx.getPixelForValue(1), a.top); ctx.lineTo(sx.getPixelForValue(1), a.bottom); ctx.stroke();
      ctx.restore();
    },
  };
  const chart = new Chart(canvas, {
    type: 'bar',
    data: { labels: items.map((i) => i.label), datasets: [{ data: items.map((i) => i.value), backgroundColor: items.map((i) => color(i.value)), borderRadius: 2 }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
      scales: { x: { min, suggestedMax: 1.3, title: { display: !!title, text: title } }, y: { ticks: { autoSkip: false } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => x(c.parsed.x) } } },
    },
    plugins: [bandPlugin],
  });
  return { destroy() { chart.destroy(); hostEl.innerHTML = ''; } };
}

/** 짝 비교 표 (Graviton ÷ Intel 등). */
export function pairTable(hostEl, pairs, { caption } = {}) {
  return table(hostEl, ['비교 (왼쪽 ÷ 오른쪽)', '세대', '성능', '가격', '가격 대비 성능', '판정'],
    pairs.map((p) => [`${short(p.left)} / ${short(p.right)}`, p.group || '', x(p.perf), x(p.price), `<strong>${x(p.ppd)}</strong>`, verdictBadge(p.verdict)]),
    caption);
}

/** 세대 향상 덤벨 차트: 각 step을 from(빈 원) → to(채운 원)로. */
export function dumbbell(hostEl, rows, A, { field = 'value', digits = 0, unit = '' } = {}) {
  const m = rowMap(rows);
  const T = A.table;
  const steps = A.uplift.flatMap((u) => u.steps);
  const labels = steps.map((s) => `${short(s.from)} → ${short(s.to)}`);
  const canvas = chartHost(hostEl, Math.max(240, steps.length * 28 + 60));
  const val = (n) => (field === 'ppd' ? T[n].value / m[n].price : T[n].value);
  const datasets = steps.map((s, i) => ({
    type: 'line', data: [{ x: val(s.from), y: labels[i] }, { x: val(s.to), y: labels[i] }],
    borderColor: archColor(m[s.to].arch, 0.9), backgroundColor: ['#fff', archColor(m[s.to].arch, 0.95)],
    pointBorderColor: archColor(m[s.to].arch, 0.95), pointRadius: 5, pointBorderWidth: 2, showLine: true,
  }));
  const chart = new Chart(canvas, {
    data: { labels, datasets },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
      scales: { x: { beginAtZero: true, title: { display: !!unit, text: unit } }, y: { type: 'category', ticks: { autoSkip: false } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataIndex === 0 ? '이전' : '신규'}: ${fmt(c.parsed.x, digits)} ${unit}` } } },
    },
  });
  return { destroy() { chart.destroy(); hostEl.innerHTML = ''; } };
}

export function upliftTable(hostEl, rows, A) {
  const m = rowMap(rows);
  const body = A.uplift.flatMap((u) => u.steps.map((s) => [
    `${short(s.from)} → ${short(s.to)}`, `${m[s.from].hw?.processor || ''} → ${m[s.to].hw?.processor || ''}`,
    pct(s.perf - 1), pct(s.price - 1), `<strong>${pct(s.ppd - 1)}</strong>`,
  ]));
  return table(hostEl, ['비교', '프로세서', '성능 변화', '가격 변화', '가격 대비 성능 변화'], body);
}

/** 같은 프로세서의 C/M/R: 성능은 비슷한데 가격이 올라가는지. */
export function familyTable(hostEl, rows, A) {
  const m = rowMap(rows);
  const body = A.families.flatMap((fam) => fam.map((r, i) => [
    i === 0 ? `<strong>${short(r.name)}</strong>` : short(r.name), `${m[r.name].hw?.mem_gib ?? '—'} GiB`,
    x(r.perf), x(r.price), `<strong>${x(r.ppd)}</strong>`,
  ]));
  return table(hostEl, ['인스턴스 (패밀리 첫 행 = 기준)', '메모리', '성능', '가격', '가격 대비 성능'], body,
    '같은 프로세서의 C/M/R은 메모리가 2배씩 늘고 가격이 오릅니다. 성능이 같다면 늘어난 메모리를 쓰지 않는 워크로드에서는 가격 대비 성능이 떨어집니다.');
}

/** 가격·성능 요약 (가격 대비 성능 순). */
export function priceTable(hostEl, rows, A, { digits = 0, limit = 15 } = {}) {
  const m = rowMap(rows);
  const T = A.table;
  const cu = A.cost_unit;
  const head = ['인스턴스', '프로세서', 'USD/시간', A.metric.label, '성능 (c7i 대비)', '가격 대비 성능 (c7i 대비)'];
  if (cu) head.push(cu.label);
  const body = A.rank_ppd.slice(0, limit).map((n) => {
    const r = [`<strong>${n}</strong>`, m[n]?.hw?.processor || '', `$${m[n].price.toFixed(4)}`,
      `${fmt(T[n].value, digits)} ${A.metric.unit}`, x(T[n].perf), `<strong>${x(T[n].ppd)}</strong>`];
    if (cu) r.push(T[n].cost != null ? `$${T[n].cost.toFixed(2)}` : '—');
    return r;
  });
  return table(hostEl, head, body,
    `가격 대비 성능 = 성능 배수 ÷ 시간당 가격 배수 (기준 ${A.baseline} = 1.00배). ${cu ? `${cu.label}은 측정 처리량이 계속 유지된다고 가정한 추정치입니다.` : ''}`);
}

/** 판정 규칙 설명 문구. */
export function bandNote(A) {
  const b = Math.round(A.band * 100);
  return `가격 대비 성능 배수가 ${(1 + A.band).toFixed(2)}배 이상이면 왼쪽 우위, ${(1 - A.band).toFixed(2)}배 이하이면 오른쪽 우위, 그 사이(±${b}%)는 비슷으로 판정했습니다.`;
}

export { ARCH_COLOR, ARCH_LABEL };
