// Spring Boot 메모리 압박 탭 — 수치는 scripts/dashboard/parsers/springboot_memory.py에서만 계산.
// envelope.tier[instance] = {heap_mb, live_mb, k, capacity, capacity_runs, util_pct, util_runs, stages{pct:{conn, p99_ms, gc_pct,...}}}
import { buildToc, fmt, badge, archColor } from '../shared.js';
import { standardReport, scenario, x, short } from '../report.js';

const CURVE = ['c8g.xlarge', 'c8i.xlarge', 'm6g.xlarge', 'm8g.xlarge', 'm8i.xlarge', 'r6g.xlarge', 'r8g.xlarge', 'r8i.xlarge'];

export async function render(root, { rows, envelope }) {
  const handles = [];
  const slot = (k) => root.querySelector(`[data-slot="${k}"]`);
  const T = envelope.tier || {};
  const PCTS = envelope.pcts || [];
  const LIMIT = { cpu: 'CPU', memory: '메모리' };
  const SLO = (envelope.slo_ms || 11000) / 1000, HOLD = SLO - 1;
  const meta = Object.fromEntries(rows.map((r) => [r.name, r]));
  const names = Object.keys(T).filter((n) => meta[n]);
  const cap = (n) => T[n]?.capacity || 0;
  const cost = (n) => (cap(n) ? meta[n].price / (cap(n) / 1000) : null);
  const gcAtCap = (n) => T[n]?.stages?.[String(T[n].util_pct)]?.gc_pct ?? null;
  const byCost = names.filter((n) => cost(n)).sort((a, b) => cost(a) - cost(b));
  const avg = (v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : null);
  const pick = (n) => (meta[n] && cost(n) ? `${short(n)} ${fmt(cap(n))}커넥션 · 1,000커넥션당 $${cost(n).toFixed(3)}/시간` : '');

  // ---------- 핵심 결론 (데이터에서 조립) ----------
  const fam = (f, arch) => names.filter((n) => meta[n].family === f && (!arch || meta[n].arch === arch));
  const famAvg = (f, arch, fn) => avg(fam(f, arch).map(fn).filter((v) => v != null));
  const famLine = ['C', 'M', 'R'].filter((f) => fam(f).length).map((f) => {
    const n0 = fam(f)[0];
    return `${f} 패밀리(RAM ${meta[n0].mem_mb / 1024} GiB, 힙 ${(T[n0].heap_mb / 1024).toFixed(1)}GB) 평균 ${fmt(famAvg(f, null, cap), 0)}커넥션`;
  }).join(', ');
  const utilG = avg(names.filter((n) => meta[n].arch === 'graviton').map((n) => T[n].util_pct));
  const utilI = avg(names.filter((n) => meta[n].arch === 'intel').map((n) => T[n].util_pct));
  const r6m8 = cost('r6g.xlarge') && cost('m8i.xlarge') ? cost('m8i.xlarge') / cost('r6g.xlarge') : null;
  const byLimit = (l) => names.filter((n) => T[n].limit === l);
  const famOf = (ns) => ['C', 'M', 'R'].map((f) => [f, ns.filter((n) => meta[n].family === f)]).filter(([, v]) => v.length).map(([f, v]) => `${f} ${v.length}개${f === 'R' ? `: ${v.map(short).join(', ')}` : ''}`).join(', ');
  const cpuL = byLimit('cpu'), memL = byLimit('memory');
  const pairLine = (g, i) => (T[g] && T[i] ? `${short(g)} ${fmt(cap(g))} vs ${short(i)} ${fmt(cap(i))}` : '');
  slot('lead').innerHTML = [
    `<p><strong>상주 데이터(2GB)·요청당 작업 객체(1MB)·대기(10초)는 모두 같고, 힙만 RAM의 60%입니다.</strong> 처리량이 늘수록 쌓이는 작업 객체만 인스턴스마다 다른 공간을 채웁니다. ${famLine}.</p>`,
    `<p><strong>무엇이 먼저 차는지가 패밀리별로 갈립니다.</strong> `
      + (memL.length ? `메모리가 먼저 차고 CPU가 남은 인스턴스 ${memL.length}개(${famOf(memL)}), ` : '')
      + (cpuL.length ? `메모리는 남았는데 CPU가 먼저 찬 인스턴스 ${cpuL.length}개(${famOf(cpuL)})` : '')
      + `입니다(첫 실패 단계 서버 CPU ${envelope.cpu_limit_pct || 70}% 기준). 이론 최대(남은 힙 ÷ 1MB) 대비 버틴 비율은 Graviton 평균 ${fmt(utilG, 0)}%, Intel 평균 ${fmt(utilI, 0)}%. `
      + `같은 메모리끼리: ${['m8g.xlarge|m8i.xlarge', 'r8g.xlarge|r8i.xlarge', 'r6g.xlarge|r6i.xlarge'].map((p) => pairLine(...p.split('|'))).filter(Boolean).join(', ')}커넥션.</p>`,
    `<p><strong>1,000커넥션을 버티는 데 드는 시간당 비용</strong>이 가장 낮은 것은 ${byCost.slice(0, 3).map(pick).join(', ')} 순입니다. `
      + (r6m8 ? `질문하신 r6g와 m8i는 ${r6m8 >= 1 ? `r6g가 ${x(r6m8)} 저렴` : `m8i가 ${x(1 / r6m8)} 저렴`}합니다(${pick('r6g.xlarge')} / ${pick('m8i.xlarge')}).` : '') + '</p>',
    '<p class="caption">단계가 이론 최대의 10% 간격이라 같은 단계에서 멈춘 인스턴스는 값이 같게 나옵니다(그 사이 차이는 이 측정의 해상도 밖). CPU 중심 측정(Spring Boot 탭, 최대 처리량)과 달리 이 탭은 요청이 오래 머무는(느린 하위 시스템) 상황입니다. 메모리 크기와 GC 처리 능력이 함께 결과를 정합니다.</p>',
  ].join('');

  // ---------- 표 1 ----------
  slot('results-lead').innerHTML = `<p>버틴 커넥션이 많을수록, 1,000커넥션당 비용이 낮을수록 좋습니다. "힙 활용률"은 이론상 최대 처리 중 요청 수(남은 힙 ÷ 1MB) 중 실제로 기준(p99 ${SLO}초·오류 0)을 지키며 버틴 비율입니다.</p>`;
  const rowsHtml = byCost.concat(names.filter((n) => !cost(n))).map((n) => {
    const m = meta[n], a = T[n];
    return `<tr><td><strong>${short(n)}</strong></td><td>${badge(m.arch)}</td><td>${m.mem_mb / 1024} GiB</td>`
      + `<td>${(a.heap_mb / 1024).toFixed(1)}GB</td><td>${fmt(a.k)}</td><td><strong>${fmt(a.capacity)}</strong></td><td>${a.util_pct}%</td>`
      + `<td>$${m.price.toFixed(3)}</td><td><strong>${cost(n) ? `$${cost(n).toFixed(3)}` : '—'}</strong></td>`
      + `<td>${gcAtCap(n) != null ? `${fmt(gcAtCap(n), 0)}%` : '—'}</td><td>${LIMIT[a.limit] || '—'}${a.fail_cpu_pct != null ? ` (CPU ${fmt(a.fail_cpu_pct, 0)}%)` : ''}</td><td>${a.capacity_runs.map(fmt).join(' / ')}</td></tr>`;
  }).join('');
  slot('results').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>인스턴스</th><th>아키텍처</th><th>RAM</th><th>힙</th><th>이론 최대</th><th>버틴 커넥션</th><th>힙 활용률</th><th>$/시간</th><th>1,000커넥션당 $/시간</th><th>GC 비율 (버틴 단계)</th><th>먼저 찬 자원 (실패 단계)</th><th>회차별</th></tr></thead><tbody>${rowsHtml}</tbody></table></div>`;

  // ---------- 그림 1: 부하(이론 최대 대비 %)별 p99 ----------
  const el = slot('curve');
  el.innerHTML = '<div class="chart-box" style="height:380px"><canvas></canvas></div>';
  const ds = CURVE.filter((n) => T[n] && meta[n]).map((n) => ({
    label: short(n),
    data: PCTS.map((p) => { const s = T[n].stages[String(p)]; return s && s.p99_ms ? s.p99_ms / 1000 : null; }),
    borderColor: archColor(meta[n].arch, 0.9), backgroundColor: archColor(meta[n].arch, 0.9),
    borderDash: meta[n].family === 'C' ? [4, 4] : meta[n].family === 'R' ? [] : [8, 3], spanGaps: false, tension: 0.2,
  }));
  ds.push({ label: `기준 ${SLO}초`, data: PCTS.map(() => SLO), borderColor: '#94a3b8', borderDash: [2, 4], pointRadius: 0 });
  const chart = new Chart(el.querySelector('canvas'), {
    type: 'line', data: { labels: PCTS.map((p) => `${p}%`), datasets: ds },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      scales: { y: { min: HOLD * 0.95, title: { display: true, text: 'p99 (초)' } },
        x: { title: { display: true, text: '동시 커넥션 (이론 최대 처리 중 요청 수 대비 %)' } } },
      plugins: { legend: { position: 'bottom' } } },
  });
  handles.push({ destroy() { chart.destroy(); } });
  slot('curve-lead').innerHTML = `<p>요청마다 ${HOLD}초를 기다리므로 여유가 있을 때 p99는 ${HOLD}초 남짓입니다. 처리 중 요청이 쌓여 힙이 차면 GC가 길어지면서 p99가 급격히 늘고, 살아 있는 데이터가 힙을 넘으면 OOM으로 서버가 재시작합니다(점이 끊김). 가로축을 인스턴스별 이론 최대 대비 %로 맞춰 힙 크기가 다른 C·M·R을 같은 눈금에서 비교합니다. 점선 = C, 긴 점선 = M, 실선 = R.</p>`;

  // ---------- 표준 리포트 ----------
  const A = envelope.analysis?.sbmem_capacity;
  if (A) {
    handles.push(standardReport(slot('report'), rows, A, {
      unit: '커넥션',
      numberPrefix: '2-',
      pairFamily: 'm',
      scenarios: [
        scenario(A, '8세대 M', 'm8g.xlarge', 'm8i.xlarge'),
        scenario(A, '8세대 R', 'r8g.xlarge', 'r8i.xlarge'),
        scenario(A, '6세대 R', 'r6g.xlarge', 'r6i.xlarge'),
        scenario(A, '구세대 R vs 최신 Intel M', 'r6g.xlarge', 'm8i.xlarge'),
      ],
      leadHtml: '<p class="caption">아래는 "버틴 커넥션"을 다른 탭과 같은 틀(기준선 c7i.xlarge = 1.00배)로 정리한 것입니다. 메모리 크기가 비교 변수이므로 C/M/R 간 배수는 메모리 차이를 포함합니다.</p>',
    }));
  }
  handles.push(buildToc(root));
  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
