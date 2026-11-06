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
  const head = ['인스턴스', '프로세서', 'USD/시간', A.metric.label, `성능 (${short(A.baseline)} 대비)`, `가격 대비 성능 (${short(A.baseline)} 대비)`];
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

// ---------------------------------------------------------------------------
// 표준 리포트 골격 — analysis 블록 하나(A)로 리포트 섹션 전체를 hostEl 안에 생성한다.
// 각 탭은 cfg로 지표 이름·단위·자릿수, 보조 시나리오(extra scenarios), 벤치마크 고유 서사(lead/notes)만 준다.
// 문장은 전부 A의 값으로 조립한다(숫자 하드코딩 금지). SpringBoot 탭은 이 골격을 쓰지 않고 수동 구성(파일럿).
// cfg = { title, unit, digits, scenarios:[{name, pair}], leadHtml, recsExtra:[...], numberPrefix }
// ---------------------------------------------------------------------------
const STEP = (A, a, b) => A.uplift.flatMap((u) => u.steps).find((s) => s.from === a && s.to === b);
const PAIR = (A, a, b) => [...A.pairs, ...A.flex_pairs, ...A.amd_pairs].find((q) => q.left === a && q.right === b);

/** 다른 analysis 블록의 짝을 종합 판정 시나리오 행으로. */
export function scenario(A, name, left, right) {
  if (!A) return null; // 분석 블록이 아직 없음(측정 진행 중)
  const q = PAIR(A, left, right);
  return q ? { name, ...q } : null;
}

export function standardReport(hostEl, rows, A, cfg = {}) {
  if (!A) { // 분석 블록이 아직 없음(측정 진행 중 등) — 탭의 나머지 섹션은 계속 그린다
    hostEl.innerHTML = '<section class="section report-lead"><p class="description">리포트 분석 데이터를 수집하는 중입니다. 모든 측정이 끝나면 핵심 결과와 판정이 표시됩니다.</p></section>';
    return { destroy() { hostEl.innerHTML = ''; } };
  }
  const handles = [];
  const unit = cfg.unit ?? A.metric.unit;
  const digits = cfg.digits ?? 0;
  const lower = A.metric.direction === 'min';
  const T = A.table;
  const odd = new Set(A.peer_outliers.map((o) => o.left));
  const topPerf = A.rank_perf.find((n) => !odd.has(n));
  const topPpd = A.rank_ppd.find((n) => !odd.has(n));
  // cfg.pairFamily: 대표 짝 비교 패밀리(기본 c). 메모리 압박처럼 C가 기준으로 부적합한 벤치마크는 m/r을 지정
  const pf = cfg.pairFamily || 'c';
  const g8 = PAIR(A, `${pf}8g.xlarge`, `${pf}8i.xlarge`);
  const g7 = PAIR(A, `${pf}7g.xlarge`, `${pf}7i.xlarge`);
  const g9 = pf === 'c' ? PAIR(A, 'c9g.xlarge', 'c8i.xlarge') : null;
  const upG = STEP(A, `${pf}7g.xlarge`, `${pf}8g.xlarge`);
  const upG5 = pf === 'c' ? STEP(A, 'c8g.xlarge', 'c9g.xlarge') : null;
  const upI = STEP(A, `${pf}7i.xlarge`, `${pf}8i.xlarge`);
  const n = (k) => `${cfg.numberPrefix || ''}${k}`;
  const sec = (id, title, inner) => `<section class="section" id="${id}"><h2>${title}</h2>${inner}</section>`;
  const slots = {};
  const s = (name) => { slots[name] = true; return `<div data-r="${name}"></div>`; };
  const cap = (t) => `<p class="caption">${t}</p>`;
  const P = (t) => (t ? `<p>${t}</p>` : '');
  const fmtv = (v) => `${fmt(v, digits)} ${unit}`;
  const dirWord = lower ? '짧을수록(낮을수록) 좋습니다' : '높을수록 좋습니다';

  const lead = [
    `${Object.keys(T).length}개 인스턴스를 <strong>${A.metric.label}</strong>(${unit}, ${dirWord}) 기준으로, 회차 중앙값을 써서 비교했습니다. 기준선은 ${A.baseline} = 1.00배, 가격은 서울 리전 Linux On-Demand입니다.`,
    g8 ? `8세대끼리는 ${pf}8g/${pf}8i가 성능 ${x(g8.perf)}, 가격 ${x(g8.price)}로 가격 대비 성능 <strong>${x(g8.ppd)} (${g8.verdict})</strong>${g7 ? `이고, 7세대 ${pf}7g/${pf}7i는 ${x(g7.ppd)}(${g7.verdict})` : ''}입니다.${g9 ? ` Graviton5 c9g는 c8i 대비 ${x(g9.ppd)}(${g9.verdict})입니다.` : ''}` : '',
  ];
  const kf = [
    topPerf && { item: `${A.metric.label} 1위`, result: topPerf, note: `${fmtv(T[topPerf].value)} · ${A.baseline} 대비 ${x(T[topPerf].perf)}` },
    topPpd && { item: '가격 대비 성능 1위', result: topPpd, note: `${A.baseline} 대비 ${x(T[topPpd].ppd)}` },
    g8 && { item: 'Graviton4 vs Intel 8세대', result: `${pf}8g / ${pf}8i ${x(g8.ppd)}`, note: `성능 ${x(g8.perf)}, 가격 ${x(g8.price)} — ${g8.verdict}` },
    g9 && { item: 'Graviton5 vs Intel 8세대', result: `c9g / c8i ${x(g9.ppd)}`, note: `성능 ${x(g9.perf)}, 가격 ${x(g9.price)} — ${g9.verdict}` },
    upG && { item: 'Graviton3 → Graviton4', result: pct(upG.perf - 1), note: `${pf}7g → ${pf}8g, 가격 대비 성능 ${pct(upG.ppd - 1)}` },
    upG5 && { item: 'Graviton4 → Graviton5', result: pct(upG5.perf - 1), note: `c8g → c9g, 가격 대비 성능 ${pct(upG5.ppd - 1)}` },
    upI && { item: 'Sapphire Rapids → Granite Rapids', result: pct(upI.perf - 1), note: `${pf}7i → ${pf}8i, 가격 대비 성능 ${pct(upI.ppd - 1)}` },
    { item: '신뢰도 경고', result: `${A.flagged.length}개`, note: A.peer_outliers.length ? `같은 프로세서 이상치: ${A.peer_outliers.map((o) => `${short(o.left)}/${short(o.right)} ${x(o.perf)}`).join(', ')}` : '같은 프로세서 이상치 없음' },
  ].filter(Boolean);

  const scen = [
    ...['8', '7', '6'].flatMap((g) => ['c', 'm', 'r'].map((f) => PAIR(A, `${f}${g}g.xlarge`, `${f}${g}i.xlarge`)).filter(Boolean)
      .map((q) => ({ name: `${A.metric.label}, ${q.group} ${short(q.left)[0].toUpperCase()}`, ...q }))),
    ...(g9 ? [{ name: `${A.metric.label}, Graviton5 vs Intel 8세대`, ...g9 }] : []),
    ...(cfg.scenarios || []).filter(Boolean),
  ];
  const fam8 = A.families.find((f) => f[0].name === 'c8g.xlarge') || A.families[0];
  const fl8 = A.flex_pairs.filter((q) => q.group === '8세대' && q.verdict !== '재측정 필요');
  const amdAll = A.amd_pairs.length && A.amd_pairs.every((q) => q.verdict === 'Intel 우위');
  const recs = [
    topPpd && `${A.metric.label} 기준 가격 대비 성능은 <strong>${short(topPpd)}</strong>가 1위입니다(${A.baseline} 대비 ${x(T[topPpd].ppd)}). 절대 성능이 우선이면 ${short(topPerf)}(${x(T[topPerf].perf)})입니다.`,
    g8 && `8세대 C 패밀리에서는 ${g8.verdict === '비슷' ? 'c8g와 c8i가 가격 대비 성능이 비슷합니다' : `${g8.verdict.replace(' 우위', '')}가 가격 대비 성능에서 앞섭니다`}(c8g/c8i ${x(g8.ppd)}).`,
    upG && `Graviton3(c7g)에서 운영 중이라면 c8g로 바꾸는 것만으로 가격 대비 성능이 ${pct(upG.ppd - 1)} 달라집니다.`,
    fam8 && fam8.length > 1 && `메모리가 더 필요하지 않다면 C 패밀리가 유리합니다. ${short(fam8[0].name)} = 1.00배일 때 ${fam8.slice(1).map((r) => `${short(r.name)} ${x(r.ppd)}`).join(', ')}입니다.`,
    fl8.length && `8세대 Intel이 필요하면 flex를 검토하십시오(flex ÷ 표준 가격 대비 성능 ${xRange(fl8.map((q) => q.ppd))}).`,
    amdAll && `5세대 AMD는 같은 세대 Intel보다 가격 대비 성능이 ${A.amd_pairs.map((q) => `${short(q.left)} ${x(q.ppd)}`).join(', ')}로 뒤집니다.`,
    ...(cfg.recsExtra || []),
  ].filter(Boolean);

  hostEl.innerHTML = [
    `<section class="section report-lead">${P(lead.join(' '))}${cfg.leadHtml || ''}${s('kf')}${cap(`<strong>표 ${n(1)}.</strong> 핵심 결과`)}</section>`,
    sec('r-reliability', '측정 신뢰도', `${s('rel')}${cap(`<strong>표 ${n(2)}.</strong> 회차 간 변동이 크거나 같은 프로세서와 어긋나는 인스턴스`)}`),
    sec('r-rank', `${A.metric.label} 순위`, `${s('rank')}${cap(`<strong>그림 ${n(1)}.</strong> 막대 = 회차 중앙값, 점 = 회차별 값 (${unit}, ${dirWord}). 진한 막대는 8세대 이상.`)}`),
    sec('r-price', '가격 대비 성능', `${s('price')}${cap(`<strong>표 ${n(3)}.</strong> 가격 대비 성능 상위 15개`)}`),
    sec('r-pairs', '같은 세대의 Graviton과 Intel', `${P('xlarge의 vCPU 4개는 Graviton에서 물리 코어 4개, Intel/AMD에서 물리 코어 2개 × 하이퍼스레딩입니다.')}${s('pairs-chart')}${cap(`<strong>그림 ${n(2)}.</strong> 가격 대비 성능 (Graviton ÷ Intel). 회색 띠는 ±${A.band * 100}%`)}${s('pairs')}<h3>5세대 AMD와 Intel</h3>${s('amd')}`),
    sec('r-uplift', '세대 간 향상', `${s('uplift-chart')}${cap(`<strong>그림 ${n(3)}.</strong> 이전 세대(빈 원) → 다음 세대(채운 원)`)}${s('uplift')}`),
    sec('r-family', '패밀리(C/M/R)와 flex', `${s('family')}<h3>flex와 표준</h3>${s('flex')}`),
    sec('r-verdict', '종합 판정과 권고', `${s('verdict-chart')}${cap(`<strong>그림 ${n(4)}.</strong> 시나리오별 가격 대비 성능 (왼쪽 ÷ 오른쪽)`)}${s('verdict')}${cap(bandNote(A))}<h3>권고</h3><ul class="recs">${recs.map((r) => `<li>${r}</li>`).join('')}</ul>`),
  ].join('');
  const at = (k) => hostEl.querySelector(`[data-r="${k}"]`);
  handles.push(keyFindings(at('kf'), kf));
  handles.push(reliability(at('rel'), A, { unit, digits,
    extra: [`경고 임계값: 회차 간 변동계수 ${A.thresholds.cv}% · 회차 최대/최소 ${A.thresholds.spread}배 · 같은 프로세서 짝 차이 ±${A.thresholds.peer * 100}%.`] }));
  handles.push(dotBar(at('rank'), rows, A, { names: A.rank_perf, digits, unit }));
  handles.push(priceTable(at('price'), rows, A, { digits, limit: 15 }));
  handles.push(ratioBars(at('pairs-chart'), A.pairs.map((q) => ({ label: `${short(q.left)} / ${short(q.right)}`, value: q.ppd })), { band: A.band, title: '가격 대비 성능 (Graviton ÷ Intel)' }));
  handles.push(pairTable(at('pairs'), A.pairs));
  handles.push(pairTable(at('amd'), A.amd_pairs));
  handles.push(dumbbell(at('uplift-chart'), rows, A, { digits, unit }));
  handles.push(upliftTable(at('uplift'), rows, A));
  handles.push(familyTable(at('family'), rows, A));
  handles.push(pairTable(at('flex'), A.flex_pairs));
  handles.push(ratioBars(at('verdict-chart'), scen.map((q) => ({ label: q.name, value: q.ppd })), { band: A.band }));
  const vt = at('verdict');
  vt.innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>시나리오</th><th>비교</th><th>성능</th><th>가격</th><th>가격 대비 성능</th><th>판정</th></tr></thead><tbody>${
    scen.map((q) => `<tr><td>${q.name}</td><td>${short(q.left)} / ${short(q.right)}</td><td>${x(q.perf)}</td><td>${q.price == null ? '—' : x(q.price)}</td><td><strong>${x(q.ppd)}</strong></td><td>${verdictBadge(q.verdict)}</td></tr>`).join('')}</tbody></table></div>`;
  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); hostEl.innerHTML = ''; } };
}
