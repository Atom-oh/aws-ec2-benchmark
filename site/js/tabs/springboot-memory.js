// Spring Boot 메모리 압박 탭 — 수치는 scripts/dashboard/parsers/springboot_memory.py에서만 계산.
// envelope.tiers.{sbmem12,sbmem24}[instance] = {heap_mb, live_mb, fit, capacity, capacity_runs, stages{conn:{p99_ms, gc_total_ms,...}}}
import { buildToc, fmt, badge, archColor } from '../shared.js';
import { standardReport, scenario, x, short } from '../report.js';

const STAGES = [256, 1024, 2048, 3072, 4096, 6144];
const CURVE12 = ['m6g.xlarge', 'm7g.xlarge', 'm8g.xlarge', 'r6g.xlarge', 'r8g.xlarge', 'm8i.xlarge', 'r8i.xlarge', 'c8g.xlarge', 'c8i.xlarge'];

export async function render(root, { rows, envelope }) {
  const handles = [];
  const slot = (k) => root.querySelector(`[data-slot="${k}"]`);
  const T12 = envelope.tiers.sbmem12 || {};
  const T24 = envelope.tiers.sbmem24 || {};
  const meta = Object.fromEntries(rows.map((r) => [r.name, r]));
  const best = (n) => Math.max(T12[n]?.capacity || 0, T24[n]?.capacity || 0);
  const cost = (n) => (best(n) ? meta[n].price / (best(n) / 1000) : null);
  const gcAt = (n, c) => { const s = T12[n]?.stages?.[String(c)]; return s?.gc_total_ms != null ? s.gc_total_ms / 600 : null; };
  const gcPct = (n) => gcAt(n, 3072);                       // 본문 비교용(M·R은 모두 3,072 단계를 정상 수행)
  const gcCap = (n) => (T12[n]?.capacity ? gcAt(n, T12[n].capacity) : null); // 표: 각자 버틴 단계의 GC 비율
  const names = Object.keys(T12).filter((n) => meta[n]);
  const byCost = names.filter((n) => cost(n)).sort((a, b) => cost(a) - cost(b));

  // ---------- 핵심 결론 (데이터에서 조립) ----------
  const grp = (pred) => names.filter((n) => T12[n].fit === 'full' && pred(meta[n]));
  const gFull = grp((m) => m.arch === 'graviton' && m.gen >= 7);
  const iFull = grp((m) => m.arch === 'intel');
  const capSet = (ns) => [...new Set(ns.map((n) => T12[n].capacity))].sort((a, b) => a - b);
  const avgGc = (ns) => { const v = ns.map(gcPct).filter((y) => y != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const pick = (n) => (meta[n] ? `${short(n)} ${fmt(best(n))}커넥션 · 1,000커넥션당 $${cost(n).toFixed(3)}/시간` : '');
  const cmp = (a, b) => (cost(a) && cost(b) ? cost(b) / cost(a) : null);
  const r6m8 = cmp('r6g.xlarge', 'm8i.xlarge');
  slot('lead').innerHTML = [
    `<p><strong>메모리가 꽉 찬 상황에서는 Graviton이 앞섭니다.</strong> 같은 힙 12GB에서 Graviton 7·8세대 M·R(${gFull.map(short).join(', ')})은 `
      + `${capSet(gFull).map(fmt).join('~')}커넥션을 버텼고, Intel M·R(${iFull.length}개, 6~8세대·flex 포함)은 ${capSet(iFull).map(fmt).join('~')}커넥션에서 멈췄습니다. `
      + `3,072커넥션 단계에서 GC 정지가 차지한 시간은 Graviton 7·8세대 평균 ${fmt(avgGc(gFull), 0)}%, Intel 평균 ${fmt(avgGc(iFull), 0)}%였습니다. `
      + 'G1은 vCPU 수만큼 GC 스레드를 쓰는데 Graviton의 vCPU 4개는 물리 코어 4개, Intel·AMD는 물리 코어 2개 × 하이퍼스레딩이라, 같은 GC 작업을 Graviton이 더 빨리 끝내는 것으로 보입니다(스레드별 GC 시간은 측정하지 않아 추정).</p>',
    `<p><strong>1,000커넥션을 버티는 데 드는 시간당 비용</strong>이 가장 낮은 것은 ${byCost.slice(0, 3).map(pick).join(', ')} 순입니다. `
      + (r6m8 ? `질문하신 r6g와 m8i는 r6g가 ${x(r6m8)} 저렴합니다(${pick('r6g.xlarge')} / ${pick('m8i.xlarge')}).` : '') + '</p>',
    (() => {
      const rs = Object.keys(T24).filter((n) => T12[n]);
      if (!rs.length) return '';
      const up = rs.filter((n) => T24[n].capacity > T12[n].capacity), same = rs.filter((n) => T24[n].capacity === T12[n].capacity),
        down = rs.filter((n) => T24[n].capacity < T12[n].capacity);
      const ch = (n) => `${short(n)} ${fmt(T12[n].capacity)}→${fmt(T24[n].capacity)}`;
      return `<p><strong>메모리를 늘린다고 다 더 버티지는 않습니다.</strong> R 패밀리 힙을 12GB에서 24GB로 늘렸을 때 `
        + (up.length ? `더 버틴 것은 ${up.map(ch).join(', ')}` : '더 버틴 인스턴스는 없었고')
        + (same.length ? `, 그대로인 것은 ${same.map(ch).join(', ')}` : '')
        + (down.length ? `, 오히려 줄어든 것은 ${down.map(ch).join(', ')}` : '') + '입니다. '
        + '힙이 커지면 G1이 훑어야 할 살아 있는 데이터도 늘어 GC 작업량이 커지므로, 늘어난 메모리를 쓰려면 그 GC를 처리할 CPU가 함께 필요합니다. 메모리가 넉넉한 구세대(r6g 등)보다 코어와 메모리를 함께 갖춘 최신 Graviton이 유리한 이유입니다.</p>';
    })(),
    '<p class="caption">CPU 중심 측정(Spring Boot 탭, 최대 처리량)에서는 8세대 Intel이 앞섰습니다. 워크로드가 메모리에 묶이면 결론이 바뀐다는 것이 이 탭의 요점입니다.</p>',
  ].join('');

  // ---------- 표 1 ----------
  slot('results-lead').innerHTML = `<p>버틴 커넥션이 많을수록, 1,000커넥션당 비용이 낮을수록 좋습니다. "축소"는 RAM이 부족해 힙을 줄여 GC 압박 상태로 측정한 인스턴스입니다(C 패밀리 등).</p>`;
  const rowsHtml = byCost.concat(names.filter((n) => !cost(n))).map((n) => {
    const m = meta[n], a = T12[n], b = T24[n];
    return `<tr><td><strong>${short(n)}</strong></td><td>${badge(m.arch)}</td><td>${m.mem_mb / 1024} GiB</td>`
      + `<td>${fmt(a.capacity)}${a.fit === 'reduced' ? ` <span class="verdict verdict-hold">축소 · 힙 ${(a.heap_mb / 1024).toFixed(1)}GB</span>` : ''}</td>`
      + `<td>${b ? fmt(b.capacity) : '—'}</td><td>$${m.price.toFixed(3)}</td><td><strong>${cost(n) ? `$${cost(n).toFixed(3)}` : '—'}</strong></td>`
      + `<td>${gcCap(n) != null ? `${fmt(gcCap(n), 0)}%` : '—'}</td><td>${a.capacity_runs.join(' / ')}</td></tr>`;
  }).join('');
  slot('results').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>인스턴스</th><th>아키텍처</th><th>RAM</th><th>버틴 커넥션 (힙 12GB)</th><th>버틴 커넥션 (힙 24GB)</th><th>$/시간</th><th>1,000커넥션당 $/시간</th><th>GC 비율 (버틴 단계)</th><th>회차별 (12GB)</th></tr></thead><tbody>${rowsHtml}</tbody></table></div>`;

  // ---------- 그림 1·2 ----------
  const curve = (el, tier, list) => {
    el.innerHTML = '<div class="chart-box" style="height:360px"><canvas></canvas></div>';
    const ds = list.filter((n) => tier[n]).map((n) => ({
      label: short(n),
      data: STAGES.map((c) => { const s = tier[n].stages[String(c)]; return s && s.p99_ms ? s.p99_ms / 1000 : null; }),
      borderColor: archColor(meta[n].arch, 0.9), backgroundColor: archColor(meta[n].arch, 0.9),
      borderDash: meta[n].family === 'C' ? [4, 4] : [], spanGaps: false, tension: 0.2,
    }));
    ds.push({ label: '기준 2초', data: STAGES.map(() => 2), borderColor: '#94a3b8', borderDash: [2, 4], pointRadius: 0 });
    const chart = new Chart(el.querySelector('canvas'), {
      type: 'line', data: { labels: STAGES.map(fmt), datasets: ds },
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        scales: { y: { type: 'logarithmic', min: 0.8, title: { display: true, text: 'p99 (초, 로그 축)' } }, x: { title: { display: true, text: '동시 커넥션' } } },
        plugins: { legend: { position: 'bottom' } } },
    });
    return { destroy() { chart.destroy(); } };
  };
  slot('curve-lead').innerHTML = '<p>요청마다 1초를 기다리므로 여유가 있을 때 p99는 1초 남짓입니다. 처리 중 요청이 쌓여 힙이 차면 GC가 길어지면서 p99가 급격히 늘고, 더 쌓이면 OOM으로 서버가 재시작합니다. 실선은 M·R, 점선은 C(힙 축소) 패밀리입니다.</p>';
  handles.push(curve(slot('curve12'), T12, CURVE12));
  handles.push(curve(slot('curve24'), T24, Object.keys(T24)));

  // ---------- 표준 리포트 (힙 12GB 기준) ----------
  handles.push(standardReport(slot('report'), rows, envelope.analysis.sbmem12_capacity, {
    unit: '커넥션',
    numberPrefix: '2-',
    pairFamily: 'm',
    scenarios: [
      scenario(envelope.analysis.sbmem12_capacity, '힙 12GB, 8세대 M', 'm8g.xlarge', 'm8i.xlarge'),
      scenario(envelope.analysis.sbmem12_capacity, '힙 12GB, 7세대 M', 'm7g.xlarge', 'm7i.xlarge'),
      scenario(envelope.analysis.sbmem12_capacity, '힙 12GB, 6세대 M', 'm6g.xlarge', 'm6i.xlarge'),
      scenario(envelope.analysis.sbmem24_capacity, '힙 24GB, 8세대 R', 'r8g.xlarge', 'r8i.xlarge'),
      scenario(envelope.analysis.sbmem24_capacity, '힙 24GB, 6세대 R', 'r6g.xlarge', 'r6i.xlarge'),
    ],
    leadHtml: '<p class="caption">아래는 힙 12GB 단계의 "버틴 커넥션"을 다른 탭과 같은 틀(기준선 c7i.xlarge = 1.00배)로 정리한 것입니다. C 패밀리는 힙을 줄인 상태라 C끼리의 짝 비교는 메모리가 충분한 경우의 판정으로 읽으면 안 됩니다.</p>',
  }));
  handles.push(buildToc(root));
  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
