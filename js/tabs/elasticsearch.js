// ES 고유 SLOT A: 페이지 레벨 탭(Rally/Coldstart/종합) — 표준 metricTabChart와는 다른 층위의
// 스위처라 자체 구현. scatter 차트도 표준 컴포넌트에 없어 bespoke.
// rally 필드는 51개 인스턴스만 값이 있고(c8gn/r8gd는 null) — shared.get()의 dot-path가 null
// 중간 경로를 undefined로 반환해 topNBar/metricTabChart의 null 필터링에 자동으로 걸린다.
import {
  buildToc, summaryCards, topNBar, metricTabChart, priceSection, resultTable, fmt, archColor,
} from '../shared.js';

export async function render(root, { rows }) {
  const handles = [];
  const rallyRows = rows.filter((r) => r.rally != null);

  const topRally = [...rallyRows].sort((a, b) => b.rally.throughput - a.rally.throughput)[0];
  const topCold = [...rows].filter((r) => r.coldstart != null).sort((a, b) => a.coldstart.avg_ms - b.coldstart.avg_ms)[0];
  const gravitonAvg = avgOf(rallyRows.filter((r) => r.arch === 'graviton').map((r) => r.rally.throughput));
  const intelAvg = avgOf(rallyRows.filter((r) => r.arch === 'intel').map((r) => r.rally.throughput));

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 Rally 처리량', value: topRally.name, detail: `${fmt(topRally.rally.throughput)} docs/s` },
    { label: '최저 콜드 스타트', value: topCold.name, detail: `${fmt(topCold.coldstart.avg_ms / 1000, 1)} s` },
    { label: 'Graviton 평균 (Rally)', value: `${fmt(gravitonAvg)} docs/s`, detail: `${rallyRows.filter((r) => r.arch === 'graviton').length}개 인스턴스` },
    { label: 'Intel 평균 (Rally)', value: `${fmt(intelAvg)} docs/s`, detail: `${rallyRows.filter((r) => r.arch === 'intel').length}개 인스턴스` },
  ]));

  // 페이지 탭
  const pageBtns = [...root.querySelectorAll('[data-page]')];
  const pageContents = [...root.querySelectorAll('[data-page-content]')];
  const onPageClick = (btn) => () => {
    pageBtns.forEach((b) => b.classList.remove('active'));
    pageContents.forEach((c) => c.classList.remove('active'));
    btn.classList.add('active');
    root.querySelector(`[data-page-content="${btn.dataset.page}"]`).classList.add('active');
  };
  const pageListeners = pageBtns.map((btn) => { const fn = onPageClick(btn); btn.addEventListener('click', fn); return [btn, fn]; });
  handles.push({ destroy() { pageListeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } });

  // Rally 탭
  handles.push(topNBar(root.querySelector('[data-slot="rally-top20"]'), rallyRows, {
    metrics: [
      { field: 'rally.throughput', label: 'Throughput', unit: 'docs/s', direction: 'max', icon: '⚡' },
      { field: 'rally.lat_p50', label: 'Latency p50', unit: 'ms', direction: 'min', icon: '⏱️' },
      { field: 'rally.lat_p99', label: 'Latency p99', unit: 'ms', direction: 'min', icon: '📊' },
      { field: 'rally.gc_young', label: 'GC 시간', unit: 's', direction: 'min', icon: '🗑️' },
      { field: 'rally.indexing_s', label: '인덱싱 시간', unit: 'min', direction: 'min', icon: '📝' },
      { field: 'rally.merge_s', label: '머지 시간', unit: 'min', direction: 'min', icon: '🔀' },
    ],
    n: 20,
  }));
  handles.push(metricTabChart(root.querySelector('[data-slot="rally-arch-gen"]'), rallyRows, [
    { field: 'rally.throughput', label: 'Throughput', unit: 'docs/s', direction: 'max', icon: '⚡' },
    { field: 'rally.lat_p50', label: 'Latency p50', unit: 'ms', direction: 'min', icon: '⏱️' },
  ]));

  // Coldstart 탭 (54개 전체)
  handles.push(topNBar(root.querySelector('[data-slot="cold-top20"]'), rows, {
    metrics: [
      { field: 'coldstart.avg_ms', label: 'Cold Start', unit: 'ms', direction: 'min', icon: '🚀' },
      { field: 'coldstart.sequential_index_ms', label: 'Sequential Index', unit: 'ms', direction: 'min', icon: '📥' },
      { field: 'coldstart.bulk_index_ms', label: 'Bulk Index', unit: 'ms', direction: 'min', icon: '📦' },
      { field: 'coldstart.search_match_all_ms', label: 'Search match_all', unit: 'ms', direction: 'min', icon: '🔍' },
    ],
    n: 20,
  }));
  handles.push(metricTabChart(root.querySelector('[data-slot="cold-arch-gen"]'), rows, [
    { field: 'coldstart.avg_ms', label: 'Cold Start', unit: 'ms', direction: 'min', icon: '🚀' },
  ]));

  // 종합: scatter (rally throughput vs coldstart)
  const scatterCanvas = root.querySelector('[data-slot="scatter"]');
  const scatterData = rows.filter((r) => r.rally != null && r.coldstart != null);
  const scatterChart = new Chart(scatterCanvas, {
    type: 'scatter',
    data: {
      datasets: ['graviton', 'intel', 'amd'].map((arch) => ({
        label: arch,
        data: scatterData.filter((r) => r.arch === arch).map((r) => ({ x: r.coldstart.avg_ms / 1000, y: r.rally.throughput, name: r.name })),
        backgroundColor: archColor(arch, 0.7),
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.raw.name}: ${ctx.raw.x.toFixed(1)}s, ${ctx.raw.y.toLocaleString()} docs/s` } } },
      scales: { x: { title: { display: true, text: 'Cold Start (s)' } }, y: { title: { display: true, text: 'Rally Throughput (docs/s)' } } },
    },
  });
  handles.push({ destroy() { scatterChart.destroy(); } });

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rallyRows, {
    mainMetric: { field: 'rally.throughput', label: 'Rally Throughput', unit: 'docs/s', direction: 'max' },
    gridMetrics: [
      { field: 'rally.throughput', label: 'Rally', unit: 'docs/s', direction: 'max' },
    ],
  }));

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'rally.throughput', label: 'Rally (docs/s)', fmt: fmt },
    { field: 'rally.lat_p50', label: 'Latency p50', fmt: fmt },
    { field: 'coldstart.avg_ms', label: 'Cold Start (ms)', fmt: fmt },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ]));

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}

function avgOf(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null; }
