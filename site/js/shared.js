// 공유 컴포넌트 — 탭 모듈(js/tabs/<b>.js)이 호출하는 전부. 새 컴포넌트 추가보다
// 기존 컴포넌트에 옵션을 늘리는 쪽을 먼저 고려할 것(design: "이것이 전부 — 추가 금지 원칙").
//
// 계약: 모든 컴포넌트 함수는 (hostEl, rows, opts) 형태를 받고 {destroy()} 핸들을 반환한다.
// hostEl은 빈 컨테이너(tabs/<b>.html이 제공)이며, 함수가 내부 마크업(탭 버튼/차트/테이블)을
// 전부 그 안에 그린다. 탭 전환 시 app.js가 이전 탭이 반환한 모든 핸들의 destroy()를 호출한다.

export const ARCH_COLOR = { graviton: '#10b981', intel: '#3b82f6', amd: '#ef4444' };
export const ARCH_LABEL = { graviton: 'Graviton', intel: 'Intel', amd: 'AMD' };
const GENS = [5, 6, 7, 8];
const ARCHES = ['intel', 'amd', 'graviton'];

export function archColor(arch, alpha = 0.7) {
  const hex = ARCH_COLOR[arch] || ARCH_COLOR.intel;
  const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function badge(arch) {
  const a = (arch || 'intel').toLowerCase();
  return `<span class="badge badge-${a}">${ARCH_LABEL[a] || arch}</span>`;
}

/** dot-path getter: get({rally:{throughput:5}}, 'rally.throughput') -> 5. 중간 경로가 null/undefined면 undefined. */
export function get(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

// digits는 숫자만 허용 — resultTable의 column.fmt(value, row) 계약과 공유하다 보니
// row 객체가 실수로 두 번째 인자로 들어와도(예: columns: [{fmt: fmt}]) 죽지 않게 방어.
export function fmt(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const d = typeof digits === 'number' ? digits : 0;
  return value.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: 0 });
}

/** row(조인된 인스턴스)에서 path 필드를 canonical price로 나눈 가성비. */
export function perDollar(row, path) {
  const v = get(row, path);
  if (v == null || !row.price) return null;
  return v / row.price;
}

// ---------------------------------------------------------------------------
// 데이터 로딩
// ---------------------------------------------------------------------------

let instancesCache = null;

/** data/<name>.json + data/instances.json을 fetch해 조인된 rows[]와 원본 envelope를 반환. */
export async function loadData(name) {
  const [payload, instances] = await Promise.all([
    fetch(`data/${name}.json`).then((r) => r.json()),
    instancesCache || fetch('data/instances.json').then((r) => r.json()),
  ]);
  instancesCache = instances;
  // metrics를 먼저 펴고 instances.json(canonical)을 나중에 덮어쓴다 — kafka/clickhouse의
  // data.json은 자체 arch/gen/family/price를 이미 갖고 있는데(대문자 'Graviton', 문자열 '8' 등)
  // canonical 값이 항상 이겨야 한다(설계 §3.1 "클라이언트 조인 값이 우선").
  const rows = Object.entries(payload.instances).map(([instName, metrics]) => ({
    name: instName,
    ...metrics,
    ...(instances[instName] || {}),
  }));
  return { envelope: payload, rows, instances };
}

// ---------------------------------------------------------------------------
// 목차
// ---------------------------------------------------------------------------

export function buildToc(rootEl) {
  const sections = [...rootEl.querySelectorAll('section[id]')];
  const toc = rootEl.querySelector('.toc');
  if (!toc || !sections.length) return { destroy() {} };
  const ul = document.createElement('ul');
  sections.forEach((sec) => {
    const h2 = sec.querySelector('h2');
    if (!h2) return;
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.textContent = h2.textContent;
    a.addEventListener('click', () => sec.scrollIntoView({ behavior: 'smooth' }));
    li.appendChild(a);
    ul.appendChild(li);
  });
  toc.appendChild(ul);
  return { destroy() { ul.remove(); } };
}

// ---------------------------------------------------------------------------
// 요약 카드
// ---------------------------------------------------------------------------

/** cards: [{label, value, detail?, expandHtml?}] */
export function summaryCards(hostEl, cards) {
  const listeners = [];
  hostEl.innerHTML = cards.map((c, i) => `
    <div class="summary-card">
      <h3>${c.label}</h3>
      <div class="value">${c.value}</div>
      ${c.detail ? `<div class="detail">${c.detail}</div>` : ''}
      ${c.expandHtml ? `<button class="expand-toggle" data-i="${i}">상세 보기 ▾</button><div class="expand-body" data-i="${i}">${c.expandHtml}</div>` : ''}
    </div>
  `).join('');
  hostEl.querySelectorAll('.expand-toggle').forEach((btn) => {
    const onClick = () => {
      const body = hostEl.querySelector(`.expand-body[data-i="${btn.dataset.i}"]`);
      body.classList.toggle('open');
      btn.textContent = body.classList.contains('open') ? '상세 숨기기 ▴' : '상세 보기 ▾';
    };
    btn.addEventListener('click', onClick);
    listeners.push([btn, onClick]);
  });
  return { destroy() { listeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } };
}

// ---------------------------------------------------------------------------
// 내부 헬퍼: metric 탭 버튼
// ---------------------------------------------------------------------------

function metricTabsMarkup(metrics, activeIdx) {
  if (metrics.length <= 1) return '';
  return `<div class="tab-buttons metric-tabs">${metrics.map((m, i) => `
    <button class="metric-tab${i === activeIdx ? ' active' : ''}" data-i="${i}">${m.icon ? `<span class="tab-icon">${m.icon}</span>` : ''}${m.label}</button>
  `).join('')}</div>`;
}

function wireMetricTabs(container, metrics, onSelect) {
  const listeners = [];
  container.querySelectorAll('.metric-tab').forEach((btn) => {
    const onClick = () => {
      container.querySelectorAll('.metric-tab').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      onSelect(metrics[Number(btn.dataset.i)]);
    };
    btn.addEventListener('click', onClick);
    listeners.push([btn, onClick]);
  });
  return listeners;
}

// ---------------------------------------------------------------------------
// Top-N 수평 바 차트 (metrics 2개 이상이면 스위처 자동)
// ---------------------------------------------------------------------------

/** opts: {metrics: [{field,label,unit,direction,fmt?,icon?}], n=20, ascending=false(worst-N)} */
export function topNBar(hostEl, rows, opts) {
  const { metrics, n = 20, ascending = false } = opts;
  hostEl.innerHTML = `
    ${metricTabsMarkup(metrics, 0)}
    <div class="chart-container tall"><canvas></canvas></div>
  `;
  const canvas = hostEl.querySelector('canvas');
  let chart = null;

  function render(metric) {
    const dir = metric.direction === 'min' ? 1 : -1;
    const sortDir = ascending ? -dir : dir;
    const top = rows
      .filter((r) => get(r, metric.field) != null)
      .sort((a, b) => sortDir * (get(a, metric.field) - get(b, metric.field)))
      .slice(0, n);
    const cfg = {
      type: 'bar',
      data: {
        labels: top.map((r) => r.name),
        datasets: [{
          data: top.map((r) => get(r, metric.field)),
          backgroundColor: top.map((r) => archColor(r.arch)),
          borderColor: top.map((r) => archColor(r.arch, 1)),
          borderWidth: 1,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        indexAxis: 'y',
        scales: { x: { title: { display: true, text: metric.unit || '' } } },
      },
    };
    if (chart) chart.destroy();
    chart = new Chart(canvas, cfg);
  }

  render(metrics[0]);
  const listeners = wireMetricTabs(hostEl, metrics, render);
  return { destroy() { if (chart) chart.destroy(); listeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } };
}

// ---------------------------------------------------------------------------
// arch × gen 그룹 바 차트 (메트릭 스위처 + gen축 null 마스킹 내장)
// ---------------------------------------------------------------------------

function aggregateByGenArch(rows, field) {
  const out = {};
  GENS.forEach((g) => { out[g] = { intel: [], amd: [], graviton: [] }; });
  rows.forEach((r) => {
    const v = get(r, field);
    if (v != null && out[r.gen] && out[r.gen][r.arch]) out[r.gen][r.arch].push(v);
  });
  return out;
}
const avg = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);

/** metrics: [{field,label,unit,direction,divisor=1,icon?,insightHtml?}] */
export function metricTabChart(hostEl, rows, metrics) {
  hostEl.innerHTML = `
    ${metricTabsMarkup(metrics, 0)}
    <div class="chart-container"><canvas></canvas></div>
    <div class="metric-insight"></div>
  `;
  const canvas = hostEl.querySelector('canvas');
  const insightEl = hostEl.querySelector('.metric-insight');
  let chart = null;

  function render(metric) {
    const data = aggregateByGenArch(rows, metric.field);
    const divisor = metric.divisor || 1;
    const datasets = ARCHES.map((arch) => ({
      label: ARCH_LABEL[arch],
      data: GENS.map((g) => {
        if (arch === 'amd' && g !== 5) return null;
        if (arch === 'graviton' && g === 5) return null;
        const a = avg(data[g][arch]);
        return a == null ? null : Math.round(a / divisor);
      }),
      backgroundColor: ARCH_COLOR[arch],
      borderColor: ARCH_COLOR[arch],
      borderWidth: 1,
    }));
    const cfg = {
      type: 'bar',
      data: { labels: GENS.map((g) => `${g}세대`), datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            callbacks: {
              label: (ctx) => (ctx.raw == null ? null : `${ctx.dataset.label}: ${ctx.raw.toLocaleString()} ${metric.unit || ''}`),
            },
          },
        },
        scales: { y: { beginAtZero: true, title: { display: true, text: `${metric.label} (${metric.unit || ''})` } } },
      },
    };
    if (chart) chart.destroy();
    chart = new Chart(canvas, cfg);
    insightEl.innerHTML = metric.insightHtml || '';
  }

  render(metrics[0]);
  const listeners = wireMetricTabs(hostEl, metrics, render);
  return { destroy() { if (chart) chart.destroy(); listeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } };
}

// ---------------------------------------------------------------------------
// C/M/R 패밀리 비교
// ---------------------------------------------------------------------------

export function familyChart(hostEl, rows, metric) {
  hostEl.innerHTML = `<div class="chart-container"><canvas></canvas></div>`;
  const canvas = hostEl.querySelector('canvas');
  const families = ['C', 'M', 'R'];
  const byFamilyArch = {};
  families.forEach((f) => { byFamilyArch[f] = { intel: [], amd: [], graviton: [] }; });
  rows.forEach((r) => {
    const v = get(r, metric.field);
    if (v != null && byFamilyArch[r.family] && byFamilyArch[r.family][r.arch]) byFamilyArch[r.family][r.arch].push(v);
  });
  const datasets = ARCHES.map((arch) => ({
    label: ARCH_LABEL[arch],
    data: families.map((f) => { const a = avg(byFamilyArch[f][arch]); return a == null ? null : Math.round(a); }),
    backgroundColor: ARCH_COLOR[arch],
  }));
  const chart = new Chart(canvas, {
    type: 'bar',
    data: { labels: families, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: { y: { beginAtZero: true, title: { display: true, text: metric.unit || '' } } },
    },
  });
  return { destroy() { chart.destroy(); } };
}

// ---------------------------------------------------------------------------
// 세대별 개선율
// ---------------------------------------------------------------------------

export function genImprovement(hostEl, rows, metric) {
  hostEl.innerHTML = `<div class="chart-container"><canvas></canvas></div>`;
  const canvas = hostEl.querySelector('canvas');
  const byGenArch = aggregateByGenArch(rows, metric.field);
  const labels = [];
  const values = [];
  ['intel', 'graviton'].forEach((arch) => {
    for (let i = 1; i < GENS.length; i++) {
      const prevGen = GENS[i - 1], curGen = GENS[i];
      if (arch === 'graviton' && prevGen === 5) continue;
      const prev = avg(byGenArch[prevGen][arch]);
      const cur = avg(byGenArch[curGen][arch]);
      if (prev == null || cur == null) continue;
      labels.push(`${ARCH_LABEL[arch]} ${prevGen}→${curGen}세대`);
      values.push(Math.round(((cur - prev) / prev) * 1000) / 10);
    }
  });
  const chart = new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets: [{ data: values, backgroundColor: labels.map((l) => (l.includes('Graviton') ? ARCH_COLOR.graviton : ARCH_COLOR.intel)) }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => `${ctx.raw > 0 ? '+' : ''}${ctx.raw}%` } } },
      scales: { y: { title: { display: true, text: '개선율 (%)' } } },
    },
  });
  return { destroy() { chart.destroy(); } };
}

// ---------------------------------------------------------------------------
// 가격 대비 성능 3-tab 섹션
// ---------------------------------------------------------------------------

/** opts: {mainMetric: {field,label,unit,direction}, gridMetrics: [{field,label,unit,direction}] (grid-3, 최대 3개)} */
export function priceSection(hostEl, rows, opts) {
  const { mainMetric, gridMetrics = [] } = opts;
  const tabs = ['버블 차트', '가성비 순위', '지표별 가성비'].slice(0, gridMetrics.length ? 3 : 2);
  hostEl.innerHTML = `
    <div class="tab-buttons">${tabs.map((t, i) => `<button class="tab-btn${i === 0 ? ' active' : ''}" data-i="${i}">${t}</button>`).join('')}</div>
    <div class="tab-content active" data-i="0"><div class="chart-container"><canvas></canvas></div></div>
    <div class="tab-content" data-i="1"><div class="chart-container"><canvas></canvas></div></div>
    ${gridMetrics.length ? `<div class="tab-content" data-i="2"><div class="grid-3">${gridMetrics.map(() => '<div class="chart-container"><canvas></canvas></div>').join('')}</div></div>` : ''}
  `;
  const charts = [];
  const contents = [...hostEl.querySelectorAll('.tab-content')];

  // 탭 0: 버블 (price vs mainMetric, r = 가성비 스케일)
  const bubbleCanvas = contents[0].querySelector('canvas');
  const priceRows = rows.filter((r) => r.price > 0 && get(r, mainMetric.field) != null);
  charts.push(new Chart(bubbleCanvas, {
    type: 'bubble',
    data: {
      datasets: ARCHES.map((arch) => ({
        label: ARCH_LABEL[arch],
        data: priceRows.filter((r) => r.arch === arch).map((r) => ({
          x: r.price, y: get(r, mainMetric.field), r: Math.max(4, Math.min(30, Math.sqrt(perDollar(r, mainMetric.field) || 1) / 3)), name: r.name,
        })),
        backgroundColor: archColor(arch, 0.6),
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.raw.name}: $${ctx.raw.x}/hr, ${ctx.raw.y.toLocaleString()} ${mainMetric.unit || ''}` } } },
      scales: { x: { title: { display: true, text: '시간당 가격 ($)' } }, y: { title: { display: true, text: mainMetric.unit || '' } } },
    },
  }));

  // 탭 1: 가성비 Top-N
  const effCanvas = contents[1].querySelector('canvas');
  const effRows = priceRows.map((r) => ({ ...r, __eff: perDollar(r, mainMetric.field) }))
    .filter((r) => r.__eff != null).sort((a, b) => (mainMetric.direction === 'min' ? a.__eff - b.__eff : b.__eff - a.__eff)).slice(0, 20);
  charts.push(new Chart(effCanvas, {
    type: 'bar',
    data: { labels: effRows.map((r) => r.name), datasets: [{ data: effRows.map((r) => Math.round(r.__eff)), backgroundColor: effRows.map((r) => archColor(r.arch)) }] },
    options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: `${mainMetric.unit || ''} per $/hr` } } } },
  }));

  // 탭 2: 지표별 가성비 grid-3
  if (gridMetrics.length) {
    const gridCanvases = contents[2].querySelectorAll('canvas');
    gridMetrics.forEach((metric, i) => {
      const gRows = rows.filter((r) => r.price > 0 && get(r, metric.field) != null)
        .map((r) => ({ ...r, __eff: perDollar(r, metric.field) }))
        .sort((a, b) => (metric.direction === 'min' ? a.__eff - b.__eff : b.__eff - a.__eff)).slice(0, 15);
      charts.push(new Chart(gridCanvases[i], {
        type: 'bar',
        data: { labels: gRows.map((r) => r.name.replace('.xlarge', '')), datasets: [{ label: metric.label, data: gRows.map((r) => Math.round(r.__eff)), backgroundColor: gRows.map((r) => archColor(r.arch)) }] },
        options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false }, title: { display: true, text: metric.label + ' 가성비' } } },
      }));
    });
  }

  const listeners = [];
  hostEl.querySelectorAll('.tab-btn').forEach((btn) => {
    const onClick = () => {
      hostEl.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
      contents.forEach((c) => c.classList.remove('active'));
      btn.classList.add('active');
      contents[Number(btn.dataset.i)].classList.add('active');
    };
    btn.addEventListener('click', onClick);
    listeners.push([btn, onClick]);
  });

  return { destroy() { charts.forEach((c) => c.destroy()); listeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } };
}

// ---------------------------------------------------------------------------
// 결과 테이블 (검색 + arch/gen/family 필터 + 정렬)
// ---------------------------------------------------------------------------

/** columns: [{field, label, fmt?(value,row)=>string}] */
/** opts: {onRowClick?(row)} — 지정하면 각 <tr>가 클릭 가능해지고 클릭 시 해당 row로 콜백(redis 모달용). */
export function resultTable(hostEl, rows, columns, opts = {}) {
  hostEl.innerHTML = `
    <div class="table-filters">
      <input type="text" class="f-search" placeholder="인스턴스 검색...">
      <select class="f-arch"><option value="">전체 아키텍처</option><option value="graviton">Graviton</option><option value="intel">Intel</option><option value="amd">AMD</option></select>
      <select class="f-gen"><option value="">전체 세대</option>${GENS.map((g) => `<option value="${g}">${g}세대</option>`).join('')}</select>
      <select class="f-family"><option value="">전체 패밀리</option><option value="C">C</option><option value="M">M</option><option value="R">R</option></select>
    </div>
    <table>
      <thead><tr>${columns.map((c) => `<th data-field="${c.field}">${c.label}</th>`).join('')}</tr></thead>
      <tbody></tbody>
    </table>
    <div class="table-count"></div>
  `;
  const tbody = hostEl.querySelector('tbody');
  const countEl = hostEl.querySelector('.table-count');
  const searchEl = hostEl.querySelector('.f-search');
  const archEl = hostEl.querySelector('.f-arch');
  const genEl = hostEl.querySelector('.f-gen');
  const famEl = hostEl.querySelector('.f-family');

  let sortField = columns[0].field;
  let sortDir = -1;

  function render() {
    let filtered = rows;
    const search = searchEl.value.toLowerCase();
    if (search) filtered = filtered.filter((r) => r.name.toLowerCase().includes(search));
    if (archEl.value) filtered = filtered.filter((r) => r.arch === archEl.value);
    if (genEl.value) filtered = filtered.filter((r) => String(r.gen) === genEl.value);
    if (famEl.value) filtered = filtered.filter((r) => r.family === famEl.value);

    const sorted = [...filtered].sort((a, b) => {
      const av = get(a, sortField), bv = get(b, sortField);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') return sortDir * av.localeCompare(bv);
      return sortDir * (av - bv);
    });

    tbody.innerHTML = sorted.map((r, i) => `<tr${opts.onRowClick ? ` class="clickable-row" data-i="${i}"` : ''}>${columns.map((c) => {
      const v = get(r, c.field);
      return `<td>${c.fmt ? c.fmt(v, r) : (v == null ? '—' : v)}</td>`;
    }).join('')}</tr>`).join('');
    countEl.textContent = `${sorted.length}개 인스턴스 표시`;

    if (opts.onRowClick) {
      tbody.querySelectorAll('tr').forEach((tr, i) => {
        tr.addEventListener('click', () => opts.onRowClick(sorted[i]));
      });
    }

    hostEl.querySelectorAll('th').forEach((th) => {
      th.classList.toggle('sort-active', th.dataset.field === sortField);
      th.classList.toggle('asc', th.dataset.field === sortField && sortDir === 1);
    });
  }

  const listeners = [];
  [searchEl, archEl, genEl, famEl].forEach((el) => {
    const evt = el === searchEl ? 'input' : 'change';
    el.addEventListener(evt, render);
    listeners.push([el, evt, render]);
  });
  hostEl.querySelectorAll('th').forEach((th) => {
    const onClick = () => {
      const field = th.dataset.field;
      sortDir = sortField === field ? -sortDir : -1;
      sortField = field;
      render();
    };
    th.addEventListener('click', onClick);
    listeners.push([th, 'click', onClick]);
  });

  render();
  return { destroy() { listeners.forEach(([el, evt, fn]) => el.removeEventListener(evt, fn)); } };
}
