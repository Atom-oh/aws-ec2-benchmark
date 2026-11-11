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
  { id: 'web', name: '웹 프레임워크' },
  { id: 'elasticsearch', name: 'Elasticsearch' },
  { id: 'clickhouse', name: 'ClickHouse' },
  { id: 'kafka', name: 'Kafka' },
];

// 웹 프레임워크 하위 탭: #web/<sub>. springboot는 자체 파셜/모듈(파일럿 리포트)을, 나머지는 web 파셜/모듈을
// 스택 파라미터와 함께 쓴다. 상단 내비는 'web' 하나만 활성화된다. 옛 링크 #springboot 는 #web/springboot 로 이동.
const WEB_SUBTABS = [
  { id: 'springboot', name: 'Spring Boot', note: 'Java' },
  { id: 'springboot-memory', name: 'Spring Boot 메모리', note: 'G1GC 압박' },
  { id: 'springboot-traffic48', name: '48시간 트래픽', note: 'Flex 비교' },
  { id: 'fastapi', name: 'FastAPI', note: 'Python ASGI' },
  { id: 'django', name: 'Django', note: 'Python WSGI' },
  { id: 'node', name: 'Node.js', note: 'Fastify' },
  { id: 'go', name: 'Go', note: 'net/http' },
  { id: 'dotnet', name: 'ASP.NET Core', note: '.NET' },
];

// 탭별 문서 제목·설명(검색 결과·공유 미리보기). 없으면 기본값.
const TAB_META = {"overview": ["종합", "55종 인스턴스의 벤치마크별 정규화 점수, Graviton ÷ Intel 판정 매트릭스와 종합 분석"], "sysbench": ["Sysbench", "CPU(멀티·싱글 스레드)와 메모리 대역폭"], "geekbench": ["Geekbench", "Geekbench 6 싱글·멀티 코어 점수"], "passmark": ["PassMark", "PassMark CPU Mark"], "stress-ng": ["stress-ng", "CPU·메모리·캐시 스트레스 7종"], "iperf3": ["iperf3", "네트워크 대역폭·지터"], "redis": ["Redis", "Redis 8.8 SET/GET 처리량·지연 (io-threads 포함)"], "valkey": ["Valkey", "Valkey 9.1 SET/GET 처리량·지연 (io-threads 포함)"], "nginx": ["Nginx", "Nginx 정적 응답 wrk 처리량·지연"], "web/springboot": ["Spring Boot", "Spring Boot(Java 21) 최대 처리량·콜드스타트, JIT 설정 영향"], "web/springboot-memory": ["Spring Boot 메모리 압박", "G1GC 메모리 압박에서 동시 연결·지연·CPU, p90 기준 scale out과 KEDA 시뮬레이션"], "web/springboot-traffic48": ["48시간 트래픽", "48시간 트래픽 변화·90k RPS 피크에서 Flex vs 표준형"], "web/fastapi": ["FastAPI", "FastAPI + uvicorn JSON·연산 처리량"], "web/django": ["Django", "Django + gunicorn 처리량"], "web/node": ["Node.js", "Node.js + Fastify 처리량"], "web/go": ["Go", "Go net/http 처리량"], "web/dotnet": ["ASP.NET Core", "ASP.NET Core(Kestrel) 처리량"], "elasticsearch": ["Elasticsearch", "Elasticsearch Rally 색인 처리량·지연과 기동 시간"], "clickhouse": ["ClickHouse", "ClickHouse ClickBench 43쿼리"], "kafka": ["Kafka", "Kafka produce/consume 처리량·지연, 포화점"]};
const BASE_TITLE = 'EC2 인스턴스 55종 비교 · Graviton vs Intel·AMD';
const HOME_TITLE = 'EC2 인스턴스 벤치마크 — Graviton vs Intel·AMD 55종 성능·가성비 비교';
function setTabMeta(route) {
  const m = TAB_META[route];
  document.title = route === 'overview' || !m ? HOME_TITLE : `${m[0]} 벤치마크 — ${BASE_TITLE}`;
  const d = document.querySelector('meta[name="description"]');
  if (d && m) d.setAttribute('content', `${m[0]}: ${m[1]}. AWS EC2 xlarge 55종(Intel·AMD·Graviton) 같은 조건 측정, 가격 대비 성능 비교.`);
}

/** hash -> {route, tabId(상단 내비), view(파셜/모듈 이름), sub} */
function parseRoute(hash) {
  let [tab, sub] = (hash || 'overview').split('/');
  if (tab === 'springboot') { tab = 'web'; sub = 'springboot'; }
  if (tab === 'web') {
    if (!WEB_SUBTABS.some((t) => t.id === sub)) sub = WEB_SUBTABS[0].id;
    // 전용 파셜/모듈이 있는 하위 탭(springboot 파일럿, springboot-memory)은 자기 뷰를, 나머지 스택은 공용 web 뷰를 쓴다
    const own = ['springboot', 'springboot-memory', 'springboot-traffic48'];
    return { route: `web/${sub}`, tabId: 'web', view: own.includes(sub) ? sub : 'web', sub };
  }
  if (!TABS.some((t) => t.id === tab)) tab = 'overview';
  return { route: tab, tabId: tab, view: tab, sub: null };
}

function subnavHtml(sub) {
  return `<nav class="subnav" aria-label="웹 프레임워크 선택">${WEB_SUBTABS.map((t) => `<a href="#web/${t.id}" class="${t.id === sub ? 'active' : ''}"${t.id === sub ? ' aria-current="page"' : ''}>${t.name}<span>${t.note}</span></a>`).join('')}</nav>`;
}

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

async function activateTab(hash) {
  const { route, tabId: navId, view, sub } = parseRoute(hash);
  if (hash && `#${route}` !== location.hash) history.replaceState(null, '', `#${route}`); // #springboot, #web → 정규 경로
  const tabId = route;
  setTabMeta(route);
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
  setActiveNav(navId);
  currentTabId = tabId;

  try {
    const [html, mod, data] = await Promise.all([getPartial(view), getModule(view), loadDataFor(view)]);
    if (version !== navigationVersion) return;
    const root = document.createElement('div');
    root.className = 'container';
    root.innerHTML = (navId === 'web' ? subnavHtml(sub) : '') + html;
    if (data && sub) data.sub = sub;
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
    main.querySelector('button').addEventListener('click', () => { currentTabId = null; activateTab(tabId); });
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
