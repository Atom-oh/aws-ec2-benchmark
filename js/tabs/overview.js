import {
  badge, buildToc, fmt, get, loadData, perDollar, priceSection, summaryCards, topNBar,
} from '../shared.js';

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
  springboot: 'SpringBoot',
  kafka: 'Kafka',
  clickhouse: 'ClickHouse',
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
