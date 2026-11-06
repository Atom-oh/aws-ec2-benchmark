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
  const LIMIT = { cpu: 'CPU 포화', gc: '메모리 (GC 정지 누적)', oom: '메모리 (OOM)' };
  const SLO = (envelope.slo_ms || 11000) / 1000, HOLD = SLO - 1;
  const meta = Object.fromEntries(rows.map((r) => [r.name, r]));
  const names = Object.keys(T).filter((n) => meta[n]);
  const cap = (n) => T[n]?.capacity || 0;
  const cost = (n) => (cap(n) ? meta[n].price / (cap(n) / 1000) : null);
  const gcAtCap = (n) => T[n]?.stages?.[String(T[n].util_pct)]?.gc_pct ?? null;
  const AT = envelope.analysis?.sbmem_capacity?.table || {}, BASE = envelope.analysis?.sbmem_capacity?.baseline;
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
  const cpuL = byLimit('cpu'), memL = names.filter((n) => ['gc', 'oom'].includes(T[n].limit));
  const pairLine = (g, i) => (T[g] && T[i] ? `${short(g)} ${fmt(cap(g))} vs ${short(i)} ${fmt(cap(i))}` : '');
  slot('lead').innerHTML = [
    `<p><strong>상주 데이터(2GB)·요청당 작업 객체(1MB)·대기(10초)는 모두 같고, 힙만 RAM의 60%입니다.</strong> 처리량이 늘수록 쌓이는 작업 객체만 인스턴스마다 다른 공간을 채웁니다. ${famLine}.</p>`,
    `<p><strong>무엇이 먼저 차는지가 패밀리별로 갈립니다.</strong> `
      + (memL.length ? `메모리가 먼저 차고 CPU가 남은 인스턴스 ${memL.length}개(${famOf(memL)}), ` : '')
      + (cpuL.length ? `메모리는 남았는데 CPU가 먼저 찬 인스턴스 ${cpuL.length}개(${famOf(cpuL)})` : '')
      + `입니다(첫 실패 단계가 OOM이거나 CPU가 ${envelope.cpu_limit_pct || 70}% 미만이면 메모리, 이상이면 CPU). 이론 최대(남은 힙 ÷ 1MB) 대비 버틴 비율은 Graviton 평균 ${fmt(utilG, 0)}%, Intel 평균 ${fmt(utilI, 0)}%. `
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
      + `<td>$${m.price.toFixed(3)}</td><td><strong>${cost(n) ? `$${cost(n).toFixed(3)}` : '—'}</strong></td><td><strong>${AT[n]?.ppd != null ? x(AT[n].ppd) : '—'}</strong></td>`
      + `<td>${gcAtCap(n) != null ? `${fmt(gcAtCap(n), 0)}%` : '—'}</td><td>${LIMIT[a.limit] || '—'}${a.fail_cpu_pct != null ? ` (CPU ${fmt(a.fail_cpu_pct, 0)}%)` : ''}</td><td>${a.capacity_runs.map(fmt).join(' / ')}</td></tr>`;
  }).join('');
  slot('results').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>인스턴스</th><th>아키텍처</th><th>RAM</th><th>힙</th><th>이론 최대</th><th>버틴 커넥션</th><th>힙 활용률</th><th>$/시간</th><th>1,000커넥션당 $/시간</th><th>가격 대비 성능 (${BASE ? short(BASE) : ''} = 1.00배)</th><th>GC 비율 (버틴 단계)</th><th>먼저 찬 자원 (다음 단계에서 실패한 원인)</th><th>회차별</th></tr></thead><tbody>${rowsHtml}</tbody></table></div>`;

  // ---------- 그림 1: 부하 단계별 지표 (선택: 추가 지연 p50/p90/p95/p99, 서버 CPU, GC 정지, 처리량) ----------
  const lat = (k) => (s) => (s && s[k] ? Math.max(s[k] - HOLD * 1000, 5) : null);  // 대기 시간을 뺀 추가 지연(ms)
  const anyStage = (k) => names.some((n) => Object.values(T[n].stages).some((s) => s[k] != null));
  const METRICS = [
    { id: 'p99', label: 'p99 추가 지연', get: lat('p99_ms'), axis: `p99 − 대기 ${HOLD}초 (ms, 로그 축)`, log: true, line: (SLO - HOLD) * 1000, lineLabel: '판정선 +1,000ms' },
    anyStage('p95_ms') && { id: 'p95', label: 'p95 추가 지연', get: lat('p95_ms'), axis: `p95 − 대기 ${HOLD}초 (ms, 로그 축)`, log: true },
    { id: 'p90', label: 'p90 추가 지연', get: lat('p90_ms'), axis: `p90 − 대기 ${HOLD}초 (ms, 로그 축)`, log: true },
    { id: 'p50', label: 'p50 추가 지연', get: lat('p50_ms'), axis: `p50 − 대기 ${HOLD}초 (ms, 로그 축)`, log: true },
    { id: 'cpu', label: '서버 CPU', get: (s) => (s && !s.errors ? s.cpu_pct : null), axis: '서버 프로세스 CPU (%, vCPU 4개 = 100%)', max: 100, line: envelope.cpu_limit_pct || 70, lineLabel: 'CPU 한계 기준' },
    { id: 'gc', label: 'GC 정지 비율', get: (s) => (s && !s.errors ? s.gc_pct : null), axis: '90초 중 GC 정지 시간 (%)', max: 100 },
    { id: 'rps', label: '처리량', get: (s) => (s && !s.errors ? s.rps : null), axis: '요청/초 (= 커넥션 ÷ 대기 10초가 이상적)' },
  ].filter(Boolean);
  const el = slot('curve');
  el.innerHTML = `<div class="subnav" data-metrics>${METRICS.map((m, i) => `<button type="button" class="subnav-link${i ? '' : ' active'}" data-m="${m.id}">${m.label}</button>`).join('')}</div>`
    + '<div class="chart-box" style="height:380px"><canvas></canvas></div>';
  const insts = CURVE.filter((n) => T[n] && meta[n]);
  const okText = (st) => (st.slo_pass === st.runs ? '통과' : st.slo_pass ? `${st.slo_pass}/${st.runs}회 통과` : st.errors ? '실패(OOM)' : '실패');
  const build = (m) => {
    const ds = insts.map((n) => ({
      label: short(n), inst: n, showLine: true, pointRadius: 3, pointHoverRadius: 6,
      data: PCTS.map((p) => T[n].stages[String(p)]).filter((st) => st && !st.errors && m.get(st) != null).map((st) => ({ x: st.conn, y: m.get(st), st })),  // OOM 단계 제외 → 선이 끝나는 곳 = 메모리 한계
      borderColor: archColor(meta[n].arch, 0.9), backgroundColor: archColor(meta[n].arch, 0.9),
      borderDash: meta[n].family === 'C' ? [4, 4] : meta[n].family === 'R' ? [] : [8, 3], tension: 0.15,
    }));
    const xmax = Math.max(...ds.flatMap((d) => d.data.map((q) => q.x)));
    if (m.line != null) ds.push({ label: m.lineLabel, data: [{ x: 0, y: m.line }, { x: xmax, y: m.line }], showLine: true, borderColor: '#94a3b8', borderDash: [2, 4], pointRadius: 0 });
    if (m.id === 'rps') ds.push({ label: '이상적 처리량 (커넥션 ÷ 10초)', data: [{ x: 0, y: 0 }, { x: xmax, y: xmax / HOLD }], showLine: true, borderColor: '#94a3b8', borderDash: [2, 4], pointRadius: 0 });
    return ds;
  };
  let cur = METRICS[0];
  const yScale = (m) => (m.log ? { type: 'logarithmic', min: 5, title: { display: true, text: m.axis } }
    : { type: 'linear', min: 0, ...(m.max ? { max: m.max } : {}), title: { display: true, text: m.axis } });
  const chart = new Chart(el.querySelector('canvas'), {
    type: 'scatter', data: { datasets: build(cur) },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      scales: { y: yScale(cur), x: { min: 0, title: { display: true, text: '동시 커넥션 (= 처리 중 요청 수)' } } },
      // 마우스에서 가장 가까운 점(점 위에 정확히 올리지 않아도 됨)
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            title: (items) => (items[0].raw.st ? `${items[0].dataset.label} · 동시 커넥션 ${fmt(items[0].raw.st.conn)}` : items[0].dataset.label),
            label: (it) => {
              const n = it.dataset.inst;
              if (!n) return `${it.dataset.label}`;
              const st = it.raw.st || {};
              const ex = (k) => (st[k] ? `+${fmt(st[k] - HOLD * 1000)}` : '—');
              return `${fmt(st.rps, 0)}요청/초 · 추가 지연 p50 ${ex('p50_ms')} / p90 ${ex('p90_ms')}${st.p95_ms ? ` / p95 ${ex('p95_ms')}` : ''} / p99 ${ex('p99_ms')}ms · CPU ${fmt(st.cpu_pct, 0)}% · GC ${fmt(st.gc_pct, 0)}% · ${okText(st)}`;
            },
          },
        },
      } },
  });
  const onClick = (e) => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    cur = METRICS.find((m) => m.id === b.dataset.m);
    el.querySelectorAll('[data-m]').forEach((x) => x.classList.toggle('active', x === b));
    chart.data.datasets = build(cur); chart.options.scales.y = yScale(cur); chart.update();
  };
  el.addEventListener('click', onClick);
  handles.push({ destroy() { el.removeEventListener('click', onClick); chart.destroy(); } });

  // ---------- 그림 2·3: 동시 커넥션(절대값) → 처리량·추가 지연, 서버 CPU → 추가 지연 ----------
  const xy = (n, fx, fy) => PCTS.map((p) => T[n].stages[String(p)]).filter((st) => st && !st.errors && fx(st) != null && fy(st) != null)
    .map((st) => ({ x: fx(st), y: fy(st), st }));
  const p99x = (st) => (st.p99_ms ? Math.max(st.p99_ms - HOLD * 1000, 5) : null);
  const scatter = (host, fx, fy, xTitle, yTitle, { ylog = false, xmax, ymin, refY, refLabel } = {}) => {
    if (!host) return;
    host.innerHTML = '<div class="chart-box" style="height:360px"><canvas></canvas></div>';
    const ds = insts.map((n) => ({
      label: short(n), inst: n, showLine: true, tension: 0.15, pointRadius: 3, pointHoverRadius: 6,
      data: xy(n, fx, fy), borderColor: archColor(meta[n].arch, 0.9), backgroundColor: archColor(meta[n].arch, 0.9),
      borderDash: meta[n].family === 'C' ? [4, 4] : meta[n].family === 'R' ? [] : [8, 3],
    }));
    if (refY != null) {
      const xs = ds.flatMap((d) => d.data.map((q) => q.x));
      ds.push({ label: refLabel, data: [{ x: 0, y: refY }, { x: xmax || Math.max(...xs), y: refY }], showLine: true, pointRadius: 0, borderColor: '#94a3b8', borderDash: [2, 4] });
    }
    const ch = new Chart(host.querySelector('canvas'), {
      type: 'scatter', data: { datasets: ds },
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        scales: { x: { min: 0, ...(xmax ? { max: xmax } : {}), title: { display: true, text: xTitle } },
          y: ylog ? { type: 'logarithmic', min: ymin || 5, title: { display: true, text: yTitle } } : { min: 0, title: { display: true, text: yTitle } } },
        interaction: { mode: 'nearest', intersect: false },
        plugins: { legend: { position: 'bottom' },
          tooltip: { callbacks: { label: (it) => {
            const st = it.raw.st; if (!st) return it.dataset.label;
            const ex = (k) => (st[k] ? `+${fmt(st[k] - HOLD * 1000)}` : '—');
            return `${it.dataset.label}: ${fmt(st.conn)}커넥션 · ${fmt(st.rps, 0)}요청/초 · CPU ${fmt(st.cpu_pct, 0)}% · GC ${fmt(st.gc_pct, 0)}% · 추가 지연 p50 ${ex('p50_ms')} / p90 ${ex('p90_ms')} / p99 ${ex('p99_ms')}ms · ${okText(st)}`;
          } } } } },
    });
    handles.push({ destroy() { ch.destroy(); } });
  };
  scatter(slot('cpu-lat'), (st) => st.cpu_pct, p99x, '서버 CPU (%)', `p99 추가 지연 (ms, 로그 축)`, { ylog: true, xmax: 100, refY: (SLO - HOLD) * 1000, refLabel: '판정선 +1,000ms' });
  const pick2 = (a, b) => {
    return [a, b].filter((n) => T[n]).map((n) => { const q = xy(n, (st) => st.cpu_pct, p99x); const last = q[q.length - 1]; return last ? `${short(n)}는 CPU ${fmt(last.x, 0)}%에서 +${fmt(last.y)}ms` : ''; }).filter(Boolean).join(', ');
  };
  {
    const all = names.flatMap((n) => Object.values(T[n].stages).filter((st) => !st.errors && st.cpu_pct != null).map((st) => ({ n, st })));
    const passMax = all.filter((q) => q.st.slo_pass === q.st.runs).reduce((m, q) => (q.st.cpu_pct > (m?.st.cpu_pct ?? -1) ? q : m), null);
    const failMin = all.filter((q) => !q.st.slo_pass).reduce((m, q) => (q.st.cpu_pct < (m?.st.cpu_pct ?? 1e9) ? q : m), null);
    if (slot('scale-lead')) slot('scale-lead').innerHTML = `<p>같은 CPU 사용률에서도 추가 지연은 인스턴스마다 다릅니다. GC를 빨리 끝내는 인스턴스는 같은 CPU에서 지연이 덜 늘어납니다. `
      + (passMax ? `기준을 지킨 단계 중 CPU가 가장 높았던 것은 ${short(passMax.n)} ${fmt(passMax.st.cpu_pct, 0)}%(+${fmt(passMax.st.p99_ms - HOLD * 1000)}ms)` : '')
      + (failMin ? `, 오류 없이 지연만으로 실패한 단계 중 CPU가 가장 낮았던 것은 ${short(failMin.n)} ${fmt(failMin.st.cpu_pct, 0)}%(+${fmt(failMin.st.p99_ms - HOLD * 1000)}ms)입니다. ` : '. ')
      + `마지막으로 오류 없이 측정된 단계 기준으로 ${pick2('r8g.xlarge', 'r8i.xlarge')}, ${pick2('m8g.xlarge', 'm8i.xlarge')}입니다. OOM이 난 단계는 서버 값이 재시작한 서버의 것이라 그리지 않았습니다.</p>`;
  }

  // ---------- 표 2: 인스턴스별 커넥션 단계 상세 ----------
  const det = slot('stages');
  if (det) {
    const opts = byCost.concat(names.filter((n) => !cost(n)));
    det.innerHTML = `<label class="stage-pick">인스턴스 <select data-pick>${opts.map((n) => `<option value="${n}"${n === 'm8i.xlarge' ? ' selected' : ''}>${short(n)}</option>`).join('')}</select></label><div data-stage-table></div>`;
    const draw = (n) => {
      const hasP95 = Object.values(T[n].stages).some((s) => s.p95_ms != null);
      const ex = (v) => (v ? `+${fmt(v - HOLD * 1000)}` : '—');
      const rowsH = PCTS.filter((p) => T[n].stages[String(p)]).map((p) => {
        const st = T[n].stages[String(p)];
        return `<tr><td>${p}%</td><td>${fmt(st.conn)}</td><td>${fmt(st.rps, 0)}</td><td>${ex(st.p50_ms)}</td><td>${ex(st.p90_ms)}</td>${hasP95 ? `<td>${ex(st.p95_ms)}</td>` : ''}<td><strong>${ex(st.p99_ms)}</strong></td>`
          + `<td>${fmt(st.cpu_pct, 0)}%</td><td>${fmt(st.gc_pct, 0)}%</td><td>${st.gc_max_ms != null ? fmt(st.gc_max_ms) : '—'}</td><td>${st.old_after_gc_mb != null ? `${fmt(st.old_after_gc_mb / 1024, 1)}GB` : '—'}</td><td>${okText(st)}</td></tr>`;
      }).join('');
      det.querySelector('[data-stage-table]').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>부하 (이론 최대 대비)</th><th>커넥션</th><th>요청/초</th><th>p50 추가</th><th>p90 추가</th>${hasP95 ? '<th>p95 추가</th>' : ''}<th>p99 추가 (ms)</th><th>서버 CPU</th><th>GC 정지 비율</th><th>최대 GC 정지 (ms)</th><th>GC 후 old 영역</th><th>결과 (5회)</th></tr></thead><tbody>${rowsH}</tbody></table></div>`
        + `<p class="caption">${short(n)} · 힙 ${fmt(T[n].heap_mb / 1024, 1)}GB (상주 ${fmt(T[n].live_mb / 1024, 1)}GB) · 이론 최대 ${fmt(T[n].k)}커넥션. 지연은 대기 ${HOLD}초를 뺀 값(ms), 모든 값은 5회 중앙값. OOM이 난 단계의 CPU·GC는 재시작한 서버의 값이라 참고하지 마세요.</p>`;
    };
    const sel = det.querySelector('[data-pick]');
    const onPick = () => draw(sel.value);
    sel.addEventListener('change', onPick); draw(sel.value);
    handles.push({ destroy() { sel.removeEventListener('change', onPick); } });
  }
  slot('curve-lead').innerHTML = `<p>가로축은 실제 동시 커넥션 수(= 처리 중 요청 수)입니다. 요청마다 ${HOLD}초를 일부러 기다리므로(느린 하위 시스템) 처리량은 이상적으로 커넥션 ÷ ${HOLD}(요청/초)이고, p99는 누구나 ${HOLD}초 + α입니다. 그래서 지연은 ${HOLD}초를 뺀 <strong>추가 지연</strong>(GC 정지·처리 시간)으로 그렸습니다 — 같은 커넥션에서 이 값이 작을수록 GC를 빨리 끝내는 인스턴스입니다. 처리 중 요청이 쌓여 힙이 차면 추가 지연이 급격히 늘고, 살아 있는 데이터가 힙을 넘으면 OOM으로 서버가 재시작합니다(선이 끝나는 곳). C(점선)·M(긴 점선)·R(실선)은 힙 크기가 달라 선이 끝나는 커넥션 수가 다릅니다.</p>`;

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
      leadHtml: '<p class="caption">아래는 "버틴 커넥션"을 다른 탭과 같은 틀로 정리한 것입니다. 이 탭은 범용 인스턴스 <strong>m7i.xlarge = 1.00배</strong>를 기준선으로 씁니다(다른 탭은 c7i.xlarge). 메모리 크기가 비교 변수이므로 C/M/R 간 배수는 메모리 차이를 포함합니다.</p>',
    }));
  }
  handles.push(buildToc(root));
  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}
