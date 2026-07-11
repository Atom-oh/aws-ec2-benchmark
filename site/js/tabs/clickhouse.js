// ClickHouse — 이미 데이터 주도인 레거시 리포트를 표준 컴포넌트+bespoke SLOT B로 이식.
// SLOT B: per-query 탐색기(드롭다운+필터+SQL+차트+테이블), breakdown 그루핑 탭,
// iso-value 컨투어 버블. 계산 로직은 레거시 renderCharts/drawQuery/drawBreakdown를 그대로 포팅.
import {
  buildToc, summaryCards, topNBar, metricTabChart, familyChart, genImprovement, priceSection, resultTable, fmt, ARCH_COLOR,
} from '../shared.js';

export async function render(root, { rows, envelope }) {
  const handles = [];
  const wh = rows.filter((r) => r.hot_total_s != null);
  const best = [...wh].sort((a, b) => a.hot_total_s - b.hot_total_s)[0];
  const bestVal = rows.filter((r) => r.value).sort((a, b) => b.value - a.value)[0];
  const bestIns = rows.filter((r) => r.insert_rps).sort((a, b) => b.insert_rps - a.insert_rps)[0];
  const gravitonAvg = avg(wh.filter((r) => r.arch === 'graviton').map((r) => r.hot_total_s));
  const intelAvg = avg(wh.filter((r) => r.arch === 'intel').map((r) => r.hot_total_s));
  const r32 = avg(wh.filter((r) => r.mem_mb === 32768).map((r) => r.hot_total_s));
  const r8 = avg(wh.filter((r) => r.mem_mb === 8192).map((r) => r.hot_total_s));

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최速 (hot 합계)', value: best.name, detail: `${best.hot_total_s}s` },
    { label: '최고 가성비', value: bestVal.name, detail: `speed/$ ${bestVal.value}` },
    { label: '최고 INSERT', value: bestIns.name, detail: `${fmt(bestIns.insert_rps)} rows/s` },
    { label: 'Graviton vs Intel', value: `${pct(gravitonAvg, intelAvg).toFixed(1)}%`, detail: 'hot 평균 빠름' },
    { label: '32GB vs 8GB', value: `${pct(r32, r8).toFixed(0)}%`, detail: 'R패밀리가 C패밀리보다 빠름' },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="hot-top"]'), wh, {
    metrics: [{ field: 'hot_total_s', label: 'Hot 합계', unit: 's (낮을수록 좋음)', direction: 'min' }],
    n: 54,
  }));
  const worst = [...wh].sort((a, b) => b.hot_total_s - a.hot_total_s)[0];
  root.querySelector('[data-slot="hot-insight"]').innerHTML = `<h4>핵심</h4><ul>
    <li>최速 <strong>${best.name}</strong> ${best.hot_total_s}s vs 최저 ${worst.name} ${worst.hot_total_s}s (${(worst.hot_total_s / best.hot_total_s).toFixed(1)}배 차이)</li>
    <li>상위권은 32GB(R)·16GB(M) Graviton이 점유</li>
  </ul>`;

  // 컨투어 버블 (iso-value: value = speed/price = (1000/hot)/price 일정 → hot = 1000/(V*price))
  const bubbleCanvas = root.querySelector('[data-slot="contour-bubble"]');
  const bpts = wh.filter((r) => r.price && r.value);
  const vAll = bpts.map((r) => r.value);
  const vmin = Math.min(...vAll), vmax = Math.max(...vAll);
  const rad = (v) => (vmax === vmin ? 14 : 8 + ((v - vmin) / (vmax - vmin)) * 26);
  const byArch = {};
  bpts.forEach((r) => { (byArch[r.arch] = byArch[r.arch] || []).push({ x: r.price, y: r.hot_total_s, r: rad(r.value), val: r.value, label: r.name }); });
  const prices = bpts.map((r) => r.price);
  const pmin = Math.min(...prices), pmax = Math.max(...prices);
  const xs = Array.from({ length: 61 }, (_, i) => pmin + ((pmax - pmin) * i) / 60);
  const lvLo = Math.ceil(vmin / 10) * 10, lvHi = Math.floor(vmax / 10) * 10;
  const levels = [];
  for (let v = lvLo; v <= lvHi; v += 10) levels.push(v);
  const contours = levels.map((V) => ({
    type: 'line', label: `가성비 ${V}`, data: xs.map((x) => ({ x, y: Math.round(1000 / (V * x)) })),
    borderColor: '#cbd5e1', borderDash: [5, 4], borderWidth: 1, pointRadius: 0, fill: false, order: 99, tension: 0.3,
  }));
  const bubbleDs = Object.entries(byArch).map(([a, p]) => ({ label: a, data: p, backgroundColor: `${ARCH_COLOR[a]}b3`, borderColor: ARCH_COLOR[a], borderWidth: 1, order: 1 }));
  const bubbleChart = new Chart(bubbleCanvas, {
    type: 'bubble',
    data: { datasets: [...contours, ...bubbleDs] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        tooltip: { callbacks: { label: (c) => (c.raw && c.raw.label ? `${c.raw.label}: $${c.raw.x}/hr · ${c.raw.y}s · 가성비 ${c.raw.val}` : '') } },
        legend: { labels: { filter: (i) => !i.text.startsWith('가성비') } },
      },
      scales: {
        x: { beginAtZero: true, min: 0, title: { display: true, text: '시간당 가격 ($) — 왼쪽일수록 저렴' } },
        y: { beginAtZero: true, min: 0, suggestedMax: Math.max(...bpts.map((r) => r.hot_total_s)) * 1.1, title: { display: true, text: 'hot 합계 (s) — 아래일수록 빠름' } },
      },
    },
  });
  handles.push({ destroy() { bubbleChart.destroy(); } });

  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), wh, [
    { field: 'hot_total_s', label: 'Hot 합계', unit: 's', direction: 'min' },
  ]));
  handles.push(familyChart(root.querySelector('[data-slot="family"]'), wh, { field: 'hot_total_s', unit: 's' }));

  // Breakdown 탭 (arch/label/family)
  const bdCanvas = root.querySelector('[data-slot="breakdown-chart"]');
  let bdChart = null;
  function drawBreakdown(key) {
    const g = {};
    wh.forEach((r) => { (g[r[key]] = g[r[key]] || []).push(r.hot_total_s); });
    const keys = Object.keys(g).sort();
    if (bdChart) bdChart.destroy();
    bdChart = new Chart(bdCanvas, {
      type: 'bar',
      data: { labels: keys, datasets: [{ label: '평균 hot(s)', data: keys.map((k) => +avg(g[k]).toFixed(2)), backgroundColor: keys.map((k) => ARCH_COLOR[k] || '#8b5cf6') }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, title: { display: true, text: `${key}별 평균` } } },
    });
  }
  drawBreakdown('arch');
  const bdListeners = [];
  root.querySelectorAll('[data-slot="breakdown-tabs"] .tab-btn').forEach((btn) => {
    const onClick = () => {
      root.querySelectorAll('[data-slot="breakdown-tabs"] .tab-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      drawBreakdown(btn.dataset.k);
    };
    btn.addEventListener('click', onClick);
    bdListeners.push([btn, onClick]);
  });
  handles.push({ destroy() { if (bdChart) bdChart.destroy(); bdListeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } });

  // RAM 티어
  const ramHost = root.querySelector('[data-slot="ram"]');
  ramHost.innerHTML = '<div class="grid-2"><div class="chart-container"><canvas></canvas></div><div class="chart-container"><canvas></canvas></div></div>';
  const [ramCanvas, ramPairCanvas] = ramHost.querySelectorAll('canvas');
  const tiers = [[8192, '8GB(C)'], [16384, '16GB(M)'], [32768, '32GB(R)']];
  const ramChart = new Chart(ramCanvas, {
    type: 'bar',
    data: { labels: tiers.map((t) => t[1]), datasets: [{ label: '평균 hot(s)', data: tiers.map((t) => avgBy(wh, (r) => r.mem_mb === t[0])), backgroundColor: ['#f59e0b', '#3b82f6', '#10b981'] }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { title: { display: true, text: '평균 hot(s) — 낮을수록 좋음' } } } },
  });
  const pairBase = [['c8g', 'm8g', 'r8g', 'Graviton4'], ['c8i', 'm8i', 'r8i', 'Intel8th'], ['c7g', 'm7g', 'r7g', 'Graviton3']];
  const q32 = 'q32';
  const pds = pairBase.map(([c, m, r, lbl], i) => {
    const get = (n) => { const o = rows.find((x) => x.name === `${n}.xlarge`); return o && o.per_query_ms ? o.per_query_ms[q32] : null; };
    return { label: lbl, data: [get(c), get(m), get(r)], backgroundColor: ['#f59e0b', '#3b82f6', '#10b981'][i] || '#8b5cf6' };
  });
  const ramPairChart = new Chart(ramPairCanvas, {
    type: 'bar',
    data: { labels: ['8GB', '16GB', '32GB'], datasets: pds },
    options: { responsive: true, maintainAspectRatio: false, plugins: { title: { display: true, text: 'q32 (GROUP BY WatchID,ClientIP) hot ms' } }, scales: { y: { title: { display: true, text: 'ms (낮을수록 좋음)' } } } },
  });
  handles.push({ destroy() { ramChart.destroy(); ramPairChart.destroy(); } });
  const r16 = avgBy(wh, (r) => r.mem_mb === 16384);
  root.querySelector('[data-slot="ram-insight"]').innerHTML = `<h4>RAM 우위 확인</h4><ul>
    <li>평균 hot: 8GB ${r8?.toFixed(1)}s → 16GB ${r16?.toFixed(1)}s → 32GB ${r32?.toFixed(1)}s (단조 감소)</li>
    <li>RAM 상대 spill 임계(40%) + page cache로 큰 RAM일수록 디스크 spill·EBS 재읽기 감소</li>
  </ul>`;

  handles.push(genImprovement(root.querySelector('[data-slot="improvement"]'), wh, { field: 'hot_total_s', direction: 'min' }));

  handles.push(topNBar(root.querySelector('[data-slot="avoid"]'), wh, {
    metrics: [{ field: 'hot_total_s', label: 'Hot 합계', unit: 's', direction: 'min' }],
    n: 10,
    ascending: true,
  }));

  // INSERT / JOIN
  const insertJoinHost = root.querySelector('[data-slot="insert-join"]');
  insertJoinHost.innerHTML = '<div class="chart-container tall"><canvas></canvas></div><div class="chart-container tall" style="margin-top:1.5rem"><canvas></canvas></div>';
  const [insertCanvas, joinCanvas] = insertJoinHost.querySelectorAll('canvas');
  const ins = rows.filter((r) => r.insert_rps).sort((a, b) => b.insert_rps - a.insert_rps);
  const insertChart = new Chart(insertCanvas, {
    type: 'bar',
    data: { labels: ins.map((r) => r.name), datasets: [{ label: 'INSERT rows/sec', data: ins.map((r) => r.insert_rps), backgroundColor: ins.map((r) => ARCH_COLOR[r.arch]) }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { autoSkip: false, maxRotation: 90, minRotation: 90 } } } },
  });
  const jn = rows.filter((r) => r.join_ms != null).sort((a, b) => a.join_ms - b.join_ms);
  const joinChart = new Chart(joinCanvas, {
    type: 'bar',
    data: { labels: jn.map((r) => r.name), datasets: [{ label: 'JOIN(ms)', data: jn.map((r) => r.join_ms), backgroundColor: jn.map((r) => ARCH_COLOR[r.arch]) }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { autoSkip: false, maxRotation: 90, minRotation: 90 } } } },
  });
  handles.push({ destroy() { insertChart.destroy(); joinChart.destroy(); } });

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'mem_mb', label: '메모리', fmt: (v) => `${v / 1024}G` },
    { field: 'fits_in_ram', label: 'RAM', fmt: (v) => (v ? '✓' : '✗') },
    { field: 'hot_total_s', label: 'hot(s)', fmt: fmt },
    { field: 'speed', label: 'speed', fmt: fmt },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
    { field: 'value', label: '가성비', fmt: fmt },
    { field: 'insert_rps', label: 'INSERT rps', fmt: fmt },
    { field: 'join_ms', label: 'JOIN(ms)', fmt: fmt },
  ]));

  // 쿼리별 탐색기
  const queries = envelope.queries || { clickbench: [], insert: '', join: '' };
  const qSelect = root.querySelector('[data-slot="q-select"]');
  const qArch = root.querySelector('[data-slot="q-arch"]');
  const qFam = root.querySelector('[data-slot="q-family"]');
  const qSqlBox = root.querySelector('[data-slot="q-sql"]');
  const qChartCanvas = root.querySelector('[data-slot="q-chart"]');
  let qChart = null;
  const present = new Set();
  rows.forEach((r) => Object.keys(r.per_query_ms || {}).forEach((k) => present.add(k)));
  const qList = (queries.clickbench || []).map((q) => q.id).filter((i) => present.has(i));
  qSelect.innerHTML = qList.map((i) => `<option value="${i}">${i}</option>`).join('');

  function drawQueryChart() {
    const qid = qSelect.value;
    const sqlObj = (queries.clickbench || []).find((q) => q.id === qid);
    qSqlBox.textContent = sqlObj ? sqlObj.sql : '';
    let r = rows.filter((x) => x.per_query_ms && x.per_query_ms[qid] != null
      && (!qArch.value || x.arch === qArch.value) && (!qFam.value || x.family === qFam.value))
      .map((x) => ({ name: x.name, arch: x.arch, mem_mb: x.mem_mb, ms: x.per_query_ms[qid] }));
    r = r.sort((a, b) => a.ms - b.ms);
    if (qChart) { qChart.destroy(); qChart = null; }
    if (!r.length) return;
    qChart = new Chart(qChartCanvas, {
      type: 'bar',
      data: { labels: r.map((x) => x.name), datasets: [{ label: `${qid} hot(ms)`, data: r.map((x) => x.ms), backgroundColor: r.map((x) => ARCH_COLOR[x.arch]) }] },
      options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false }, title: { display: true, text: `${qid} — 인스턴스별 hot 지연` } }, scales: { x: { title: { display: true, text: 'ms' } } } },
    });
  }
  const qListeners = [[qSelect, 'change'], [qArch, 'change'], [qFam, 'change']];
  qListeners.forEach(([el, evt]) => el.addEventListener(evt, drawQueryChart));
  if (qList.length) drawQueryChart();
  handles.push({ destroy() { qListeners.forEach(([el, evt]) => el.removeEventListener(evt, drawQueryChart)); if (qChart) qChart.destroy(); } });

  // SQL 라이브러리
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  root.querySelector('[data-slot="q-list"]').innerHTML = (queries.clickbench || [])
    .map((q) => `<div><strong>${q.id}</strong> <code>${esc(q.sql)}</code></div>`).join('') || '<em>없음</em>';
  root.querySelector('[data-slot="ins-sql"]').textContent = queries.insert || '';
  root.querySelector('[data-slot="join-sql"]').textContent = queries.join || '';

  root.querySelector('[data-slot="conclusion"]').innerHTML = `<h4>핵심 시사점</h4><ul>
    <li>절대 성능 <strong>${best.name}</strong>(${best.hot_total_s}s), 가성비 <strong>${bestVal.name}</strong>(speed/$ ${bestVal.value}).</li>
    <li>Graviton4가 세대·아키텍처 전반에서 우위. AMD(5세대)가 최하위권.</li>
    <li>RAM 클수록 유리: 8GB ${r8?.toFixed(1)}s → 32GB ${r32?.toFixed(1)}s. hot 비교는 16/32GB(fits=✓)에서 가장 공정.</li>
  </ul>`;

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}

function avg(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0; }
function avgBy(arr, pred) { const v = arr.filter(pred).map((r) => r.hot_total_s); return v.length ? avg(v) : null; }
function pct(a, b) { return b && a ? ((b - a) / b) * 100 : 0; }
