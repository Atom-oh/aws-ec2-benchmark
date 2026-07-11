// geekbench = 표준 골격, bespoke 슬롯 없음(family-vs-arch 뷰 토글은 정보 가치가 낮아
// metricTabChart의 single/multi 스위처로 대체 — 콘텐츠 명세 §3 "정보 중복" 판단과 동일 기준).
import { buildToc, summaryCards, topNBar, metricTabChart, genImprovement, priceSection, resultTable, fmt } from '../shared.js';

export async function render(root, { rows }) {
  const handles = [];
  const topMulti = [...rows].filter((r) => r.multi != null).sort((a, b) => b.multi - a.multi)[0];
  const topSingle = [...rows].filter((r) => r.single != null).sort((a, b) => b.single - a.single)[0];
  const topEff = rows.filter((r) => r.multi != null && r.price).map((r) => ({ ...r, __eff: r.multi / r.price }))
    .sort((a, b) => b.__eff - a.__eff)[0];

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 멀티코어', value: topMulti.name, detail: `${fmt(topMulti.multi)} score` },
    { label: '최고 싱글코어', value: topSingle.name, detail: `${fmt(topSingle.single)} score` },
    { label: '최고 가성비', value: topEff.name, detail: `${fmt(topEff.__eff)} score per $/hr` },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="top20"]'), rows, {
    metrics: [
      { field: 'multi', label: '멀티코어', unit: 'score', direction: 'max', icon: '🚀' },
      { field: 'single', label: '싱글코어', unit: 'score', direction: 'max', icon: '⚡' },
    ],
    n: 20,
  }));

  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), rows, [
    { field: 'multi', label: '멀티코어', unit: 'score', direction: 'max', icon: '🚀' },
    { field: 'single', label: '싱글코어', unit: 'score', direction: 'max', icon: '⚡' },
  ]));

  handles.push(genImprovement(root.querySelector('[data-slot="improvement"]'), rows, { field: 'multi' }));

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'multi', label: '멀티코어', unit: 'score', direction: 'max' },
    gridMetrics: [
      { field: 'multi', label: '멀티코어', unit: 'score', direction: 'max' },
      { field: 'single', label: '싱글코어', unit: 'score', direction: 'max' },
    ],
  }));

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'single', label: '싱글코어', fmt: fmt },
    { field: 'multi', label: '멀티코어', fmt: fmt },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ]));

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
