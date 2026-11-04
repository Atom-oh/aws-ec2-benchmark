// 웹 프레임워크 하위 탭(#web/<stack>) — 스택 하나의 독립 리포트. 스택 간 비교·종합 인사이트는 종합 탭에 있다.
// 수치는 scripts/dashboard/parsers/web.py(analysis.report)에서만 계산: 블록 키 <stack>, <stack>_compute, <stack>_plaintext.
import { buildToc, fmt, metricTabChart, resultTable, badge } from '../shared.js';
import { standardReport, scenario, x } from '../report.js';

const DESC = {
  fastapi: 'Python ASGI 비동기 프레임워크 — uvicorn 워커 4(uvloop · httptools)',
  django: 'Python WSGI 풀스택 프레임워크 — gunicorn gthread 워커 4 × 스레드 4',
  node: 'Node.js 단일 스레드 이벤트 루프 — node:cluster 워커 4',
  go: 'Go 표준 라이브러리 net/http — 단일 프로세스, GOMAXPROCS = vCPU',
  dotnet: 'ASP.NET Core Minimal API on Kestrel — Server GC, TieredPGO',
};

export async function render(root, { rows, envelope, sub }) {
  const handles = [];
  const slot = (k) => root.querySelector(`[data-slot="${k}"]`);
  const n = envelope.notes;
  const label = { ...n.stacks, ...(n.pending_stacks || {}) };
  const st = sub;
  const pending = !n.stacks[st];
  slot('title').textContent = `${label[st] || st} 벤치마크`;
  slot('subtitle').textContent = DESC[st] || '';
  slot('server').innerHTML = `${DESC[st] || ''}${n.versions?.[st] ? ` · 서버 보고 버전 <code>${n.versions[st]}</code>` : ''}`;
  slot('az-note').innerHTML = n.az;

  handles.push(standardReport(slot('report'), rows, pending ? null : envelope.analysis[st], {
    unit: 'req/s',
    scenarios: [
      scenario(envelope.analysis[`${st}_compute`], `${label[st]} /compute (CPU 위주), 8세대 C`, 'c8g.xlarge', 'c8i.xlarge'),
      scenario(envelope.analysis[`${st}_plaintext`], `${label[st]} /plaintext, 8세대 C`, 'c8g.xlarge', 'c8i.xlarge'),
      scenario(envelope.analysis[`${st}_compute`], `${label[st]} /compute, Graviton5 vs Intel 8세대`, 'c9g.xlarge', 'c8i.xlarge'),
    ],
    leadHtml: endpointGap(envelope, st, label[st]),
  }));

  slot('endpoint-lead').textContent = '엔드포인트마다 요청당 CPU 사용량이 다릅니다. /plaintext와 /json은 프레임워크 요청 처리와 네트워크 스택 비용이 대부분이고, /compute는 애플리케이션 코드의 연산 성능이 대부분입니다.';
  if (!pending) {
    handles.push(metricTabChart(slot('endpoints'), rows, [
      { field: `${st}.json`, label: '/json (128c)', unit: 'req/s', direction: 'max' },
      { field: `${st}.plaintext`, label: '/plaintext (128c)', unit: 'req/s', direction: 'max' },
      { field: `${st}.compute`, label: '/compute (128c)', unit: 'req/s', direction: 'max' },
      { field: `${st}.json512`, label: '/json (512c)', unit: 'req/s', direction: 'max' },
    ]));
    handles.push(resultTable(slot('table'), rows.filter((r) => r[st]), [
      { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
      { field: 'arch', label: '아키텍처', fmt: (v) => badge(v) },
      { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
      { field: `${st}.json`, label: '/json', fmt },
      { field: `${st}.plaintext`, label: '/plaintext', fmt },
      { field: `${st}.compute`, label: '/compute', fmt },
      { field: `${st}.json512`, label: '/json 512c', fmt },
      { field: `${st}.p99_json_ms`, label: 'p99 (ms)', fmt: (v) => fmt(v, 2) },
      { field: `r.${st}.cv`, label: 'CV (%)', fmt: (v) => fmt(v, 1) },
      { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(4)}` },
    ]));
  }
  handles.push(buildToc(root));
  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}

// 가벼운 응답(/json)과 CPU 위주(/compute)의 Graviton/Intel 차이 — 같은 스택 안에서도 판정이 갈리는지 보여 준다.
function endpointGap(env, st, name) {
  const pick = (k, l, r) => env.analysis[k]?.pairs.find((q) => q.left === l && q.right === r);
  const j8 = pick(st, 'c8g.xlarge', 'c8i.xlarge');
  const c8 = pick(`${st}_compute`, 'c8g.xlarge', 'c8i.xlarge');
  const tj = env.analysis[st]?.table;
  const tc = env.analysis[`${st}_compute`]?.table;
  const parts = [];
  if (j8 && c8) {
    parts.push(`${name}에서 c8g / c8i 성능은 <code>/json</code> ${x(j8.perf)}, <code>/compute</code> ${x(c8.perf)}입니다`
      + `${Math.abs(j8.perf - c8.perf) >= 0.1 ? ' — 엔드포인트 성격에 따라 우열이 달라지므로 자신의 요청 구성에 가까운 쪽을 보십시오' : ''}.`);
  }
  if (tj?.['c9g.xlarge'] && tj?.['c8g.xlarge'] && tc?.['c9g.xlarge'] && tc?.['c8g.xlarge']) {
    const rj = tj['c9g.xlarge'].value / tj['c8g.xlarge'].value;
    const rc = tc['c9g.xlarge'].value / tc['c8g.xlarge'].value;
    parts.push(`Graviton5(c9g)는 Graviton4(c8g) 대비 /json ${x(rj)}, /compute ${x(rc)}입니다`
      + `${rj - rc >= 0.15 ? '. 가벼운 엔드포인트는 네트워크 경로 차이(c9g 최대 15 Gbps, c8g 12.5 Gbps)가 크게 섞인 값입니다' : ''}.`);
  }
  return parts.length ? `<p>${parts.join(' ')}</p>` : '';
}
