// passmark = 표준 골격 + 4-way 상세테스트를 metricTabChart로(레거시의 전용 탭 UI를 표준 컴포넌트로 흡수).
import { buildToc, summaryCards, topNBar, metricTabChart, priceSection, resultTable, fmt } from '../shared.js';

export async function render(root, { rows }) {
  const handles = [];
  const topCpu = [...rows].filter((r) => r.cpu_mark != null).sort((a, b) => b.cpu_mark - a.cpu_mark)[0];
  const topSingle = [...rows].filter((r) => r.single != null).sort((a, b) => b.single - a.single)[0];
  const topEff = rows.filter((r) => r.cpu_mark != null && r.price).map((r) => ({ ...r, __eff: r.cpu_mark / r.price }))
    .sort((a, b) => b.__eff - a.__eff)[0];

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 CPU Mark', value: topCpu.name, detail: `${fmt(topCpu.cpu_mark)} score` },
    { label: '최고 싱글스레드', value: topSingle.name, detail: `${fmt(topSingle.single)} score` },
    { label: '최고 가성비', value: topEff.name, detail: `${fmt(topEff.__eff)} score per $/hr` },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="top20"]'), rows, {
    metrics: [
      { field: 'cpu_mark', label: 'CPU Mark', unit: 'score', direction: 'max', icon: '🖥️' },
      { field: 'single', label: '싱글스레드', unit: 'score', direction: 'max', icon: '⚡' },
    ],
    n: 20,
  }));

  handles.push(metricTabChart(root.querySelector('[data-slot="detail"]'), rows, [
    { field: 'int', label: 'Integer', unit: 'M ops/s', direction: 'max', icon: '🔢' },
    { field: 'float', label: 'Floating Point', unit: 'M ops/s', direction: 'max', icon: '📊' },
    { field: 'encryption', label: 'Encryption', unit: 'GB/s', direction: 'max', icon: '🔐' },
    { field: 'compression', label: 'Compression', unit: 'MB/s', direction: 'max', icon: '📦' },
  ]));

  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), rows, [
    { field: 'cpu_mark', label: 'CPU Mark', unit: 'score', direction: 'max', icon: '🖥️' },
    { field: 'single', label: '싱글스레드', unit: 'score', direction: 'max', icon: '⚡' },
  ]));

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'cpu_mark', label: 'CPU Mark', unit: 'score', direction: 'max' },
    gridMetrics: [
      { field: 'cpu_mark', label: 'CPU Mark', unit: 'score', direction: 'max' },
      { field: 'single', label: '싱글스레드', unit: 'score', direction: 'max' },
    ],
  }));

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'cpu_mark', label: 'CPU Mark', fmt: fmt },
    { field: 'single', label: '싱글스레드', fmt: fmt },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ]));

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
