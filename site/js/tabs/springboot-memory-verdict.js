// 메모리 압박 탭의 '종합 판정과 권고' — 두 운영 상황을 같은 M 패밀리 6종으로 함께 본다.
//   (1) 동시접속이 많은 환경: 이 탭의 메모리 압박 측정(요청이 10초 머묾 → 처리 중 요청이 쌓임)
//   (2) 트래픽이 올라가는 환경: 48시간 트래픽 측정(springboot-traffic48 — 요청률 23.5k → 90k RPS, 짧은 요청)
// 수치는 두 data/*.json에서만 읽는다(하드코딩 수치 없음). 탭 JS 규칙과 같이 그리기·문장 조립만 한다.
import { fmt, archColor } from '../shared.js';
import { x, short } from '../report.js';

const SIX = ['m7i.xlarge', 'm7i-flex.xlarge', 'm8i.xlarge', 'm8i-flex.xlarge', 'm7g.xlarge', 'm8g.xlarge'];
const BASE = 'm7i.xlarge';
const BAND = 0.05;

export function renderVerdict(host, { T, meta, HOLD, SLO, t48 }) {
  const handles = [];
  const six = SIX.filter((n) => T[n] && meta[n]);
  const shade = (n) => (meta[n].gen >= 8 ? 0.95 : meta[n].gen >= 7 ? 0.6 : 0.35);
  const lineStyle = (n) => ({ borderColor: archColor(meta[n].arch, shade(n)), backgroundColor: archColor(meta[n].arch, shade(n)), borderDash: /flex/.test(n) ? [6, 4] : [] });
  const price = (n) => meta[n].price;

  // ---------- (1) 동시접속: 메모리 압박 측정 ----------
  const stages = (n) => Object.values(T[n].stages).filter((st) => !st.errors).sort((a, b) => a.conn - b.conn);
  const capOf = (n) => T[n].capacity;
  const atStage = (n, pct) => T[n].stages[String(pct)];
  const refPct = (() => { // 6종이 모두 통과한 가장 높은 단계(같은 부하에서 비교)
    const ok = (p) => six.every((n) => { const st = atStage(n, p); return st && !st.errors && st.slo_pass === st.runs; });
    return [...new Set(six.flatMap((n) => Object.keys(T[n].stages).map(Number)))].sort((a, b) => b - a).find(ok);
  })();
  const conc = Object.fromEntries(six.map((n) => {
    const st = refPct ? atStage(n, refPct) : null;
    return [n, { cap: capOf(n), costPerK: price(n) / (capOf(n) / 1000), p99x: st ? st.p99_ms - HOLD * 1000 : null, cpu: st?.cpu_pct, conn: st?.conn,
      peakCpu: Math.max(...stages(n).map((s) => s.cpu_pct ?? 0)) }];
  }));

  // ---------- (2) 트래픽 상승: 48시간 측정 ----------
  const E = t48?.envelope;
  const C = E?.comparisons || {};
  const cmp = (g, m, n) => (C[g]?.[m] || []).find((r) => r.instance === n);
  const levels = (() => { // 첫째 날 단계별(목표 RPS) 구간 p99·성공 RPS 중앙값
    if (!E) return [];
    const by = new Map();
    for (const p of E.phases) {
      if (!p.finished || !p.name.startsWith('d1') || p.duration_seconds < 600) continue;
      const k = Math.round(p.rate_rps / 1000) * 1000;
      if (!by.has(k)) by.set(k, []);
      by.get(k).push(p);
    }
    const med = (v) => { const s = v.filter((q) => q != null).sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };
    return [...by.entries()].sort((a, b) => a[0] - b[0]).map(([rate, ps]) => ({
      rate, n: ps.length,
      by: Object.fromEntries(six.map((n) => [n, { p99: med(ps.map((p) => p.instances[n]?.p99_ms)), rps: med(ps.map((p) => p.instances[n]?.success_rps)), drop: med(ps.map((p) => 100 * (p.instances[n]?.dropped_fraction || 0))) }])),
    }));
  })();
  const peak = Object.fromEntries(six.map((n) => {
    const r = cmp('peak90', 'observed', n), lo = cmp('day2_low', 'idle_qualified', n), l60 = cmp('peak_3600s', 'observed', n), l1 = cmp('peak_60s', 'observed', n);
    const ppd = r?.rps_ratio != null ? r.rps_ratio / (price(n) / price(BASE)) : null;
    return [n, { rps: r?.target?.success_rps, rpsX: r?.rps_ratio, p99: r?.target?.p99_ms, p99X: r?.p99_ratio, drop: r?.target?.drop_pct, ppd,
      per100M: r?.target?.success_rps ? (price(n) / 3600 / r.target.success_rps) * 1e8 : null,
      lowP99X: lo?.p99_ratio, lowP99: lo?.target?.p99_ms, l1X: l1?.rps_ratio, l60X: l60?.rps_ratio }];
  }));

  // ---------- 문장 조립 ----------
  const rank = (obj, key, asc) => six.filter((n) => obj[n]?.[key] != null).sort((a, b) => (asc ? obj[a][key] - obj[b][key] : obj[b][key] - obj[a][key]));
  const concBest = rank(conc, 'costPerK', true), peakBest = rank(peak, 'ppd', false), lowCheap = six.filter((n) => peak[n].lowP99X != null && peak[n].lowP99X <= 1 + BAND).sort((a, b) => price(a) - price(b));
  const g78 = six.filter((n) => meta[n].arch === 'graviton' && meta[n].gen >= 7), intel = six.filter((n) => meta[n].arch === 'intel');
  const latRise = (n) => { const v = levels.map((l) => l.by[n].p99).filter((q) => q != null); return v.length > 1 ? v[v.length - 1] / v[0] : null; };
  const kneeOf = (n) => { // p99가 평상시의 3배를 처음 넘는 목표 RPS
    if (!levels.length || levels[0].by[n].p99 == null) return null;
    const base = levels[0].by[n].p99; const l = levels.find((q) => q.by[n].p99 != null && q.by[n].p99 > 3 * base); return l ? l.rate : null;
  };
  const midLv = levels.length > 2 ? levels[Math.floor((levels.length - 1) / 2)] : null; // 평상시와 피크 사이 단계
  const flexHold = ['m7i-flex.xlarge', 'm8i-flex.xlarge'].filter((n) => peak[n]?.l1X != null && peak[n]?.l60X != null);
  const fmtK = (v) => `${fmt(v / 1000, 1)}k`;

  host.innerHTML = `
    <p class="rel-note">운영에서 인스턴스가 한계에 닿는 방식은 크게 둘입니다. <strong>동시접속이 많은 환경</strong>(DB·외부 API가 느려 요청이 오래 머묾 → 처리 중 요청과 객체가 쌓여 메모리가 먼저 참)과 <strong>트래픽이 올라가는 환경</strong>(요청은 짧지만 초당 요청 수가 급증 → CPU가 먼저 참)입니다. 두 측정에 모두 들어간 같은 M 패밀리 6종(${six.map(short).join(', ')})으로 두 상황의 지연 추이를 나란히 봅니다.</p>
    <div class="quad-grid">
      <div><h3 class="quad-title">동시접속이 늘 때 — p99 추가 지연</h3><div class="ts-controls"><label>인스턴스 <select data-vc="fam"><option value="six">M 6종 (오른쪽과 같은 인스턴스, RAM 16 GiB)</option><option value="R">R 패밀리 전체 (RAM 32 GiB)</option><option value="M">M 패밀리 전체 (RAM 16 GiB)</option><option value="C">C 패밀리 전체 (RAM 8 GiB)</option></select></label></div><div class="chart-box" style="height:320px"><canvas data-vc="conc"></canvas></div>
        <p class="caption">이 탭의 메모리 압박 측정. 가로 = 동시 커넥션(= 처리 중 요청), 세로 = p99 − 대기 ${HOLD}초(ms, 로그). 선이 끝나는 곳 = OOM 직전 — 패밀리마다 RAM이 달라 끝나는 커넥션 수가 다릅니다(C ≈ 2천, M ≈ 6천, R ≈ 1만 3천).</p></div>
      <div><h3 class="quad-title">트래픽이 올라갈 때 — p99</h3><div class="chart-box" style="height:320px"><canvas data-vc="traffic"></canvas></div>
        <p class="caption">48시간 트래픽 측정 첫째 날, 목표 RPS 단계별 구간 p99 중앙값(ms, 로그). 요청은 짧은 정적 응답.</p></div>
    </div>
    <h3>동시 연결이 많은 상황의 CPU·지연 — p90 기준으로 scale out하면</h3>
    <p class="rel-note"><strong>동시 연결 수가 많은 상황에서 CPU와 지연이 어떻게 되는지에 대한 지표입니다. p90 지표로 scale out을 하면 훨씬 가성비 있게 뽑을 수 있습니다.</strong> 힙이 차면 가끔 오는 GC 정지가 p99를 먼저 끌어올리지만, 대부분의 요청(p90)은 그보다 훨씬 늦게 느려집니다. 같은 지연 목표로 오토스케일링을 걸 때 트리거를 p99가 아니라 p90으로 두면, 인스턴스 한 대가 scale out 전까지 더 많은 동시 연결을 받습니다.</p>
    <div class="ts-controls"><label>scale out 기준(추가 지연) <select data-p90="th"><option value="100">+100ms</option><option value="200" selected>+200ms</option><option value="300">+300ms</option></select></label></div>
    <div class="chart-box" data-p90="chart" style="height:380px"><canvas></canvas></div>
    <p class="caption"><strong>그림.</strong> scale out 전까지 인스턴스 한 대가 받는 동시 연결(기준 지연을 넘기 직전 단계, OOM 단계 제외, 5회 중앙값). 옅은 막대 = p99 기준, 진한 막대 = p90 기준.</p>
    <div data-p90="table"></div>
    <p data-p90="note" class="rel-note"></p>
    <h3>KEDA로 scale out할 때 — 48시간 시뮬레이션</h3>
    <p class="rel-note">KEDA(HPA)에 <strong>p90 지연</strong>과 <strong>CPU 사용률</strong> 두 트리거를 걸면 둘 중 더 많은 replica를 요구하는 쪽을 따릅니다. 아래는 이 탭의 측정값으로 pod 한 대가 두 기준을 모두 지키며 받는 동시 연결(단계 사이는 선형 보간, OOM 단계 이전까지)을 구하고, 48시간 트래픽 측정의 구간별 요청률 모양을 동시 연결로 바꿔 필요한 replica 수와 비용을 계산한 것입니다.</p>
    <div class="ts-controls">
      <label>p90 기준(추가 지연) <select data-k="p90"><option value="100">+100ms</option><option value="200">+200ms</option><option value="300" selected>+300ms</option><option value="500">+500ms</option></select></label>
      <label>CPU 기준 <select data-k="cpu"><option value="50">50%</option><option value="60" selected>60%</option><option value="70">70%</option><option value="80">80%</option></select></label>
      <label>피크 동시 연결 <select data-k="peak"><option value="30000">30,000</option><option value="100000" selected>100,000</option><option value="300000">300,000</option></select></label>
      <label>최소 replica <select data-k="min"><option value="1">1</option><option value="2" selected>2</option><option value="3">3</option></select></label>
    </div>
    <div class="quad-grid">
      <div><h3 class="quad-title">48시간 비용 (낮을수록 좋음)</h3><div class="chart-box" data-k="cost" style="height:520px"><canvas></canvas></div></div>
      <div><h3 class="quad-title">시간에 따른 replica 수 (8세대 M·R 짝 — C는 표 참고)</h3><div class="chart-box" style="height:520px"><canvas data-k="rep"></canvas></div></div>
    </div>
    <div data-k="table"></div>
    <p data-k="note" class="rel-note"></p>
    <details class="keda-yaml"><summary>KEDA ScaledObject 예시 (p90 + CPU)</summary><pre><code>apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: app
spec:
  scaleTargetRef:
    name: app                      # Deployment
  minReplicaCount: 2
  maxReplicaCount: 100
  triggers:
    - type: prometheus             # p90 지연 (예: Spring Boot http_server_requests 히스토그램)
      metadata:
        serverAddress: http://prometheus.monitoring:9090
        query: |
          histogram_quantile(0.90, sum(rate(http_server_requests_seconds_bucket{app="app"}[1m])) by (le))
        threshold: "0.3"           # 초 — 서비스의 p90 목표
    - type: cpu                    # CPU 사용률
      metricType: Utilization
      metadata:
        value: "60"</code></pre></details>
    <h3>운영 상황별 판정</h3>
    <div class="table-scroll"><table class="report-table"><thead><tr><th>운영 상황</th><th>무엇이 먼저 한계인가</th><th>근거 (m7i = 1.00배)</th><th>권장</th></tr></thead><tbody>
      <tr><td><strong>동시접속이 많음</strong><br><span class="caption">느린 하위 시스템, 세션·캐시가 큰 서비스</span></td>
        <td>메모리(OOM). 같은 RAM이면 버티는 커넥션이 거의 같고, 차이는 지연·CPU</td>
        <td>버틴 커넥션 ${six.map((n) => `${short(n)} ${fmt(conc[n].cap)}`).join(' · ')}.<br>${refPct ? `같은 부하(이론 최대 ${refPct}%)에서 p99 추가 지연 ${six.map((n) => `${short(n)} +${fmt(conc[n].p99x)}ms`).join(' · ')}, 서버 CPU ${six.map((n) => `${short(n)} ${fmt(conc[n].cpu, 0)}%`).join(' · ')}.` : ''}</td>
        <td><strong>메모리가 큰 패밀리(R)부터</strong>, 같은 RAM에서는 ${g78.map(short).join('·')}(CPU·지연 여유). 1,000커넥션당 비용 최저 ${concBest.slice(0, 2).map((n) => `${short(n)} $${conc[n].costPerK.toFixed(3)}`).join(', ')}</td></tr>
      <tr><td><strong>트래픽이 급증</strong><br><span class="caption">짧은 요청, 피크 90k RPS 목표</span></td>
        <td>CPU(요청 처리량). 피크에서 처리량과 p99가 크게 갈림</td>
        <td>90k 피크 성공 처리량 ${six.map((n) => `${short(n)} ${x(peak[n].rpsX)}`).join(' · ')}; p99 ${six.map((n) => `${short(n)} ${fmt(peak[n].p99, 0)}ms`).join(' · ')}; 미발생 ${six.map((n) => `${short(n)} ${fmt(peak[n].drop, 1)}%`).join(' · ')}</td>
        <td><strong>${peakBest.slice(0, 2).map(short).join(', ')}</strong>(가격 대비 처리량 ${peakBest.slice(0, 2).map((n) => x(peak[n].ppd)).join(', ')}). 1억 요청당 ${peakBest.slice(0, 2).map((n) => `${short(n)} $${peak[n].per100M.toFixed(3)}`).join(', ')}</td></tr>
      <tr><td><strong>피크가 오래 지속</strong><br><span class="caption">1분 → 60분 피크</span></td>
        <td>Flex의 지속 성능(크레딧·제한)</td>
        <td>${flexHold.map((n) => `${short(n)} ${x(peak[n].l1X)} → ${x(peak[n].l60X)}`).join(' · ')} (m7i 대비 처리량, 1분 → 60분 피크)</td>
        <td>${flexHold.length && flexHold.every((n) => Math.abs(peak[n].l60X - peak[n].l1X) <= BAND) ? '긴 피크에서도 Flex가 따로 밀리지 않음 — Flex 사용 가능' : '긴 피크에서 Flex가 밀림 — 표준형 검토'}</td></tr>
      <tr><td><strong>평상시 (여유 부하)</strong><br><span class="caption">둘째 날 23.5k RPS, 같은 구간 교집합</span></td>
        <td>한계 없음 — 지연만 비교</td>
        <td>p99 ${six.map((n) => `${short(n)} ${peak[n].lowP99X != null ? x(peak[n].lowP99X) : '—'}`).join(' · ')}</td>
        <td>p99가 m7i ±5% 이내인 것 중 가장 싼 ${lowCheap.slice(0, 2).map((n) => `${short(n)}($${price(n).toFixed(3)}/시간)`).join(', ')}</td></tr>
    </tbody></table></div>
    <p class="caption"><strong>표.</strong> 운영 상황별 판정. 두 측정 모두 타입별 1호스트이고, 48시간 측정의 피크는 클라이언트 동시성 한도·지연이 섞인 관측(미발생 요청 포함)입니다. 메모리 압박 측정은 부하를 10% 간격으로 올려 같은 단계에서 멈춘 인스턴스끼리의 차이는 구분하지 못합니다.</p>
    <h3>권고</h3>
    <ul class="recs">
      <li><strong>먼저 워크로드가 어느 쪽인지 보십시오.</strong> 요청이 오래 머물러 처리 중 요청이 쌓이는 서비스는 메모리가 한계라 <strong>RAM이 큰 인스턴스</strong>가, 짧은 요청이 몰리는 서비스는 CPU가 한계라 <strong>코어 성능이 좋은 인스턴스</strong>가 유리합니다. 같은 인스턴스라도 두 상황의 순위가 다릅니다(동시접속: ${concBest.slice(0, 3).map(short).join(' > ')} / 트래픽 급증: ${peakBest.slice(0, 3).map(short).join(' > ')}, 가성비 기준).</li>
      <li><strong>동시접속이 많은 서비스</strong>는 같은 RAM에서 버티는 커넥션 수가 아키텍처와 거의 무관했습니다. 대신 같은 부하에서 Graviton 7·8세대가 CPU와 지연을 덜 썼고(OOM 전 최대 CPU ${g78.map((n) => `${short(n)} ${fmt(conc[n].peakCpu, 0)}%`).join(', ')} vs ${intel.map((n) => `${short(n)} ${fmt(conc[n].peakCpu, 0)}%`).join(', ')}), 시간당 가격이 낮아 커넥션당 비용이 가장 낮습니다. 커넥션이 더 필요하면 CPU보다 <strong>RAM을 늘리는 쪽(M → R)</strong>이 효과적입니다.</li>
      <li><strong>동시 연결이 많은 서비스의 오토스케일링은 p90 지연을 트리거로</strong> 두면 인스턴스당 받는 연결이 늘어 같은 연결을 더 적은 인스턴스로 처리합니다(위 그림·표). p99는 GC 정지 꼬리에 먼저 반응해 너무 일찍 scale out합니다. 메모리 사용률 알람은 별도로 두십시오.</li>
      <li><strong>KEDA 트리거는 p90 지연 + CPU를 함께</strong> 거십시오. 이 워크로드는 CPU가 오르기 전에 지연·메모리가 먼저 한계에 닿아 CPU 트리거만으로는 scale out이 늦습니다(위 시뮬레이션). 메모리 사용률 알람(OOM 방지)은 별도로 두십시오.</li>
      <li><strong>트래픽이 급증하는 서비스</strong>에서는 요청률이 오를수록 p99가 갈립니다. 목표 ${midLv ? fmtK(midLv.rate) : '—'} RPS 단계의 p99는 ${six.filter((n) => midLv?.by[n].p99 != null).sort((a, b) => midLv.by[a].p99 - midLv.by[b].p99).map((n) => `${short(n)} ${fmt(midLv.by[n].p99, 1)}ms`).join(', ')}이고, 평상시 → 90k 목표에서 p99는 ${six.map((n) => `${short(n)} ${latRise(n) ? x(latRise(n), 1) : '—'}`).join(', ')}로 늘었습니다. 피크 여유가 필요하면 8세대(${six.filter((n) => meta[n].gen >= 8).map(short).join('·')})를 쓰고, ${six.filter((n) => peak[n].rpsX != null && peak[n].rpsX < 1 - BAND).map(short).join('·') || '—'}는 피크 처리량이 m7i보다 낮아 피크가 있는 서비스에는 권하지 않습니다.</li>
      <li><strong>Flex</strong>는 이번 측정에서 평상시 p99가 표준형과 같고, 60분 피크에서도 표준형 대비 처리량이 유지됐습니다. 가격이 낮으므로 <strong>8세대 Intel이 필요하면 m8i-flex</strong>가 우선 후보입니다(단일 호스트·1회 관측).</li>
      <li><strong>두 상황이 섞인 서비스</strong>(동시접속이 많고 피크도 있는)는 ${(() => { const both = six.filter((n) => concBest.indexOf(n) < 3 && peakBest.indexOf(n) < 3); return both.length ? `두 순위에서 모두 상위 3위 안인 <strong>${both.map(short).join(', ')}</strong>` : '두 순위의 상위가 겹치지 않으므로, 피크 여유를 우선하면 트래픽 순위 상위, 비용·메모리를 우선하면 동시접속 순위 상위'; })()}를 기준으로 RAM(패밀리)을 정하십시오. 실제 적용 전에는 서비스의 요청 비용·지연 목표로 재측정해야 합니다.</li>
    </ul>`;

  // ---------- p90 기준 scale-out ----------
  const P90_SET = ['c8g.xlarge', 'c8i.xlarge', ...SIX, 'r6g.xlarge', 'r7g.xlarge', 'r8g.xlarge', 'r8i.xlarge'].filter((n) => T[n] && meta[n]);
  const capAt = (n, key, th) => { // 기준 추가 지연 이하를 연속으로 지킨 마지막 단계의 커넥션
    let best = 0;
    for (const st of Object.values(T[n].stages).sort((a, b) => a.conn - b.conn)) {
      if (st.errors || st[key] == null || st[key] - HOLD * 1000 > th) break;
      best = st.conn;
    }
    return best;
  };
  const p90Host = host.querySelector('[data-p90="chart"]');
  let p90Chart = null;
  const drawP90 = () => {
    const th = Number(host.querySelector('[data-p90="th"]').value);
    const rowsP = P90_SET.map((n) => { const a = capAt(n, 'p99_ms', th), b = capAt(n, 'p90_ms', th);
      return { n, a, b, ca: a ? price(n) / (a / 1000) : null, cb: b ? price(n) / (b / 1000) : null }; });
    if (p90Chart) p90Chart.destroy();
    p90Chart = new Chart(p90Host.querySelector('canvas'), {
      type: 'bar',
      data: { labels: rowsP.map((r) => short(r.n)), datasets: [
        { label: `p99 ≤ +${th}ms 기준`, data: rowsP.map((r) => r.a), backgroundColor: rowsP.map((r) => archColor(meta[r.n].arch, 0.3)) },
        { label: `p90 ≤ +${th}ms 기준`, data: rowsP.map((r) => r.b), backgroundColor: rowsP.map((r) => archColor(meta[r.n].arch, 0.9)) }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        scales: { y: { min: 0, title: { display: true, text: 'scale out 전 인스턴스당 동시 연결' } } },
        plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { afterBody: (it) => { const r = rowsP[it[0].dataIndex];
          return r.a && r.b ? [`p90 기준이 ${x(r.b / r.a)} 더 받음`, `1,000연결당 $${r.ca.toFixed(3)} → $${r.cb.toFixed(3)}/시간`] : []; } } } } },
    });
    host.querySelector('[data-p90="table"]').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>인스턴스</th><th>p99 기준 연결</th><th>p90 기준 연결</th><th>더 받는 배수</th><th>1,000연결당 $/시간 (p99 → p90)</th><th>절감</th></tr></thead><tbody>${
      rowsP.map((r) => `<tr><td><strong>${short(r.n)}</strong></td><td>${fmt(r.a)}</td><td>${fmt(r.b)}</td><td><strong>${r.a && r.b ? x(r.b / r.a) : '—'}</strong></td><td>${r.ca ? `$${r.ca.toFixed(3)}` : '—'} → ${r.cb ? `$${r.cb.toFixed(3)}` : '—'}</td><td>${r.ca && r.cb ? `${fmt((1 - r.cb / r.ca) * 100, 0)}%` : '—'}</td></tr>`).join('')}</tbody></table></div>`;
    const gain = rowsP.filter((r) => r.a && r.b && r.b > r.a);
    const best = rowsP.filter((r) => r.cb).sort((a, b) => a.cb - b.cb).slice(0, 3);
    host.querySelector('[data-p90="note"]').innerHTML = gain.length
      ? `+${th}ms 기준에서 p90 트리거는 ${gain.length}/${rowsP.length}개 인스턴스에서 scale out 전 연결을 ${x(Math.min(...gain.map((r) => r.b / r.a)))}~${x(Math.max(...gain.map((r) => r.b / r.a)))} 늘려, 같은 동시 연결을 ${fmt((1 - Math.max(...gain.map((r) => r.a / r.b))) * 100, 0)}~${fmt((1 - Math.min(...gain.map((r) => r.a / r.b))) * 100, 0)}% 적은 인스턴스로 처리합니다. p90 기준 1,000연결당 비용이 가장 낮은 것은 ${best.map((r) => `${short(r.n)} $${r.cb.toFixed(3)}`).join(', ')}입니다. `
        + 'p90 트리거는 상위 10% 요청이 기준보다 느릴 수 있다는 뜻이므로, p99 목표가 계약(SLA)으로 묶인 서비스라면 p99 기준을 유지하십시오. 메모리 한계(OOM)는 지연 기준과 무관하므로 메모리 사용률 알람은 별도로 두어야 합니다.'
      : `+${th}ms 기준에서는 p90과 p99 트리거의 차이가 없습니다(메모리 한계에 먼저 닿음).`;
  };
  const thSel = host.querySelector('[data-p90="th"]');
  thSel.addEventListener('change', drawP90); drawP90();
  handles.push({ destroy() { thSel.removeEventListener('change', drawP90); if (p90Chart) p90Chart.destroy(); } });

  // ---------- KEDA 시뮬레이션 ----------
  const kedaCap = (n, p90Th, cpuTh) => { // pod 한 대가 p90 추가 지연 ≤ p90Th, CPU ≤ cpuTh, OOM 없음을 지키는 동시 연결(선형 보간)
    const st = Object.values(T[n].stages).filter((q) => !q.errors && q.p90_ms != null && q.cpu_pct != null).sort((a, b) => a.conn - b.conn);
    let prev = null;
    for (const q of st) {
      const ex = q.p90_ms - HOLD * 1000;
      if (ex <= p90Th && q.cpu_pct <= cpuTh) { prev = q; continue; }
      if (!prev) return { cap: 0, by: ex > p90Th ? 'p90' : 'CPU' };
      const pe = prev.p90_ms - HOLD * 1000, cand = [];
      if (ex > p90Th && ex !== pe) cand.push([prev.conn + ((q.conn - prev.conn) * (p90Th - pe)) / (ex - pe), 'p90 지연']);
      if (q.cpu_pct > cpuTh && q.cpu_pct !== prev.cpu_pct) cand.push([prev.conn + ((q.conn - prev.conn) * (cpuTh - prev.cpu_pct)) / (q.cpu_pct - prev.cpu_pct), 'CPU']);
      cand.sort((a, b) => a[0] - b[0]);
      return cand.length ? { cap: cand[0][0], by: cand[0][1] } : { cap: prev.conn, by: 'p90 지연' };
    }
    return { cap: prev ? prev.conn : 0, by: '메모리(OOM)' };
  };
  const PH = (E?.phases || []).filter((q) => q.finished);
  const pkRate = Math.max(...PH.map((q) => q.rate_rps), 1);
  const kHost = (k) => host.querySelector(`[data-k="${k}"]`);
  const KEDA_PAIRS = ['m8g.xlarge', 'm8i.xlarge', 'r8g.xlarge', 'r8i.xlarge'].filter((n) => T[n] && meta[n]);
  let kCost = null, kRep = null;
  const drawKeda = () => {
    const p90Th = Number(kHost('p90').value), cpuTh = Number(kHost('cpu').value), peakConn = Number(kHost('peak').value), minR = Number(kHost('min').value);
    const all = Object.keys(T).filter((n) => meta[n]);
    const sim = all.map((n) => {
      const { cap, by } = kedaCap(n, p90Th, cpuTh);
      if (!cap || !PH.length) return { n, cap, by, cost: null };
      let cost = 0, peakR = 0, rh = 0, hrs = 0;
      const series = PH.map((q) => { const conn = (peakConn * q.rate_rps) / pkRate, r = Math.max(minR, Math.ceil(conn / cap)), h = q.hour_end - q.hour_start;
        cost += r * price(n) * h; rh += r * h; hrs += h; peakR = Math.max(peakR, r); return { x: q.hour_start, y: r, x2: q.hour_end }; });
      return { n, cap, by, cost, peakR, avgR: rh / hrs, series };
    }).filter((r) => r.cost != null).sort((a, b) => a.cost - b.cost);
    const best = sim[0]?.cost;
    if (kCost) kCost.destroy();
    kHost('cost').innerHTML = '<canvas></canvas>';
    kCost = new Chart(kHost('cost').querySelector('canvas'), {
      type: 'bar', data: { labels: sim.map((r) => short(r.n)), datasets: [{ data: sim.map((r) => r.cost), backgroundColor: sim.map((r) => archColor(meta[r.n].arch, shade(r.n))), borderRadius: 2 }] },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
        scales: { x: { min: 0, title: { display: true, text: '48시간 비용 (USD, On-Demand)' } }, y: { ticks: { autoSkip: false, font: { size: 11 } } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => { const r = sim[c.dataIndex];
          return [`$${r.cost.toFixed(1)} (최저 대비 ${x(r.cost / best)})`, `pod당 ${fmt(r.cap)}연결 — ${r.by}가 먼저 한계`, `피크 ${r.peakR}대 · 평균 ${fmt(r.avgR, 1)}대`]; } } } } },
    });
    if (kRep) kRep.destroy();
    kRep = new Chart(kHost('rep'), {
      type: 'line', data: { datasets: sim.filter((r) => KEDA_PAIRS.includes(r.n)).sort((a, b) => KEDA_PAIRS.indexOf(a.n) - KEDA_PAIRS.indexOf(b.n)).map((r) => ({
        label: short(r.n), stepped: true, pointRadius: 0, borderWidth: 2, ...lineStyle(r.n), borderDash: meta[r.n].family === 'C' ? [3, 3] : meta[r.n].family === 'M' ? [8, 3] : [],
        data: r.series.flatMap((q) => [{ x: q.x, y: q.y }, { x: q.x2, y: q.y }]) })) },
      options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'nearest', intersect: false },
        scales: { x: { type: 'linear', min: 0, max: 48, title: { display: true, text: '시간 (48시간 트래픽 모양)' } }, y: { min: 0, title: { display: true, text: 'replica 수' } } },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 18 } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y}대` } } } },
    });
    kHost('table').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>순위</th><th>인스턴스</th><th>pod당 동시 연결</th><th>먼저 걸리는 기준</th><th>피크 replica</th><th>평균 replica</th><th>48시간 비용</th><th>최저 대비</th></tr></thead><tbody>${
      sim.map((r, i) => `<tr><td>${i + 1}</td><td><strong>${short(r.n)}</strong></td><td>${fmt(r.cap)}</td><td>${r.by}</td><td>${r.peakR}</td><td>${fmt(r.avgR, 1)}</td><td><strong>$${r.cost.toFixed(1)}</strong></td><td>${x(r.cost / best)}</td></tr>`).join('')}</tbody></table></div>`;
    const by = (k) => sim.filter((r) => r.by === k).length;
    const pair = (g, i) => { const a = sim.find((r) => r.n === g), b = sim.find((r) => r.n === i); return a && b ? `${short(g)} $${a.cost.toFixed(1)}(${a.peakR}대) vs ${short(i)} $${b.cost.toFixed(1)}(${b.peakR}대)` : ''; };
    kHost('note').innerHTML = `<strong>p90 +${p90Th}ms · CPU ${cpuTh}% 기준으로 scale out하면</strong> 48시간 비용이 가장 낮은 것은 ${sim.slice(0, 3).map((r) => `${short(r.n)} $${r.cost.toFixed(1)}`).join(', ')}입니다. `
      + `먼저 걸리는 기준은 p90 지연 ${by('p90 지연')}개 · CPU ${by('CPU')}개 · 메모리(OOM) ${by('메모리(OOM)')}개로, ${by('CPU') === 0 ? `CPU ${cpuTh}%에 닿기 전에 지연이나 메모리가 먼저 한계에 닿습니다 — 이 워크로드에서 CPU 트리거만 걸면 scale out이 늦어 지연이 먼저 무너집니다.` : 'CPU 트리거가 먼저 걸리는 인스턴스도 있습니다.'} `
      + `8세대 짝: ${[['c8g.xlarge', 'c8i.xlarge'], ['m8g.xlarge', 'm8i.xlarge'], ['r8g.xlarge', 'r8i.xlarge']].map(([g, i]) => pair(g, i)).filter(Boolean).join(', ')}. `
      + `<span class="caption">가정: 피크 ${fmt(peakConn)} 동시 연결을 48시간 측정의 구간별 요청률 비율로 배분, replica = max(최소 ${minR}, ⌈연결 ÷ pod당 연결⌉), scale out 지연·cooldown·노드 bin-packing·여유율 미반영, 서울 On-Demand 가격. pod 1개 = 인스턴스 1대(xlarge) 기준.</span>`;
  };
  ['p90', 'cpu', 'peak', 'min'].forEach((k) => kHost(k).addEventListener('change', drawKeda));
  drawKeda();
  handles.push({ destroy() { ['p90', 'cpu', 'peak', 'min'].forEach((k) => kHost(k).removeEventListener('change', drawKeda)); if (kCost) kCost.destroy(); if (kRep) kRep.destroy(); } });

  // ---------- 그림 ----------
  const mk = (canvas, datasets, xt, yt, xlog = false) => new Chart(canvas, {
    type: 'scatter', data: { datasets },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'nearest', intersect: false },
      scales: { x: { type: xlog ? 'logarithmic' : 'linear', min: 0, title: { display: true, text: xt } }, y: { type: 'logarithmic', title: { display: true, text: yt } } },
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 18 } }, tooltip: { callbacks: { label: (c) => c.raw.tip || c.dataset.label } } } },
  });
  const famSel = host.querySelector('[data-vc="fam"]');
  const concList = () => (famSel.value === 'six' ? six : Object.keys(T).filter((n) => meta[n] && meta[n].family === famSel.value)
    .sort((a, b) => (meta[a].arch === meta[b].arch ? meta[a].gen - meta[b].gen : meta[a].arch < meta[b].arch ? -1 : 1)));
  const concData = () => {
    const ds = concList().map((n) => ({ label: short(n), showLine: true, tension: 0.15, pointRadius: 3, ...lineStyle(n),
      data: stages(n).filter((st) => st.p99_ms).map((st) => ({ x: st.conn, y: Math.max(st.p99_ms - HOLD * 1000, 5),
        tip: `${short(n)}: ${fmt(st.conn)}커넥션 · p99 +${fmt(st.p99_ms - HOLD * 1000)}ms · CPU ${fmt(st.cpu_pct, 0)}% · ${fmt(st.rps, 0)}요청/초` })) }));
    const cx = Math.max(...ds.flatMap((d) => d.data.map((v) => v.x)));
    ds.push({ label: '판정선 +1,000ms', data: [{ x: 0, y: (SLO - HOLD) * 1000 }, { x: cx, y: (SLO - HOLD) * 1000 }], showLine: true, pointRadius: 0, borderColor: '#94a3b8', borderDash: [2, 4] });
    return ds;
  };
  const concChart = mk(host.querySelector('[data-vc="conc"]'), concData(), '동시 커넥션', 'p99 추가 지연 (ms, 로그)');
  handles.push(concChart);
  const onFam = () => { concChart.data.datasets = concData(); concChart.update(); };
  famSel.addEventListener('change', onFam);
  handles.push({ destroy() { famSel.removeEventListener('change', onFam); } });
  if (levels.length) {
    const trDs = six.map((n) => ({ label: short(n), showLine: true, tension: 0.15, pointRadius: 3, ...lineStyle(n),
      data: levels.filter((l) => l.by[n].p99 != null).map((l) => ({ x: l.rate, y: l.by[n].p99,
        tip: `${short(n)}: 목표 ${fmtK(l.rate)} RPS · 성공 ${fmt(l.by[n].rps)} RPS · p99 ${fmt(l.by[n].p99, 1)}ms · 미발생 ${fmt(l.by[n].drop, 1)}% (구간 ${l.n}개 중앙값)` })) }));
    handles.push(mk(host.querySelector('[data-vc="traffic"]'), trDs, '목표 RPS (첫째 날 단계)', 'p99 ms (로그)'));
  }
  return { destroy() { handles.forEach((h) => h.destroy()); } };
}
