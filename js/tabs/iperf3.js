// iperf3 = 표준 골격(single/parallel/reverse/udp 스위처). bespoke 콘텐츠는 정적 파셜(추천
// 카드 그리드, env-item 그리드, 메트릭 정의 테이블)뿐 — 계산할 게 없어 tabs/iperf3.html에 그대로.
import {
  buildToc, summaryCards, topNBar, metricTabChart, familyChart, priceSection, resultTable, fmt,
} from '../shared.js';

export async function render(root, { rows }) {
  const handles = [];
  const topParallel = [...rows].filter((r) => r.parallel_gbps != null).sort((a, b) => b.parallel_gbps - a.parallel_gbps)[0];
  const topJitter = [...rows].filter((r) => r.jitter_ms != null).sort((a, b) => a.jitter_ms - b.jitter_ms)[0];
  const topEff = rows.filter((r) => r.parallel_gbps != null && r.price).map((r) => ({ ...r, __eff: r.parallel_gbps / r.price }))
    .sort((a, b) => b.__eff - a.__eff)[0];

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 TCP 병렬 대역폭', value: topParallel.name, detail: `${fmt(topParallel.parallel_gbps, 2)} Gbps` },
    { label: '최저 UDP Jitter', value: topJitter.name, detail: `${fmt(topJitter.jitter_ms, 4)} ms` },
    { label: '최고 가성비', value: topEff.name, detail: `${fmt(topEff.__eff)} Gbps per $/hr` },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="top20"]'), rows, {
    metrics: [
      { field: 'parallel_gbps', label: 'TCP Parallel', unit: 'Gbps', direction: 'max', icon: '📡' },
      { field: 'single_gbps', label: 'TCP Single', unit: 'Gbps', direction: 'max', icon: '🔗' },
      { field: 'reverse_gbps', label: 'TCP Reverse', unit: 'Gbps', direction: 'max', icon: '🔄' },
      { field: 'jitter_ms', label: 'UDP Jitter (낮을수록 좋음)', unit: 'ms', direction: 'min', icon: '📶' },
    ],
    n: 20,
  }));

  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), rows, [
    { field: 'parallel_gbps', label: 'TCP Parallel', unit: 'Gbps', direction: 'max', icon: '📡' },
    { field: 'single_gbps', label: 'TCP Single', unit: 'Gbps', direction: 'max', icon: '🔗' },
  ]));

  handles.push(familyChart(root.querySelector('[data-slot="family"]'), rows, { field: 'parallel_gbps', unit: 'Gbps' }));

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'parallel_gbps', label: 'TCP Parallel', unit: 'Gbps', direction: 'max' },
    gridMetrics: [
      { field: 'single_gbps', label: 'TCP Single', unit: 'Gbps', direction: 'max' },
      { field: 'parallel_gbps', label: 'TCP Parallel', unit: 'Gbps', direction: 'max' },
      { field: 'udp_mbps', label: 'UDP', unit: 'Mbps', direction: 'max' },
    ],
  }));

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'single_gbps', label: 'TCP Single', fmt: (v) => fmt(v, 2) },
    { field: 'parallel_gbps', label: 'TCP Parallel', fmt: (v) => fmt(v, 2) },
    { field: 'reverse_gbps', label: 'TCP Reverse', fmt: (v) => fmt(v, 2) },
    { field: 'udp_mbps', label: 'UDP (Mbps)', fmt: fmt },
    { field: 'jitter_ms', label: 'Jitter (ms)', fmt: (v) => fmt(v, 4) },
    { field: 'loss_pct', label: 'Loss (%)', fmt: (v) => fmt(v, 3) },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ]));

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
