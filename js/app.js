// Hash 라우터. HTML과 모듈은 캐시하고 방문할 때마다 DOM과 차트를 다시 마운트한다.
// 한 번에 한 탭만 마운트되므로 탭 간 id 충돌이 없다 — 새 탭 추가 시 TABS 배열에
// 1줄만 추가하면 된다(reports/report-nav.js의 REPORTS 배열과 같은 패턴).
import { loadData } from './shared.js';

const TABS = [
  { id: 'overview', name: '종합' },
  { id: 'sysbench', name: 'Sysbench' },
  { id: 'geekbench', name: 'Geekbench' },
  { id: 'passmark', name: 'PassMark' },
  { id: 'stress-ng', name: 'stress-ng' },
  { id: 'iperf3', name: 'iperf3' },
  { id: 'redis', name: 'Redis' },
  { id: 'valkey', name: 'Valkey' },
  { id: 'nginx', name: 'Nginx' },
  { id: 'springboot', name: 'SpringBoot' },
  { id: 'web', name: '웹 프레임워크' },
  { id: 'elasticsearch', name: 'Elasticsearch' },
  { id: 'clickhouse', name: 'ClickHouse' },
  { id: 'kafka', name: 'Kafka' },
];

const partialCache = new Map(); // tabId -> html string
const moduleCache = new Map(); // tabId -> {render}
const mountedHandles = new Map(); // tabId -> handle from render() (destroy on leave)
let currentTabId = null;
let navigationVersion = 0;

function renderNav() {
  const nav = document.createElement('nav');
  nav.className = 'navbar';
  nav.setAttribute('aria-label', '벤치마크 탐색');
  nav.innerHTML = `
    <div class="navbar-container">
      <button class="navbar-brand" data-tab="overview"><span class="brand-mark" aria-hidden="true">▥</span> EC2<span class="brand-subtitle">BENCHMARK EXPLORER</span></button>
      <div class="navbar-links">${TABS.map((t) => `<button data-tab="${t.id}">${t.name}</button>`).join('')}</div>
    </div>
  `;
  nav.querySelectorAll('[data-tab]').forEach((btn) => {
    btn.addEventListener('click', () => { location.hash = `#${btn.dataset.tab}`; });
  });
  document.body.insertBefore(nav, document.body.firstChild);
  return nav;
}

function setActiveNav(tabId) {
  document.querySelectorAll('.navbar-links button').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
    if (btn.dataset.tab === tabId) btn.setAttribute('aria-current', 'page');
    else btn.removeAttribute('aria-current');
  });
}

async function getPartial(tabId) {
  if (!partialCache.has(tabId)) {
    const html = await fetch(`tabs/${tabId}.html`).then((r) => {
      if (!r.ok) throw new Error(`tabs/${tabId}.html 로드 실패 (${r.status})`);
      return r.text();
    });
    partialCache.set(tabId, html);
  }
  return partialCache.get(tabId);
}

async function getModule(tabId) {
  if (!moduleCache.has(tabId)) {
    const mod = await import(`./tabs/${tabId}.js`);
    moduleCache.set(tabId, mod);
  }
  return moduleCache.get(tabId);
}

async function activateTab(tabId) {
  if (!TABS.some((t) => t.id === tabId)) tabId = 'overview';
  if (tabId === currentTabId) return;
  const version = ++navigationVersion;

  const main = document.getElementById('app-main');
  main.setAttribute('aria-busy', 'true');
  const prevHandle = mountedHandles.get(currentTabId);
  if (prevHandle && prevHandle.destroy) {
    try { prevHandle.destroy(); } catch (e) { console.error(`tab ${currentTabId} destroy 실패`, e); }
  }
  mountedHandles.delete(currentTabId);

  main.innerHTML = '<div class="container"><div class="loading-state" role="status"><span class="loading-bar"></span>벤치마크 데이터를 불러오는 중...</div></div>';
  setActiveNav(tabId);
  currentTabId = tabId;

  try {
    const [html, mod, data] = await Promise.all([getPartial(tabId), getModule(tabId), loadDataFor(tabId)]);
    if (version !== navigationVersion) return;
    const root = document.createElement('div');
    root.className = 'container';
    root.innerHTML = html;
    main.replaceChildren(root);
    const handle = await mod.render(root, data);
    if (version !== navigationVersion) {
      handle?.destroy?.();
      return;
    }
    root.querySelectorAll('canvas').forEach((canvas) => {
      canvas.setAttribute('role', 'img');
      if (!canvas.hasAttribute('aria-label')) canvas.setAttribute('aria-label', canvas.closest('section')?.querySelector('h2')?.textContent || '벤치마크 비교 차트');
    });
    root.querySelectorAll('table').forEach((table) => {
      if (table.parentElement.classList.contains('table-scroll')) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'table-scroll';
      wrapper.tabIndex = 0;
      wrapper.setAttribute('role', 'region');
      wrapper.setAttribute('aria-label', '벤치마크 결과 표, 가로 스크롤 가능');
      table.before(wrapper);
      wrapper.append(table);
    });
    mountedHandles.set(tabId, handle || { destroy() {} });
  } catch (err) {
    if (version !== navigationVersion) return;
    console.error(`탭 ${tabId} 렌더 실패`, err);
    currentTabId = null;
    main.innerHTML = '<div class="container"><div class="loading-state" role="alert"><p>벤치마크를 불러오지 못했습니다. 연결을 확인하고 다시 시도해 주세요.</p><button class="tab-btn">다시 시도</button></div></div>';
    main.querySelector('button').addEventListener('click', () => activateTab(tabId));
  } finally {
    if (version === navigationVersion) main.setAttribute('aria-busy', 'false');
  }
}

async function loadDataFor(tabId) {
  if (tabId === 'overview') return null; // overview.js가 자체적으로 11개 fetch
  return loadData(tabId);
}

function boot() {
  if (window.Chart) {
    Chart.defaults.font.family = "system-ui, -apple-system, 'Segoe UI', sans-serif";
    Chart.defaults.color = '#64748b';
    Chart.defaults.borderColor = '#e9eef3';
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 8;
    Chart.defaults.plugins.tooltip.backgroundColor = '#142d3a';
    Chart.defaults.plugins.tooltip.padding = 12;
    Chart.defaults.elements.bar.borderRadius = 4;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) Chart.defaults.animation = false;
  }
  renderNav();
  document.body.insertAdjacentHTML('beforeend', '<main id="app-main" tabindex="-1"></main><footer>EC2 Benchmark Explorer · EKS EC2 Benchmark Suite</footer>');
  document.querySelector('.skip-link').addEventListener('click', (event) => {
    event.preventDefault();
    document.getElementById('app-main').focus();
  });
  window.addEventListener('hashchange', () => activateTab(location.hash.slice(1)));
  activateTab(location.hash.slice(1) || 'overview');
}

boot();
