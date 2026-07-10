// 레퍼런스 탭 — 이후 탭 모듈은 이 파일의 구조(성능표 슬롯 채우기 → bespoke 차트 → destroy 수집)를
// 그대로 따라 만들 것. 표준 컴포넌트로 안 되는 부분만 이 파일 안에서 직접 Chart.js로 그린다(가는
// family trend 라인차트, 사유는 tabs/sysbench.html 참고).
import {
  buildToc, summaryCards, topNBar, metricTabChart, priceSection, resultTable, fmt,
} from '../shared.js';

export async function render(root, { rows }) {
  const handles = [];
  const bestBy = (field) => [...rows].filter((r) => r[field] != null).sort((a, b) => b[field] - a[field])[0];

  const topMt = bestBy('cpu_mt');
  const topSt = bestBy('cpu_st');
  const topMem = bestBy('mem_large_block');
  const topEff = [...rows].filter((r) => r.cpu_mt != null && r.price).map((r) => ({ ...r, __eff: r.cpu_mt / r.price }))
    .sort((a, b) => b.__eff - a.__eff)[0];

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 CPU 성능 (Multi-thread)', value: topMt.name, detail: `${fmt(topMt.cpu_mt)} events/sec` },
    { label: '최고 CPU 성능 (Single-thread)', value: topSt.name, detail: `${fmt(topSt.cpu_st)} events/sec` },
    { label: '최고 메모리 대역폭', value: topMem.name, detail: `${fmt(topMem.mem_large_block)} MiB/sec` },
    { label: '최고 CPU 가성비', value: topEff.name, detail: `${fmt(topEff.__eff)} events/$/hr` },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="cpu-mt"]'), rows, {
    metrics: [
      { field: 'cpu_mt', label: 'CPU Multi-thread', unit: 'events/sec', direction: 'max', icon: '⚡' },
      { field: 'cpu_st', label: 'CPU Single-thread', unit: 'events/sec', direction: 'max', icon: '🔹' },
    ],
    n: 25,
  }));

  handles.push(topNBar(root.querySelector('[data-slot="mem-metrics"]'), rows, {
    metrics: [
      { field: 'mem_large_block', label: 'Large Block (1M)', unit: 'MiB/sec', direction: 'max', icon: '📦' },
      { field: 'mem_seq_write', label: 'Sequential Write (1K)', unit: 'MiB/sec', direction: 'max', icon: '➡️' },
      { field: 'mem_seq_read', label: 'Sequential Read (1K)', unit: 'MiB/sec', direction: 'max', icon: '⬅️' },
      { field: 'mem_rnd_write', label: 'Random Write (1K)', unit: 'MiB/sec', direction: 'max', icon: '🔀' },
      { field: 'mem_rnd_read', label: 'Random Read (1K)', unit: 'MiB/sec', direction: 'max', icon: '🎲' },
    ],
    n: 25,
  }));

  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), rows, [
    { field: 'cpu_mt', label: 'CPU Multi-thread', unit: 'events/sec', direction: 'max', icon: '💻' },
    { field: 'mem_large_block', label: 'Memory Large Block', unit: 'MiB/s (÷10)', direction: 'max', divisor: 10, icon: '📋' },
  ]));

  // family trend 라인차트: family(C/M/R)별 Intel(실선)/Graviton(점선) 세대 추이 — metricTabChart로 표현 불가능한 유일한 bespoke.
  const genTrendCanvas = root.querySelector('[data-slot="gen-trend"]');
  const families = ['C', 'M', 'R'];
  const gens = [5, 6, 7, 8];
  const byFamGenArch = {};
  families.forEach((f) => { byFamGenArch[f] = { intel: {}, graviton: {} }; gens.forEach((g) => { byFamGenArch[f].intel[g] = []; byFamGenArch[f].graviton[g] = []; }); });
  rows.forEach((r) => {
    if (r.cpu_mt == null || (r.arch !== 'intel' && r.arch !== 'graviton')) return;
    if (byFamGenArch[r.family] && byFamGenArch[r.family][r.arch][r.gen]) byFamGenArch[r.family][r.arch][r.gen].push(r.cpu_mt);
  });
  const avg = (arr) => (arr.length ? Math.round(arr.reduce((a, b) => a + b, 0) / arr.length) : null);
  const famColor = { C: '#3b82f6', M: '#10b981', R: '#f59e0b' };
  const trendDatasets = [];
  families.forEach((f) => {
    trendDatasets.push({
      label: `${f} - Intel`, data: gens.map((g) => avg(byFamGenArch[f].intel[g])),
      borderColor: famColor[f], borderDash: [], tension: 0.2,
    });
    trendDatasets.push({
      label: `${f} - Graviton`, data: gens.map((g) => avg(byFamGenArch[f].graviton[g])),
      borderColor: famColor[f], borderDash: [6, 4], tension: 0.2,
    });
  });
  const trendChart = new Chart(genTrendCanvas, {
    type: 'line',
    data: { labels: gens.map((g) => `${g}세대`), datasets: trendDatasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: { y: { title: { display: true, text: 'CPU Multi-thread (events/sec)' } } },
    },
  });
  handles.push({ destroy() { trendChart.destroy(); } });

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'cpu_mt', label: 'CPU Multi-thread', unit: 'events/sec', direction: 'max' },
    gridMetrics: [
      { field: 'cpu_mt', label: 'CPU', unit: 'events/sec', direction: 'max' },
      { field: 'mem_large_block', label: 'Memory', unit: 'MiB/sec', direction: 'max' },
      { field: 'cpu_st', label: 'CPU Single', unit: 'events/sec', direction: 'max' },
    ],
  }));

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'cpu_mt', label: 'CPU MT', fmt: fmt },
    { field: 'cpu_st', label: 'CPU ST', fmt: fmt },
    { field: 'mem_seq_write', label: 'Seq Write', fmt: fmt },
    { field: 'mem_seq_read', label: 'Seq Read', fmt: fmt },
    { field: 'mem_rnd_write', label: 'Rnd Write', fmt: fmt },
    { field: 'mem_rnd_read', label: 'Rnd Read', fmt: fmt },
    { field: 'mem_large_block', label: 'Large Block', fmt: (v) => `<strong>${fmt(v)}</strong>` },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ]));

  handles.push(buildToc(root));

  return {
    destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); },
  };
}
