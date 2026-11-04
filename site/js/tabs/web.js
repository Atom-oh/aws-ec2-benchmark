// 웹 프레임워크 탭 — 표준 리포트(종합 지수) + 스택별 Graviton/Intel 판정 매트릭스.
// 수치는 scripts/dashboard/parsers/web.py(analysis.report)에서 온다.
import { buildToc, fmt, metricTabChart, resultTable, badge } from '../shared.js';
import { standardReport, scenario, ratioBars, x, short } from '../report.js';

const ALL = ['fastapi', 'django', 'node', 'go', 'dotnet'];
const COLS = [['c9g.xlarge', 'c8i.xlarge', 'Graviton5 / Intel 8세대'], ['c8g.xlarge', 'c8i.xlarge', '8세대'], ['c7g.xlarge', 'c7i.xlarge', '7세대'], ['c6g.xlarge', 'c6i.xlarge', '6세대']];

export async function render(root, { rows, envelope }) {
  const handles = [];
  const A = envelope.analysis;
  const label = { ...envelope.notes.stacks, ...(envelope.notes.pending_stacks || {}) };
  const STACKS = ALL.filter((st) => envelope.notes.stacks[st]); // 모든 인스턴스 5회 완료된 스택만
  const pending = Object.values(envelope.notes.pending_stacks || {});
  const slot = (n) => root.querySelector(`[data-slot="${n}"]`);
  slot('az-note').innerHTML = `${envelope.notes.az}. 서버 버전: ${Object.entries(envelope.notes.versions || {}).map(([k, v]) => `${label[k]} = <code>${v}</code>`).join(' · ')}`;

  handles.push(standardReport(slot('report'), rows, A.json_geomean, {
    unit: 'req/s',
    scenarios: STACKS.map((st) => A[st] && scenario(A[st], `${label[st]} /json, 8세대 C`, 'c8g.xlarge', 'c8i.xlarge')),
    leadHtml: (pending.length ? `<p class="caption"><strong>측정 진행 중:</strong> ${pending.join(', ')} — 모든 인스턴스 측정이 끝나면 종합 지수에 포함됩니다. 현재 지수는 ${STACKS.length}개 스택 기준입니다.</p>` : '') + uplift(rows, STACKS, label) + '<p class="caption">종합 지수는 회차마다 스택별 /json 처리량을 기하평균한 값입니다. 스택마다 처리량 규모가 10배 이상 달라 산술평균이면 빠른 스택이 점수를 독점하므로 기하평균으로 동등 가중했습니다.</p>',
  }));

  // 스택별 판정 매트릭스
  const cls = (v) => (v === '비슷' ? 'verdict-even' : v === '재측정 필요' ? 'verdict-hold' : v?.startsWith('Graviton') ? 'verdict-left' : 'verdict-right');
  const cols = COLS.filter(([l, r]) => STACKS.some((st) => A[st]?.pairs.find((q) => q.left === l && q.right === r)));
  slot('stack-matrix').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>스택</th>${cols.map((c) => `<th>${c[2]}</th>`).join('')}</tr></thead><tbody>${
    STACKS.filter((st) => A[st]).map((st) => `<tr><td><strong>${label[st]}</strong></td>${cols.map(([l, r]) => {
      const q = A[st].pairs.find((p) => p.left === l && p.right === r);
      return `<td>${q ? `성능 ${x(q.perf)} · 가격 대비 ${x(q.ppd)} <span class="verdict ${cls(q.verdict)}">${q.verdict}</span>` : '—'}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div>`;
  handles.push(ratioBars(slot('stack-chart'), STACKS.filter((st) => A[st]).map((st) => {
    const q = A[st].pairs.find((p) => p.left === 'c8g.xlarge');
    return { label: label[st], value: q ? q.ppd : null };
  }), { band: 0.05, title: 'c8g / c8i 가격 대비 성능' }));

  handles.push(metricTabChart(slot('endpoints'), rows, STACKS.flatMap((st) => [
    { field: `${st}.json`, label: `${label[st]} /json`, unit: 'req/s', direction: 'max' },
  ]).concat(STACKS.map((st) => ({ field: `${st}.compute`, label: `${label[st]} /compute`, unit: 'req/s', direction: 'max' })))));

  handles.push(resultTable(slot('table'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => badge(v) },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    ...STACKS.map((st) => ({ field: `${st}.json`, label: `${label[st]} /json`, fmt })),
    { field: 'json_geomean', label: '종합 지수', fmt },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(4)}` },
  ]));
  handles.push(buildToc(root));
  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}

// Graviton5 vs Graviton4: 가벼운 응답(/json)과 CPU 위주(/compute)의 향상폭 차이 — 가벼운 엔드포인트는
// 요청당 CPU가 작아 커널 네트워크·패킷 처리 비용이 크게 섞인다는 점을 데이터로 보여 준다.
function uplift(rows, stacks, label) {
  const m = Object.fromEntries(rows.map((r) => [r.name, r]));
  const a = m['c9g.xlarge'], b = m['c8g.xlarge'];
  if (!a || !b) return '';
  const r = (st, k) => (a[st]?.[k] && b[st]?.[k] ? a[st][k] / b[st][k] : null);
  const rng = (k) => { const v = stacks.map((st) => r(st, k)).filter((x) => x); return v.length ? `${Math.min(...v).toFixed(2)}~${Math.max(...v).toFixed(2)}배` : '—'; };
  return `<p>Graviton5(c9g)는 Graviton4(c8g) 대비 <code>/json</code> 처리량이 ${rng('json')}이지만, CPU 위주의 <code>/compute</code>는 ${rng('compute')}입니다. `
    + '요청당 연산이 작은 엔드포인트는 커널 네트워크·패킷 처리 비용이 처리량을 좌우하므로, 네트워크 경로 차이(c9g는 최대 15 Gbps, c8g는 12.5 Gbps)가 크게 섞입니다. 연산이 많은 서비스라면 /compute 쪽 향상폭을 기준으로 보십시오.</p>';
}
