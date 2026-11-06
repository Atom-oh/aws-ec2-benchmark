// Spring Boot 메모리 압박 탭 — 수치는 scripts/dashboard/parsers/springboot_memory.py에서만 계산.
// envelope.tier[instance] = {heap_mb, live_mb, k, capacity, capacity_runs, util_pct, util_runs, stages{pct:{conn, p99_ms, gc_pct,...}}}
import { buildToc, fmt, badge, archColor } from '../shared.js';
import { standardReport, scenario, x, short } from '../report.js';


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

  // ---------- 그림 1~4: 처리량·지연 × CPU·커넥션 (패밀리·분위수 선택) ----------
  // 같은 패밀리(C/M/R)는 RAM·힙이 같아 같은 커넥션에서 직접 비교 가능. OOM 단계는 서버가 재시작 중이라 제외.
  const okText = (st) => (st.slo_pass === st.runs ? '통과' : st.slo_pass ? `${st.slo_pass}/${st.runs}회 통과` : st.errors ? '실패(OOM)' : '실패');
  const PCTL = [['p50_ms', 'p50'], ['p75_ms', 'p75'], ['p90_ms', 'p90'], ['p95_ms', 'p95'], ['p99_ms', 'p99']]
    .filter(([k]) => names.some((n) => Object.values(T[n].stages).some((st) => st[k] != null)));
  const famList = ['C', 'M', 'R'].filter((f) => names.some((n) => meta[n].family === f));
  const quad = slot('quad');
  quad.innerHTML = `<div class="ts-controls"><label>패밀리 <select data-q="fam">${famList.map((f) => `<option value="${f}"${f === 'M' ? ' selected' : ''}>${f} (${names.filter((n) => meta[n].family === f).length}개, RAM ${meta[names.find((n) => meta[n].family === f)].mem_mb / 1024} GiB)</option>`).join('')}</select></label>`
    + `<label>지연 분위수 <select data-q="pct">${PCTL.map(([k, l]) => `<option value="${k}"${k === 'p99_ms' ? ' selected' : ''}>${l}</option>`).join('')}</select></label></div>`
    + '<div class="quad-grid">'
    + [['rps-cpu', '그림 1. 처리량 / 서버 CPU'], ['rps-conn', '그림 2. 처리량 / 동시 커넥션'], ['lat-cpu', '그림 3. 지연 / 서버 CPU'], ['lat-conn', '그림 4. 지연 / 동시 커넥션']]
      .map(([k, t]) => `<div><h3 class="quad-title">${t}</h3><div class="chart-box" style="height:300px"><canvas data-c="${k}"></canvas></div></div>`).join('') + '</div>';
  const q = (k) => quad.querySelector(`[data-q="${k}"]`);
  const shade = (n) => (meta[n].gen >= 8 ? 0.95 : meta[n].gen >= 7 ? 0.65 : 0.4);
  const lineStyle = (n) => ({ borderColor: archColor(meta[n].arch, shade(n)), backgroundColor: archColor(meta[n].arch, shade(n)), borderDash: /flex/.test(n) ? [6, 4] : [] });
  const exLat = (st, k) => (st[k] ? Math.max(st[k] - HOLD * 1000, 5) : null);   // 대기 10초를 뺀 추가 지연(ms)
  const AX = {
    'rps-cpu': { x: (st) => st.cpu_pct, y: (st) => st.rps, xt: '서버 CPU (%)', yt: '처리량 (요청/초)', xmax: 100 },
    'rps-conn': { x: (st) => st.conn, y: (st) => st.rps, xt: '동시 커넥션', yt: '처리량 (요청/초)', ideal: true },
    'lat-cpu': { x: (st) => st.cpu_pct, y: (st, k) => exLat(st, k), xt: '서버 CPU (%)', yt: '추가 지연 (ms, 로그 축)', log: true, xmax: 100, slo: true },
    'lat-conn': { x: (st) => st.conn, y: (st, k) => exLat(st, k), xt: '동시 커넥션', yt: '추가 지연 (ms, 로그 축)', log: true, slo: true },
  };
  const quadCharts = {};
  const quadData = (key) => {
    const ax = AX[key], fam = q('fam').value, pk = q('pct').value;
    const list = names.filter((n) => meta[n].family === fam)
      .sort((a, b) => (meta[a].arch === meta[b].arch ? meta[a].gen - meta[b].gen : meta[a].arch < meta[b].arch ? -1 : 1));
    const ds = list.map((n) => ({
      label: short(n), inst: n, showLine: true, tension: 0.15, pointRadius: 3, pointHoverRadius: 6, ...lineStyle(n),
      data: PCTS.map((p) => T[n].stages[String(p)]).filter((st) => st && !st.errors && ax.x(st) != null && ax.y(st, pk) != null)
        .map((st) => ({ x: ax.x(st), y: ax.y(st, pk), st })),
    }));
    const xs = ds.flatMap((d) => d.data.map((v) => v.x)), xm = ax.xmax || Math.max(...xs, 1);
    if (ax.ideal) ds.push({ label: '이상적 (커넥션 ÷ 10초)', data: [{ x: 0, y: 0 }, { x: xm, y: xm / HOLD }], showLine: true, pointRadius: 0, borderColor: '#94a3b8', borderDash: [2, 4] });
    if (ax.slo) ds.push({ label: '판정선 +1,000ms', data: [{ x: 0, y: (SLO - HOLD) * 1000 }, { x: xm, y: (SLO - HOLD) * 1000 }], showLine: true, pointRadius: 0, borderColor: '#94a3b8', borderDash: [2, 4] });
    return ds;
  };
  for (const key of Object.keys(AX)) {
    const ax = AX[key];
    quadCharts[key] = new Chart(quad.querySelector(`[data-c="${key}"]`), {
      type: 'scatter', data: { datasets: quadData(key) },
      options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'nearest', intersect: false },
        scales: { x: { min: 0, ...(ax.xmax ? { max: ax.xmax } : {}), title: { display: true, text: ax.xt } },
          y: ax.log ? { type: 'logarithmic', min: 5, title: { display: true, text: ax.yt } } : { min: 0, title: { display: true, text: ax.yt } } },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 18 } },
          tooltip: { callbacks: {
            title: (it) => (it[0]?.raw?.st ? `${it[0].dataset.label} · ${fmt(it[0].raw.st.conn)}커넥션` : ''),
            label: (it) => {
              const st = it.raw.st; if (!st) return it.dataset.label;
              const ex = (k) => (st[k] ? `+${fmt(st[k] - HOLD * 1000)}` : '—');
              return [`${fmt(st.rps, 0)}요청/초 · 서버 CPU ${fmt(st.cpu_pct, 0)}% · GC 정지 ${fmt(st.gc_pct, 0)}% · ${okText(st)}`,
                `추가 지연 p50 ${ex('p50_ms')} · p75 ${ex('p75_ms')} · p90 ${ex('p90_ms')} · p99 ${ex('p99_ms')} ms`];
            },
          } } } },
    });
  }
  const onQ = () => { for (const k of Object.keys(AX)) { quadCharts[k].data.datasets = quadData(k); quadCharts[k].update(); } };
  ['fam', 'pct'].forEach((k) => q(k).addEventListener('change', onQ));
  handles.push({ destroy() { ['fam', 'pct'].forEach((k) => q(k).removeEventListener('change', onQ)); Object.values(quadCharts).forEach((c) => c.destroy()); } });
  // 같은 처리량을 낼 때 CPU가 얼마나 다른지: 같은 패밀리는 RAM·힙이 같아 같은 단계 = 거의 같은 커넥션·처리량.
  // 패밀리 사이 비교는 하지 않는다(힙이 작을수록 같은 요청에도 GC가 더 자주 돌아 CPU가 늘어 프로세서 차이와 섞임).
  const REF = '70';
  const cpuAt = (n) => { const st = T[n].stages[REF]; return st && !st.errors && st.cpu_pct != null ? st.cpu_pct : null; };
  const famPair = (g, i) => (T[g] && T[i] && cpuAt(g) != null && cpuAt(i) != null ? `${short(g)} ${fmt(cpuAt(g), 0)}% vs ${short(i)} ${fmt(cpuAt(i), 0)}%` : '');
  slot('quad-lead').innerHTML = `<p>요청마다 ${HOLD}초를 일부러 기다리므로(느린 하위 시스템) 처리량은 이상적으로 커넥션 ÷ ${HOLD}이고, 지연은 ${HOLD}초를 뺀 <strong>추가 지연</strong>(GC 정지·처리 시간)으로 그렸습니다. `
    + '같은 패밀리는 RAM·힙이 같아 같은 커넥션에서 바로 비교할 수 있습니다. 위 선택으로 패밀리와 지연 분위수를 바꿀 수 있고, 점에 마우스를 올리면 그 단계의 처리량·CPU·GC·분위수가 모두 나옵니다.</p>'
    + `<p><strong>처리량은 같은 커넥션에서 거의 같고(그림 2), 차이는 그 처리량을 내는 데 드는 CPU와 지연에서 납니다(그림 1·3).</strong> 같은 부하(이론 최대의 ${REF}% 단계)에서 서버 CPU는 ${[['c8g.xlarge', 'c8i.xlarge'], ['m8g.xlarge', 'm8i.xlarge'], ['r8g.xlarge', 'r8i.xlarge'], ['r6g.xlarge', 'r6i.xlarge']].map(([g, i]) => famPair(g, i)).filter(Boolean).join(', ')}. 선이 끝나는 지점은 OOM(메모리 한계) 직전 단계입니다.</p>`;

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
        return `<tr><td>${p}%</td><td>${fmt(st.conn)}</td><td>${fmt(st.rps, 0)}</td><td>${ex(st.p50_ms)}</td><td>${ex(st.p75_ms)}</td><td>${ex(st.p90_ms)}</td>${hasP95 ? `<td>${ex(st.p95_ms)}</td>` : ''}<td><strong>${ex(st.p99_ms)}</strong></td>`
          + `<td>${fmt(st.cpu_pct, 0)}%</td><td>${fmt(st.gc_pct, 0)}%</td><td>${st.gc_max_ms != null ? fmt(st.gc_max_ms) : '—'}</td><td>${st.old_after_gc_mb != null ? `${fmt(st.old_after_gc_mb / 1024, 1)}GB` : '—'}</td><td>${okText(st)}</td></tr>`;
      }).join('');
      det.querySelector('[data-stage-table]').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>부하 (이론 최대 대비)</th><th>커넥션</th><th>요청/초</th><th>p50 추가</th><th>p75 추가</th><th>p90 추가</th>${hasP95 ? '<th>p95 추가</th>' : ''}<th>p99 추가 (ms)</th><th>서버 CPU</th><th>GC 정지 비율</th><th>최대 GC 정지 (ms)</th><th>GC 후 old 영역</th><th>결과 (5회)</th></tr></thead><tbody>${rowsH}</tbody></table></div>`
        + `<p class="caption">${short(n)} · 힙 ${fmt(T[n].heap_mb / 1024, 1)}GB (상주 ${fmt(T[n].live_mb / 1024, 1)}GB) · 이론 최대 ${fmt(T[n].k)}커넥션. 지연은 대기 ${HOLD}초를 뺀 값(ms), 모든 값은 5회 중앙값. OOM이 난 단계의 CPU·GC는 재시작한 서버의 값이라 참고하지 마세요.</p>`;
    };
    const sel = det.querySelector('[data-pick]');
    const onPick = () => draw(sel.value);
    sel.addEventListener('change', onPick); draw(sel.value);
    handles.push({ destroy() { sel.removeEventListener('change', onPick); } });
  }

  // ---------- 가성비 순위 (표준 리포트의 순위 그림 대체 — 단계 양자화로 '버틴 커넥션' 순위는 패밀리 구분 외 정보가 없음) ----------
  const maxRps = (n) => T[n].stages[String(T[n].util_pct)]?.rps || null;             // 버틴 단계의 처리량
  const perM = (n) => (maxRps(n) ? (meta[n].price / 3600 / maxRps(n)) * 1e6 : null); // 100만 요청당 USD
  const valueRank = (host) => {
    host.innerHTML = '<div class="chart-row"><div class="chart-box" data-v="cost"></div><div class="chart-box" data-v="cpu"></div></div>';
    const mk = (el, list, val, title, f) => {
      el.style.height = `${list.length * 22 + 80}px`;
      el.innerHTML = '<canvas></canvas>';
      return new Chart(el.querySelector('canvas'), {
        type: 'bar',
        data: { labels: list.map(short), datasets: [{ data: list.map(val), backgroundColor: list.map((n) => archColor(meta[n].arch, shade(n))), borderRadius: 2 }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
          scales: { x: { min: 0, title: { display: true, text: title } }, y: { ticks: { autoSkip: false, font: { size: 11 }, callback(v) { const n = list[v]; return n ? `${short(n)}  ${title.includes('패밀리') ? meta[n].family : ''}` : v; } } } },
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => f(list[c.dataIndex]) } } } },
      });
    };
    const byM = names.filter((n) => perM(n)).sort((a, b) => perM(a) - perM(b));
    const famOrder = { C: 0, M: 1, R: 2 };
    const byC = names.filter((n) => cpuAt(n) != null).sort((a, b) => famOrder[meta[a].family] - famOrder[meta[b].family] || cpuAt(a) - cpuAt(b));
    const c1 = mk(host.querySelector('[data-v="cost"]'), byM, perM, '100만 요청당 USD (최대 처리량 기준)',
      (n) => `$${perM(n).toFixed(4)} · ${fmt(maxRps(n), 0)}요청/초 · ${fmt(cap(n))}커넥션 · $${meta[n].price.toFixed(3)}/시간`);
    const c2 = mk(host.querySelector('[data-v="cpu"]'), byC, cpuAt, `같은 부하(이론 최대 ${REF}%)에서의 서버 CPU (%) — 패밀리 안에서 비교`,
      (n) => { const st = T[n].stages[REF]; return `${meta[n].family} · CPU ${fmt(cpuAt(n), 0)}% · ${fmt(st.conn)}커넥션 · ${fmt(st.rps, 0)}요청/초 · GC 정지 ${fmt(st.gc_pct, 0)}%`; });
    return { destroy() { c1.destroy(); c2.destroy(); } };
  };

  // ---------- 표준 리포트 ----------
  const A = envelope.analysis?.sbmem_capacity;
  if (A) {
    handles.push(standardReport(slot('report'), rows, A, {
      unit: '커넥션',
      numberPrefix: '2-',
      rankTitle: '가성비 순위 — 100만 요청당 비용과 CPU 효율',
      rankCaption: '왼쪽 = 기준(p99 ≤ 대기 + 1초, 오류 0)을 지키며 낸 최대 처리량으로 100만 요청을 처리하는 비용(낮을수록 좋음). 오른쪽 = 같은 패밀리(같은 RAM·힙) 안에서 같은 부하 단계의 서버 CPU(낮을수록 같은 일을 적은 CPU로 처리 — GC·처리 효율). 패밀리 사이는 힙 크기가 달라 직접 비교하지 않습니다.',
      rank: (host) => valueRank(host),
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
