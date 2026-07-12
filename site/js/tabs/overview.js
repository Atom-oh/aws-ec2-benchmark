import {
  buildToc, fmt, get, loadData, summaryCards,
} from '../shared.js';

const BENCHMARKS = [
  'sysbench',
  'iperf3',
  'nginx',
  'redis',
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
      label: '로드된 벤치마크',
      value: `${loadedCount}/${BENCHMARKS.length}`,
      detail: 'headline 계약 기준으로 로드',
    },
    {
      label: '인스턴스 수',
      value: fmt(totalInstances),
      detail: 'canonical instances.json 기준',
    },
    {
      label: '평균 커버리지',
      value: averageCoverage == null ? '—' : fmt(averageCoverage, 1),
      detail: '벤치마크당 평균 인스턴스 수',
    },
  ]));

  handles.push(buildToc(root));

  return {
    data: overviewData,
    destroy() {
      delete root.__overviewData;
      handles.forEach((handle) => handle && handle.destroy && handle.destroy());
    },
  };
}
