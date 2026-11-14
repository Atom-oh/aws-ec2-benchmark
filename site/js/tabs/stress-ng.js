// stress-ng = 표준 골격 + 7-way 메트릭을 metricTabChart로(레거시의 <select> 드롭다운 +
// 4개 탭 그룹을 하나의 탭 버튼군으로 통일 — 유일한 예외 UI 제거, 콘텐츠 명세 §3 결정).
import { buildToc, summaryCards, topNBar, metricTabChart, genImprovement, priceSection, resultTable, fmt } from '../shared.js';
import { standardReport, scenario } from '../report.js';

const METRICS = [
  { field: 'matrix', label: 'Matrix', unit: 'bogo ops/s', direction: 'max', icon: '🔲' },
  { field: 'float', label: 'Float', unit: 'bogo ops/s', direction: 'max', icon: '📊' },
  { field: 'int', label: 'Integer', unit: 'bogo ops/s', direction: 'max', icon: '🔢' },
  { field: 'memcpy', label: 'Memcpy', unit: 'bogo ops/s', direction: 'max', icon: '📋' },
  { field: 'cache', label: 'Cache', unit: 'bogo ops/s', direction: 'max', icon: '💾' },
  { field: 'ctx_switch', label: 'Context Switch', unit: 'bogo ops/s', direction: 'max', icon: '🔀' },
  { field: 'branch', label: 'Branch', unit: 'bogo ops/s', direction: 'max', icon: '🌿' },
];

export async function render(root, { rows, envelope }) {
  const handles = [];
  handles.push(standardReport(root.querySelector('[data-slot="report"]'), rows, envelope.analysis.geomean, { unit: 'bogo ops/s', leadHtml: '<p class="caption">종합 지수 = 스트레서 7종(matrix, cpu float, cpu int, memcpy, cache, switch, branch)의 bogo ops/s(실제 시간 기준)를 회차마다 기하평균한 값입니다. 부록의 이전 <code>total</code> 점수와는 산식이 다릅니다.</p>' }));
  const gm = (r) => r.r?.geomean?.value ?? null;   // 종합 지수(7종 기하평균) — 전 인스턴스
  const topTotal = [...rows].filter((r) => gm(r) != null).sort((a, b) => gm(b) - gm(a))[0];
  const topEff = rows.filter((r) => gm(r) != null && r.price).map((r) => ({ ...r, __eff: gm(r) / r.price }))
    .sort((a, b) => b.__eff - a.__eff)[0];

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 종합 지수', value: topTotal.name, detail: `${fmt(gm(topTotal))} bogo ops/s (7종 기하평균)` },
    { label: '최고 가성비', value: topEff.name, detail: `${fmt(topEff.__eff)} bogo ops/s per $/hr` },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="top20"]'), rows, { metrics: METRICS, n: 20 }));
  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), rows, METRICS));
  handles.push(genImprovement(root.querySelector('[data-slot="improvement"]'), rows, { field: 'r.geomean.value' }));

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'r.geomean.value', label: '종합 지수(7종 기하평균)', unit: 'bogo ops/s', direction: 'max' },
    gridMetrics: [
      { field: 'matrix', label: 'Matrix', unit: 'bogo ops/s', direction: 'max' },
      { field: 'memcpy', label: 'Memcpy', unit: 'bogo ops/s', direction: 'max' },
    ],
  }));

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'matrix', label: 'Matrix', fmt: fmt },
    { field: 'float', label: 'Float', fmt: fmt },
    { field: 'int', label: 'Int', fmt: fmt },
    { field: 'memcpy', label: 'Memcpy', fmt: fmt },
    { field: 'ctx_switch', label: 'Switch(K)', fmt: fmt },
    { field: 'r.geomean.value', label: '종합 지수', fmt: fmt },
    { field: 'total', label: '이전 종합(산식 미상)', fmt: fmt },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ]));

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
