import {
  buildToc, summaryCards, topNBar, metricTabChart, priceSection, resultTable, fmt, badge, get, perDollar, archColor,
} from '../shared.js';

export async function render(root, { rows, envelope }) {
  const handles = [];
  const bestBy = (field, direction = 'max') => [...rows]
    .filter((r) => get(r, field) != null)
    .sort((a, b) => (direction === 'min' ? get(a, field) - get(b, field) : get(b, field) - get(a, field)))[0];

  const topRps = bestBy('wrk.rps200');
  const topCold = bestBy('cold_s', 'min');
  const topEff = rows
    .filter((r) => get(r, 'wrk.rps200') != null && r.price)
    .map((r) => ({ ...r, __eff: perDollar(r, 'wrk.rps200') }))
    .sort((a, b) => b.__eff - a.__eff)[0];

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 처리량 (200 conn)', value: topRps.name, detail: `${fmt(get(topRps, 'wrk.rps200'))} req/s` },
    { label: '최저 콜드스타트', value: topCold.name, detail: `${fmt(topCold.cold_s, 2)} s` },
    { label: '최고 가성비', value: topEff.name, detail: `${fmt(topEff.__eff)} req/s per $/hr` },
  ]));

  handles.push(metricTabChart(root.querySelector('[data-slot="load-stages"]'), rows, [
    { field: 'wrk.rps50', label: '50 connections', unit: 'req/s', direction: 'max', icon: '50' },
    { field: 'wrk.rps100', label: '100 connections', unit: 'req/s', direction: 'max', icon: '100' },
    { field: 'wrk.rps200', label: '200 connections', unit: 'req/s', direction: 'max', icon: '200' },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="coldstart"]'), rows, {
    metrics: [{ field: 'cold_s', label: 'Cold start', unit: 's', direction: 'min', icon: '⏱️' }],
    n: 20,
  }));

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'wrk.rps200', label: '200 connections', unit: 'req/s', direction: 'max' },
    gridMetrics: [
      { field: 'wrk.rps200', label: '200 conn 처리량', unit: 'req/s', direction: 'max' },
      { field: 'cold_s', label: '콜드스타트', unit: 's', direction: 'min' },
    ],
  }));

  handles.push(timeseriesSection(root.querySelector('[data-slot="timeseries"]'), envelope?.timeseries, rows));

  handles.push(familyFilterChart(root.querySelector('[data-slot="family-filter"]'), rows));

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => badge(v) },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'wrk.rps50', label: 'RPS 50', fmt: fmt },
    { field: 'wrk.rps100', label: 'RPS 100', fmt: fmt },
    { field: 'wrk.rps200', label: 'RPS 200', fmt: fmt },
    { field: 'wrk.lat50_ms', label: 'Lat 50 (ms)', fmt: (v) => fmt(v, 2) },
    { field: 'wrk.lat99_ms', label: 'Lat 99 (ms)', fmt: (v) => fmt(v, 2) },
    { field: 'cold_s', label: 'Cold start (s)', fmt: (v) => fmt(v, 2) },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ]));

  handles.push(buildToc(root));

  return {
    destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); },
  };
}

function timeseriesSection(hostEl, timeseries, rows) {
  const metrics = [
    { key: 'throughput', label: '처리량', unit: 'req/s', yTitle: 'req/s', digits: 0 },
    { key: 'lat_avg_ms', label: '평균 지연', unit: 'ms', yTitle: 'ms', digits: 2 },
    { key: 'lat_p99_ms', label: 'P99 지연', unit: 'ms', yTitle: 'ms', digits: 2 },
  ];
  hostEl.innerHTML = `
    <p class="description">Run 2, 60개 샘플(10초 간격, 600초)의 시계열 포인트 통계입니다. 5회 반복 평균이 아닙니다.</p>
    <div class="tab-buttons timeseries-tabs">
      ${metrics.map((metric, i) => `<button class="tab-btn${i === 0 ? ' active' : ''}" data-metric="${metric.key}">${metric.label}</button>`).join('')}
    </div>
    <div class="chart-container tall"><canvas></canvas></div>
    <div class="timeseries-stats"></div>
  `;

  const canvas = hostEl.querySelector('canvas');
  const statsEl = hostEl.querySelector('.timeseries-stats');
  const rowByName = new Map(rows.map((r) => [r.name, r]));
  const interval = timeseries?.interval_s || 10;
  const pointCount = timeseries?.points || 60;
  const labels = Array.from({ length: pointCount }, (_, i) => (i + 1) * interval);
  let chart = null;

  function seriesEntries() {
    return Object.entries(timeseries?.series || {});
  }

  function stats(values) {
    const nums = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
    if (!nums.length) return { mean: null, min: null, max: null, cv: null };
    const mean = nums.reduce((sum, v) => sum + v, 0) / nums.length;
    const variance = nums.reduce((sum, v) => sum + (v - mean) ** 2, 0) / nums.length;
    const stdev = Math.sqrt(variance);
    return {
      mean,
      min: Math.min(...nums),
      max: Math.max(...nums),
      cv: mean ? (stdev / mean) * 100 : null,
    };
  }

  function renderStats(metric) {
    const rowsHtml = seriesEntries().map(([instanceName, series]) => {
      const s = stats(series[metric.key] || []);
      return `
        <tr>
          <td><strong>${instanceName}</strong></td>
          <td>${fmt(s.mean, metric.digits)}</td>
          <td>${fmt(s.min, metric.digits)}</td>
          <td>${fmt(s.max, metric.digits)}</td>
          <td>${fmt(s.cv, 1)}</td>
        </tr>
      `;
    }).join('');

    statsEl.innerHTML = `
      <table>
        <thead>
          <tr><th>인스턴스</th><th>평균</th><th>최소</th><th>최대</th><th>CV(%)</th></tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    `;
  }

  function draw(metric) {
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: seriesEntries().map(([instanceName, series]) => {
          const row = rowByName.get(instanceName);
          const color = archColor(row?.arch, 1);
          return {
            label: instanceName,
            data: series[metric.key] || [],
            borderColor: color,
            backgroundColor: archColor(row?.arch, 0.12),
            borderWidth: 2,
            borderDash: instanceName.includes('-flex') ? [] : [5, 5],
            fill: false,
            pointRadius: 0,
            pointHoverRadius: 3,
            tension: 0.25,
          };
        }),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmt(ctx.raw, metric.digits)} ${metric.unit}`,
            },
          },
        },
        scales: {
          x: { title: { display: true, text: 'Elapsed seconds' } },
          y: { beginAtZero: true, title: { display: true, text: metric.yTitle } },
        },
      },
    });
    renderStats(metric);
  }

  draw(metrics[0]);
  const listeners = [];
  hostEl.querySelectorAll('.tab-btn').forEach((btn) => {
    const onClick = () => {
      const metric = metrics.find((m) => m.key === btn.dataset.metric) || metrics[0];
      hostEl.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      draw(metric);
    };
    btn.addEventListener('click', onClick);
    listeners.push([btn, onClick]);
  });

  return { destroy() { if (chart) chart.destroy(); listeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } };
}

function familyFilterChart(hostEl, rows) {
  hostEl.innerHTML = `
    <div class="tab-buttons family-filter-tabs">
      <button class="tab-btn active" data-family="all">전체</button>
      <button class="tab-btn" data-family="C">C</button>
      <button class="tab-btn" data-family="M">M</button>
      <button class="tab-btn" data-family="R">R</button>
    </div>
    <div class="chart-container tall"><canvas></canvas></div>
  `;
  const canvas = hostEl.querySelector('canvas');
  const metrics = [
    { field: 'wrk.rps50', label: '50 conn', alpha: 0.5 },
    { field: 'wrk.rps100', label: '100 conn', alpha: 0.75 },
    { field: 'wrk.rps200', label: '200 conn', alpha: 1 },
  ];
  let chart = null;

  function sortByRps200Desc(items) {
    return [...items].sort((a, b) => {
      const av = get(a, 'wrk.rps200');
      const bv = get(b, 'wrk.rps200');
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return bv - av;
    });
  }

  function filteredRows(family) {
    const candidates = family === 'all'
      ? rows
      : rows.filter((r) => r.family === family);
    const sorted = sortByRps200Desc(candidates);
    return family === 'all' ? sorted.slice(0, 10) : sorted;
  }

  function draw(family) {
    const selected = filteredRows(family);
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: selected.map((r) => r.name),
        datasets: metrics.map((metric) => ({
          label: metric.label,
          data: selected.map((r) => get(r, metric.field)),
          backgroundColor: selected.map((r) => archColor(r.arch, metric.alpha)),
          borderColor: selected.map((r) => archColor(r.arch, 1)),
          borderWidth: 1,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmt(ctx.raw)} req/s`,
            },
          },
        },
        scales: {
          x: { ticks: { autoSkip: false, maxRotation: 90, minRotation: 45 } },
          y: { beginAtZero: true, title: { display: true, text: 'Requests/sec' } },
        },
      },
    });
  }

  draw('all');
  const listeners = [];
  hostEl.querySelectorAll('.tab-btn').forEach((btn) => {
    const onClick = () => {
      hostEl.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      draw(btn.dataset.family);
    };
    btn.addEventListener('click', onClick);
    listeners.push([btn, onClick]);
  });

  return { destroy() { if (chart) chart.destroy(); listeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } };
}
