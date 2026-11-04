import {
  badge, buildToc, fmt, get, loadData, perDollar, priceSection, summaryCards, topNBar,
} from '../shared.js';
import { ratioBars, x as xTimes } from '../report.js';

const BENCHMARKS = [
  'sysbench',
  'iperf3',
  'nginx',
  'redis',
  'valkey',
  'elasticsearch',
  'geekbench',
  'passmark',
  'stress-ng',
  'springboot',
  'kafka',
  'clickhouse',
  'web',
];

const BENCHMARK_LABELS = {
  sysbench: 'Sysbench',
  iperf3: 'iperf3',
  nginx: 'Nginx',
  redis: 'Redis',
  valkey: 'Valkey',
  elasticsearch: 'Elasticsearch',
  geekbench: 'Geekbench',
  passmark: 'PassMark',
  'stress-ng': 'stress-ng',
  springboot: '웹 · Spring Boot',
  kafka: 'Kafka',
  clickhouse: 'ClickHouse',
  web: '웹 프레임워크',
};

function normalize(value, best, direction) {
  if (value == null || best == null || best === 0) return null;
  const score = direction === 'min' ? (best / value) * 100 : (value / best) * 100;
  return Number.isFinite(score) ? score : null;
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function bestHeadlineValue(rows, headline) {
  const values = rows
    .map((row) => numberOrNull(get(row, headline.field)))
    .filter((value) => value != null);
  if (!values.length) return null;
  return headline.direction === 'min' ? Math.min(...values) : Math.max(...values);
}

function buildOverviewData(results) {
  const canonicalInstanceNames = [...new Set(results.flatMap(({ instances }) => Object.keys(instances || {})))];
  const instanceNames = [...new Set(results.flatMap(({ instances, rows }) => [
    ...Object.keys(instances || {}),
    ...rows.map((row) => row.name),
  ]))];
  const instanceScores = Object.fromEntries(
    instanceNames.map((instanceName) => [
      instanceName,
      Object.fromEntries(BENCHMARKS.map((benchmarkId) => [benchmarkId, null])),
    ]),
  );

  const benchmarks = results.map(({ envelope, rows }, index) => {
    const id = BENCHMARKS[index];
    const headline = envelope.headline;
    const best = bestHeadlineValue(rows, headline);
    const scoredRows = rows.filter((row) => {
      const value = numberOrNull(get(row, headline.field));
      const score = normalize(value, best, headline.direction);
      if (instanceScores[row.name]) instanceScores[row.name][id] = score;
      return score != null;
    });

    return {
      id,
      label: BENCHMARK_LABELS[id] || id,
      headline,
      best,
      coverage: envelope.coverage,
      rowCount: rows.length,
      scoredCount: scoredRows.length,
    };
  });

  return {
    benchmarks,
    canonicalInstanceNames,
    instanceNames,
    instanceScores,
  };
}

function average(values) {
  const numbers = values.filter((value) => typeof value === 'number' && Number.isFinite(value));
  if (!numbers.length) return null;
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function colorFor(score) {
  const clamped = Math.max(0, Math.min(100, score));
  return `hsl(169, 48%, ${97 - clamped * 0.64}%)`;
}

function scoreRow(instanceName, overviewData, canonicalIndex) {
  const scores = overviewData.instanceScores[instanceName] || {};
  const values = overviewData.benchmarks.map((benchmark) => scores[benchmark.id]);
  const availableCount = values.filter((value) => value != null).length;

  return {
    instanceName,
    canonicalIndex,
    scores,
    compositeScore: average(values),
    availableCount,
  };
}

function bestMetricRow(rows, headline) {
  const scoredRows = rows
    .map((row) => ({ row, value: numberOrNull(get(row, headline.field)) }))
    .filter(({ value }) => value != null)
    .sort((a, b) => (headline.direction === 'min' ? a.value - b.value : b.value - a.value));
  return scoredRows[0] ? scoredRows[0].row : null;
}

function bestEfficiency(rows, headline) {
  const scoredRows = rows
    .map((row) => {
      const value = numberOrNull(get(row, headline.field));
      if (value == null || !(row.price > 0)) return null;
      return {
        row,
        score: headline.direction === 'min' ? value * row.price : perDollar(row, headline.field),
      };
    })
    .filter((entry) => entry && entry.score != null && Number.isFinite(entry.score))
    .sort((a, b) => (headline.direction === 'min' ? a.score - b.score : b.score - a.score));
  return scoredRows[0] ? scoredRows[0].row : null;
}

function metricDetail(row, headline, suffix) {
  if (!row) return suffix;
  const value = numberOrNull(get(row, headline.field));
  const unit = headline.unit ? ` ${escapeHtml(headline.unit)}` : '';
  return `${fmt(value)}${unit} — ${suffix}`;
}

function renderWinners(hostEl, overviewData, results) {
  if (!hostEl) return { destroy() {} };

  const cards = overviewData.benchmarks.map((benchmark, index) => {
    const { rows } = results[index];
    const bestRow = bestMetricRow(rows, benchmark.headline);
    const effRow = bestEfficiency(rows, benchmark.headline);
    const effName = effRow ? escapeHtml(effRow.name) : '—';

    return {
      label: escapeHtml(benchmark.label),
      value: bestRow ? escapeHtml(bestRow.name) : '—',
      detail: metricDetail(bestRow, benchmark.headline, '최고 성능'),
      expandHtml: `<div>가성비 최고: <strong>${effName}</strong></div><div>${metricDetail(effRow, benchmark.headline, '가격 대비 성능')}</div>`,
    };
  });

  return summaryCards(hostEl, cards);
}

function buildInstanceLookup(results) {
  const entries = {};
  results.forEach(({ instances, rows }) => {
    Object.entries(instances || {}).forEach(([name, instance]) => {
      if (!entries[name]) entries[name] = { name, ...instance };
    });
    rows.forEach((row) => {
      if (!entries[row.name]) entries[row.name] = row;
    });
  });
  return entries;
}

function buildCompositeRows(overviewData, results) {
  const instances = buildInstanceLookup(results);
  return overviewData.canonicalInstanceNames.map((instanceName, canonicalIndex) => {
    const row = scoreRow(instanceName, overviewData, canonicalIndex);
    return {
      ...(instances[instanceName] || {}),
      name: instanceName,
      __compositeScore: row.compositeScore,
    };
  });
}

function renderRankingSection(hostEl, overviewData, results) {
  if (!hostEl) return [];

  const compositeRows = buildCompositeRows(overviewData, results);
  const compositeMetric = {
    field: '__compositeScore',
    label: '종합 점수',
    unit: 'score',
    direction: 'max',
  };

  hostEl.innerHTML = '<div class="grid-2"><div><h3>성능 상위 20개</h3><div data-part="rank"></div></div><div><h3>비용과 성능 비교</h3><div data-part="bubble"></div></div></div>';
  if (!compositeRows.some((row) => row.__compositeScore != null)) {
    hostEl.innerHTML = '<p class="empty-state">조건에 맞는 측정값이 없습니다. 필터를 변경해 주세요.</p>';
    return [];
  }

  return [
    topNBar(hostEl.querySelector('[data-part="rank"]'), compositeRows, {
      metrics: [compositeMetric],
      n: 20,
    }),
    priceSection(hostEl.querySelector('[data-part="bubble"]'), compositeRows, {
      mainMetric: compositeMetric,
    }),
  ];
}

function renderHeatmap(hostEl, overviewData, instances) {
  if (!hostEl) return { destroy() {} };

  const totalBenchmarks = overviewData.benchmarks.length;
  const rows = overviewData.canonicalInstanceNames
    .map((instanceName, canonicalIndex) => scoreRow(instanceName, overviewData, canonicalIndex))
    .sort((a, b) => {
      if (a.compositeScore == null && b.compositeScore == null) {
        return a.canonicalIndex - b.canonicalIndex;
      }
      if (a.compositeScore == null) return 1;
      if (b.compositeScore == null) return -1;
      return b.compositeScore - a.compositeScore || a.canonicalIndex - b.canonicalIndex;
    });

  hostEl.innerHTML = `
    <div class="table-scroll heatmap-scroll" tabindex="0" role="region" aria-label="벤치마크 점수 히트맵, 가로 및 세로 스크롤 가능">
      <table class="heatmap-table">
        <caption class="sr-only">벤치마크별 정규화 점수와 측정 범위, 종합 점수 내림차순</caption>
        <thead>
          <tr>
            <th>인스턴스</th>
            ${overviewData.benchmarks.map((benchmark) => `<th scope="col"><a href="#${benchmark.id}">${escapeHtml(BENCHMARK_LABELS[benchmark.id] || benchmark.label)} ↗</a></th>`).join('')}
            <th>종합 점수</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr data-instance="${escapeHtml(row.instanceName.toLowerCase())}">
              <th scope="row">${escapeHtml(row.instanceName)}<span class="instance-arch">${badge(instances[row.instanceName]?.arch)}</span></th>
              ${overviewData.benchmarks.map((benchmark) => {
                const score = row.scores[benchmark.id];
                if (score == null) return '<td class="heatmap-cell heatmap-na">—</td>';
                return `<td class="heatmap-cell" title="${escapeHtml(row.instanceName)} · ${escapeHtml(benchmark.label)}: ${fmt(score, 1)}점" style="background-color: ${colorFor(score)};color:${score >= 97 ? '#fff' : '#000'}">${fmt(score, 0)}</td>`;
              }).join('')}
              ${row.compositeScore == null
                ? `<td class="heatmap-cell heatmap-na">—<br><small>0/${totalBenchmarks}</small></td>`
                : `<td class="heatmap-cell" style="background-color: ${colorFor(row.compositeScore)};color:${row.compositeScore >= 97 ? '#fff' : '#000'}">${fmt(row.compositeScore, 0)}<br><small>${row.availableCount}/${totalBenchmarks}</small></td>`}
            </tr>
          `).join('') || `<tr><td colspan="${totalBenchmarks + 2}" class="empty-state">조건에 맞는 인스턴스가 없습니다. 필터를 변경해 주세요.</td></tr>`}
        </tbody>
      </table>
    </div>
    <div class="table-count">${fmt(rows.length)}개 인스턴스 표시</div>
  `;

  return { destroy() {} };
}

export async function render(root, _data) {
  const handles = [];
  const results = await Promise.all(BENCHMARKS.map((name) => loadData(name)));
  const overviewData = buildOverviewData(results);
  root.__overviewData = overviewData;

  handles.push(verdictMatrix(root, results));

  const loadedCount = results.length;
  const totalInstances = overviewData.canonicalInstanceNames.length;
  const averageCoverage = average(overviewData.benchmarks.map((benchmark) => benchmark.coverage));

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    {
      label: '비교 워크로드',
      value: `${loadedCount}/${BENCHMARKS.length}`,
      detail: 'CPU · 메모리 · 네트워크 · 애플리케이션',
    },
    {
      label: '인스턴스 수',
      value: fmt(totalInstances),
      detail: 'C · M · R 패밀리 / 5–8세대',
    },
    {
      label: '평균 측정 인스턴스',
      value: averageCoverage == null ? '—' : fmt(averageCoverage, 1),
      detail: '벤치마크당 평균 인스턴스 수',
    },
  ]));

  root.querySelector('[data-slot="subtitle"]').textContent = `${loadedCount}개 벤치마크 · ${totalInstances}개 EC2 인스턴스의 성능과 비용 효율을 비교하세요.`;

  handles.push(renderWinners(root.querySelector('[data-slot="winners"]'), overviewData, results));

  const instances = buildInstanceLookup(results);
  const filters = [...root.querySelectorAll('[data-filter]')];
  let comparisonHandles = [];
  function updateComparison() {
    comparisonHandles.forEach((handle) => handle.destroy());
    const values = Object.fromEntries(filters.map((el) => [el.dataset.filter, el.value]));
    const names = overviewData.canonicalInstanceNames.filter((name) => {
      const instance = instances[name];
      return name.toLowerCase().includes(values.search.trim().toLowerCase())
        && (!values.arch || instance.arch === values.arch)
        && (!values.gen || String(instance.gen) === values.gen)
        && (!values.family || instance.family === values.family)
        && (!values.coverage || overviewData.benchmarks.every((benchmark) => overviewData.instanceScores[name][benchmark.id] != null));
    });
    const filtered = { ...overviewData, canonicalInstanceNames: names };
    root.querySelector('[data-slot="filter-count"]').textContent = `${names.length} / ${totalInstances}개 인스턴스 · 전체 데이터 기준 점수`;
    comparisonHandles = [
      renderHeatmap(root.querySelector('[data-slot="heatmap"]'), filtered, instances),
      ...renderRankingSection(root.querySelector('[data-slot="ranking-chart"]'), filtered, results),
    ];
  }
  filters.forEach((el) => el.addEventListener(el.tagName === 'INPUT' ? 'input' : 'change', updateComparison));
  const reset = root.querySelector('[data-action="reset"]');
  const onReset = () => { filters.forEach((el) => { el.value = ''; }); updateComparison(); };
  reset.addEventListener('click', onReset);
  updateComparison();
  handles.push({ destroy() {
    comparisonHandles.forEach((handle) => handle.destroy());
    filters.forEach((el) => el.removeEventListener(el.tagName === 'INPUT' ? 'input' : 'change', updateComparison));
    reset.removeEventListener('click', onReset);
  } });

  handles.push(buildToc(root));

  return {
    data: overviewData,
    destroy() {
      delete root.__overviewData;
      handles.forEach((handle) => handle && handle.destroy && handle.destroy());
    },
  };
}


// 벤치마크별 Graviton ÷ Intel 판정 매트릭스 — envelope.headline.analysis_key가 가리키는 분석 블록만 읽는다
// (벤치마크별 분기 0줄). 짝 정의·판정 규칙은 scripts/dashboard/analysis.py와 동일.
const MATRIX_COLS = [
  ['c9g.xlarge', 'c8i.xlarge', 'Graviton5 / Intel 8세대'],
  ['c8g.xlarge', 'c8i.xlarge', '8세대 (c8g / c8i)'],
  ['c7g.xlarge', 'c7i.xlarge', '7세대 (c7g / c7i)'],
  ['c6g.xlarge', 'c6i.xlarge', '6세대 (c6g / c6i)'],
];
// 판정표 행 = 벤치마크 하나, 단 headline.matrix_rows가 있으면 그 목록대로 여러 행(웹 프레임워크 스택별).
function matrixRows(results) {
  return results.flatMap(({ envelope }) => {
    const h = envelope.headline || {};
    const specs = h.matrix_rows || (h.analysis_key ? [{ key: h.analysis_key, name: BENCHMARK_LABELS[envelope.benchmark] || envelope.benchmark }] : []);
    return specs.map(({ key, name }) => {
      const A = envelope.analysis?.[key];
      if (!A) return null;
      const cells = MATRIX_COLS.map(([l, r]) => A.pairs.find((q) => q.left === l && q.right === r) || null);
      return { name, label: A.metric.label, A, cells, caveat: h.caveat, category: h.category || '기타' };
    }).filter(Boolean);
  });
}

function verdictMatrix(root, results) {
  const rowsData = matrixRows(results);
  const cols = MATRIX_COLS.filter((_, i) => rowsData.some((r) => r.cells[i]));
  const colIdx = cols.map((c) => MATRIX_COLS.indexOf(c));
  const g8 = rowsData.map((r) => r.cells[1]).filter(Boolean);
  const count = (v) => g8.filter((q) => q.verdict === v).length;
  root.querySelector('[data-slot="verdict-lead"]').innerHTML = `<p>8세대(c8g / c8i) 기준으로 ${g8.length}개 워크로드 중 Graviton 우위 ${count('Graviton 우위')}개, 비슷 ${count('비슷')}개, Intel 우위 ${count('Intel 우위')}개${count('재측정 필요') ? `, 판정 보류 ${count('재측정 필요')}개` : ''}입니다. `
    + '웹 프레임워크는 스택마다 한 행씩 나눴습니다. 같은 하드웨어라도 워크로드와 런타임에 따라 판정이 갈리므로, 자신의 워크로드에 가장 가까운 행을 보십시오.</p>';
  const chart = ratioBars(root.querySelector('[data-slot="verdict-chart"]'),
    rowsData.filter((r) => r.cells[1]).map((r) => ({ label: `${r.name} · ${r.label}`, value: r.cells[1].ppd })), { band: 0.05, title: 'c8g / c8i 가격 대비 성능' });
  root.querySelector('[data-slot="verdict-matrix"]').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>워크로드</th><th>기본 지표</th>${cols.map((c) => `<th>${c[2]}</th>`).join('')}</tr></thead><tbody>${
    rowsData.map((r) => `<tr><td><strong>${r.name}</strong>${r.caveat ? ' <sup>※</sup>' : ''}</td><td>${r.label}</td>${colIdx.map((i) => { const q = r.cells[i]; return `<td>${q ? `${xTimes(q.ppd)} <span class="verdict ${verdictCls(q.verdict)}">${q.verdict}</span>` : '—'}</td>`; }).join('')}</tr>`).join('')
  }</tbody></table></div><p class="caption">셀 = 가격 대비 성능 배수(Graviton ÷ Intel)와 판정. '재측정 필요'는 같은 프로세서 이상치나 알려진 측정 이슈가 낀 짝입니다.</p>${
    [...new Map(rowsData.filter((r) => r.caveat).map((r) => [r.caveat, r])).values()].map((r) => `<p class="caption" style="text-align:left">※ <strong>${r.name}</strong>: ${r.caveat}</p>`).join('')}`;
  const ins = insights(root, rowsData);
  return { destroy() { chart.destroy(); ins.destroy(); } };
}

const verdictCls = (v) => (!v ? '' : v === '비슷' ? 'verdict-even' : v === '재측정 필요' ? 'verdict-hold' : v.startsWith('Graviton') ? 'verdict-left' : 'verdict-right');
const shortName = (n) => n.replace('.xlarge', '');

// 종합 분석 — 워크로드 유형별 판정 요약 + 추천 인스턴스. 모든 문장은 판정표 행(analysis 블록)에서 조립한다.
function insights(root, rowsData) {
  const host = root.querySelector('[data-slot="insights"]');
  if (!host) return { destroy() {} };
  const cats = [...new Set(rowsData.map((r) => r.category))];
  const verdictOf = (r) => r.cells[1];
  const mode = (arr) => { const c = new Map(); arr.forEach((v) => c.set(v, (c.get(v) || 0) + 1)); return [...c.entries()].sort((a, b) => b[1] - a[1])[0]; };
  const catRows = cats.map((cat) => {
    const rs = rowsData.filter((r) => r.category === cat);
    const v8 = rs.map(verdictOf).filter(Boolean);
    const odd = (r) => new Set(r.A.peer_outliers.map((o) => o.left));
    const topPpd = mode(rs.map((r) => r.A.rank_ppd.find((n) => !odd(r).has(n))).filter(Boolean));
    const topPerf = mode(rs.map((r) => r.A.rank_perf.find((n) => !odd(r).has(n))).filter(Boolean));
    const g = v8.filter((q) => q.verdict === 'Graviton 우위').length;
    const i = v8.filter((q) => q.verdict === 'Intel 우위').length;
    const e = v8.filter((q) => q.verdict === '비슷').length;
    const n = v8.length;
    const summary = g === n ? 'Graviton 우위' : i === n ? 'Intel 우위' : e === n ? '비슷'
      : g && !i ? 'Graviton 우위 또는 비슷' : i && !g ? 'Intel 우위 또는 비슷' : '워크로드에 따라 갈림';
    return { cat, rs, g, i, e, summary, topPpd, topPerf };
  });
  const detail = (r) => { const q = verdictOf(r); return q ? `${r.name.replace(/^웹 · /, '')} ${xTimes(q.ppd)}` : null; };
  const web = catRows.find((c) => c.cat.startsWith('웹 프레임워크'));
  const g5 = rowsData.map((r) => ({ r, q: r.cells[0] })).filter((x) => x.q);
  const items = [];
  if (web) {
    const gw = web.rs.filter((r) => verdictOf(r)?.verdict === 'Graviton 우위').map(detail).filter(Boolean);
    const ev = web.rs.filter((r) => ['비슷', 'Intel 우위'].includes(verdictOf(r)?.verdict)).map(detail).filter(Boolean);
    items.push(`<strong>런타임이 판정을 바꿉니다.</strong> 같은 c8g / c8i라도 웹 프레임워크에서는 ${gw.length ? `${gw.join(', ')}가 Graviton 우위` : ''}${gw.length && ev.length ? '이고, ' : ''}${ev.length ? `${ev.join(', ')}는 비슷하거나 Intel 우위` : ''}입니다. 인스턴스를 고르기 전에 실제 런타임으로 측정해야 하는 이유입니다.${web.rs.some((r) => r.caveat) ? ' Spring Boot는 JVM 플래그에 따라 판정이 뒤집힙니다(※).' : ''}`);
  }
  const cpu = catRows.find((c) => c.cat === 'CPU 연산');
  if (cpu) items.push(`<strong>CPU 연산 벤치마크는 측정 방식에 따라 정반대로 나옵니다.</strong> ${cpu.rs.map(detail).filter(Boolean).join(', ')}. 멀티코어 점수는 Graviton의 물리 코어 4개(Intel/AMD는 2코어 × 하이퍼스레딩)가 크게 작용하고, x86 확장 명령어에 의존하는 항목은 Intel에 유리합니다.`);
  if (g5.length) items.push(`<strong>Graviton5(c9g)</strong>는 측정된 ${g5.length}개 워크로드에서 c8i 대비 가격 대비 성능 ${xTimes(Math.min(...g5.map((x) => x.q.ppd)))}~${xTimes(Math.max(...g5.map((x) => x.q.ppd)))}입니다. 아직 다른 벤치마크에는 c9g 데이터가 없어 범위가 좁습니다.`);
  host.innerHTML = `<ul class="recs">${items.map((t) => `<li>${t}</li>`).join('')}</ul>
    <div class="table-scroll"><table class="report-table"><thead><tr><th>워크로드 유형</th><th>8세대 판정 (c8g / c8i)</th><th>행별 가격 대비 성능</th><th>가격 대비 성능 1위 (최빈)</th><th>성능 1위 (최빈)</th></tr></thead><tbody>${
      catRows.map((c) => `<tr><td><strong>${c.cat}</strong></td><td><span class="verdict ${verdictCls(c.summary.endsWith('또는 비슷') ? c.summary.replace(' 또는 비슷', '') : c.summary === '워크로드에 따라 갈림' ? '비슷' : c.summary)}">${c.summary}</span> <span class="caption">G ${c.g} · 비슷 ${c.e} · I ${c.i}</span></td><td>${c.rs.map(detail).filter(Boolean).join('<br>')}</td><td>${c.topPpd ? `${shortName(c.topPpd[0])}${c.topPpd[1] > 1 ? ` (${c.topPpd[1]}/${c.rs.length})` : ''}` : '—'}</td><td>${c.topPerf ? `${shortName(c.topPerf[0])}${c.topPerf[1] > 1 ? ` (${c.topPerf[1]}/${c.rs.length})` : ''}` : '—'}</td></tr>`).join('')
    }</tbody></table></div><p class="caption">1위 열은 유형에 속한 행(벤치마크·스택)마다 가격 대비 성능/성능 1위 인스턴스를 뽑아 가장 많이 나온 것입니다(같은 프로세서 이상치는 제외). 가격은 서울 리전 On-Demand 기준입니다.</p>`;
  return { destroy() { host.innerHTML = ''; } };
}
