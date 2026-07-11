// nginx = 표준 골격 100%, bespoke 슬롯 없음 — "슬롯이 비어도 된다"는 설계 증명 사례.
import {
  buildToc, summaryCards, topNBar, metricTabChart, familyChart, genImprovement, priceSection, resultTable, fmt,
} from '../shared.js';

export async function render(root, { rows }) {
  const handles = [];
  const topReq = [...rows].filter((r) => r.req_sec != null).sort((a, b) => b.req_sec - a.req_sec)[0];
  const topLat = [...rows].filter((r) => r.latency_ms != null).sort((a, b) => a.latency_ms - b.latency_ms)[0];
  const topEff = rows.filter((r) => r.req_sec != null && r.price).map((r) => ({ ...r, __eff: r.req_sec / r.price }))
    .sort((a, b) => b.__eff - a.__eff)[0];

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 처리량', value: topReq.name, detail: `${fmt(topReq.req_sec)} req/s` },
    { label: '최저 지연', value: topLat.name, detail: `${fmt(topLat.latency_ms, 2)} ms` },
    { label: '최고 가성비', value: topEff.name, detail: `${fmt(topEff.__eff)} req/s per $/hr` },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="top20"]'), rows, {
    metrics: [
      { field: 'req_sec', label: 'Requests/sec', unit: 'req/s', direction: 'max', icon: '⚡' },
      { field: 'latency_ms', label: 'Latency', unit: 'ms', direction: 'min', icon: '⏱️' },
    ],
    n: 20,
  }));

  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), rows, [
    { field: 'req_sec', label: 'Requests/sec', unit: 'req/s', direction: 'max', icon: '⚡' },
    { field: 'latency_ms', label: 'Latency', unit: 'ms', direction: 'min', icon: '⏱️' },
  ]));

  handles.push(familyChart(root.querySelector('[data-slot="family"]'), rows, { field: 'req_sec', unit: 'req/s' }));
  handles.push(genImprovement(root.querySelector('[data-slot="improvement"]'), rows, { field: 'req_sec' }));

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'req_sec', label: 'Requests/sec', unit: 'req/s', direction: 'max' },
    gridMetrics: [
      { field: 'req_sec', label: 'Requests/sec', unit: 'req/s', direction: 'max' },
      { field: 'latency_ms', label: 'Latency', unit: 'ms', direction: 'min' },
    ],
  }));

  handles.push(topNBar(root.querySelector('[data-slot="avoid"]'), rows, {
    metrics: [{ field: 'req_sec', label: 'Requests/sec', unit: 'req/s', direction: 'max' }],
    n: 10,
    ascending: true,
  }));

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'req_sec', label: 'Req/sec', fmt: fmt },
    { field: 'latency_ms', label: 'Latency (ms)', fmt: (v) => fmt(v, 2) },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ]));

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
