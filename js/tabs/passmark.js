// passmark = 표준 골격 + 4-way 상세테스트를 metricTabChart로(레거시의 전용 탭 UI를 표준 컴포넌트로 흡수).
import { buildToc, summaryCards, topNBar, metricTabChart, priceSection, resultTable, fmt } from '../shared.js';
import { standardReport, scenario } from '../report.js';

export async function render(root, { rows, envelope }) {
  const handles = [];
  handles.push(standardReport(root.querySelector('[data-slot="report"]'), rows, envelope.analysis.cpu_mark, { unit: '점', scenarios: [scenario(envelope.analysis.single, 'PassMark 단일 스레드, 8세대 C', 'c8g.xlarge', 'c8i.xlarge')], leadHtml: passmarkLead(envelope.subscores) }));
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

// PassMark에서 Intel이 크게 앞서는 이유 — 값은 parsers/passmark.py subscores(회차 중앙값)에서 온다.
function passmarkLead(sub) {
  const g = sub['c8g.xlarge'], i = sub['c8i.xlarge'];
  if (!g || !i) return '';
  const r = (k) => (g[k] && i[k] ? i[k] / g[k] : null);
  const f = (v) => (v == null ? '—' : `${v.toFixed(1)}배`);
  return `<p>PassMark는 다른 CPU 벤치마크와 반대로 Intel이 크게 앞섭니다. 세부 항목을 보면 정수 연산은 c8g와 c8i가 거의 같고`
    + `(${Math.round(g.CPU_INTEGER_MATH).toLocaleString()} vs ${Math.round(i.CPU_INTEGER_MATH).toLocaleString()}), 부동소수점은 오히려 c8g가 높습니다`
    + `(${Math.round(g.CPU_FLOATINGPOINT_MATH).toLocaleString()} vs ${Math.round(i.CPU_FLOATINGPOINT_MATH).toLocaleString()}). `
    + `격차는 압축(c8i가 ${f(r('CPU_COMPRESSION'))}), 암호화(${f(r('CPU_ENCRYPTION'))}), 확장 명령어 항목에서 나옵니다. arm64 빌드는 AVX/AVX-512 항목이 0점으로 기록됩니다(x86 전용 경로).`
    + ' 따라서 PassMark 종합 점수로 아키텍처를 비교하면 벤치마크 바이너리의 최적화 차이가 섞입니다. 아키텍처 간 비교는 다른 탭을 참고하고, 이 탭은 같은 아키텍처 안의 세대 비교에 쓰는 것을 권합니다.</p>';
}
