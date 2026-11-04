// 레퍼런스 탭 — 이후 탭 모듈은 이 파일의 구조(성능표 슬롯 채우기 → bespoke 차트 → destroy 수집)를
// 그대로 따라 만들 것. 표준 컴포넌트로 안 되는 부분만 이 파일 안에서 직접 Chart.js로 그린다(가는
// family trend 라인차트, 사유는 tabs/sysbench.html 참고).
import {
  buildToc, summaryCards, topNBar, metricTabChart, priceSection, resultTable, fmt,
} from '../shared.js';
import { standardReport, scenario } from '../report.js';

export async function render(root, { rows, envelope }) {
  const handles = [];
  handles.push(standardReport(root.querySelector('[data-slot="report"]'), rows, envelope.analysis.cpu_mt, { unit: 'events/s', scenarios: [scenario(envelope.analysis.cpu_st, 'CPU 단일 스레드, 8세대 C', 'c8g.xlarge', 'c8i.xlarge'), scenario(envelope.analysis.cpu_st, 'CPU 단일 스레드, 7세대 C', 'c7g.xlarge', 'c7i.xlarge'), scenario(envelope.analysis.mem_seq_read, '메모리 순차 읽기, 8세대 C (변동 큼)', 'c8g.xlarge', 'c8i.xlarge')] }));
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

  // ---- 고유 섹션: 4 vCPU 스케일링 (멀티 ÷ 단일) — 값은 parsers/sysbench.py smt_scaling ----
  const sc = envelope.smt_scaling;
  const g = (k) => sc[k];
  const label = { graviton: 'Graviton', intel: 'Intel', amd: 'AMD' };
  const bes = root.querySelector('[data-slot="bespoke"]');
  bes.innerHTML = `<p>멀티스레드(4 threads) 점수를 단일 스레드 점수로 나누면 vCPU 4개가 코어 하나의 몇 배를 내는지 알 수 있습니다. `
    + `Graviton은 vCPU 하나가 물리 코어 하나라서 ${fmt(g('graviton-8').median, 2)}배(4에 근접)이고, Intel 6~8세대는 ${fmt(g('intel-6').median, 2)}~${fmt(Math.max(g('intel-7').median, g('intel-8').median), 2)}배, AMD 5세대는 ${fmt(g('amd-5').median, 2)}배입니다. `
    + `xlarge Intel/AMD의 vCPU 4개는 물리 코어 2개를 하이퍼스레딩으로 나눈 것이고, sysbench cpu(소수 계산)는 실행 유닛을 이미 채우는 부하라 두 번째 스레드가 거의 보탬이 되지 않습니다. `
    + `예외는 5세대 Intel(${fmt(g('intel-5').median, 2)}배)로, 하이퍼스레딩으로 약 ${Math.round((g('intel-5').median / 2 - 1) * 100)}%를 더 얻었습니다. `
    + `<strong>그래서 멀티스레드 격차(Graviton이 같은 세대 Intel의 약 1.8배)는 코어 성능 차이가 아니라 물리 코어 수 차이에서 나옵니다.</strong> 단일 스레드는 Intel이 조금 빠릅니다(리포트 종합 판정 참고).</p>`
    + `<div class="table-scroll"><table class="report-table"><thead><tr><th>아키텍처</th><th>세대</th><th>인스턴스 수</th><th>멀티 ÷ 단일 (중앙값)</th><th>범위</th></tr></thead><tbody>${
      Object.entries(sc).map(([k, v]) => { const [a, gen] = k.split('-'); return `<tr><td>${label[a]}</td><td>${gen}세대</td><td>${v.n}</td><td><strong>${fmt(v.median, 2)}배</strong></td><td>${fmt(v.min, 2)} ~ ${fmt(v.max, 2)}</td></tr>`; }).join('')
    }</tbody></table></div><p class="caption">CPU 멀티스레드 ÷ 단일 스레드 (회차 중앙값 기준)</p>`;

  handles.push(buildToc(root));

  return {
    destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); },
  };
}
