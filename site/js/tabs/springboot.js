// SpringBoot 탭 — 리포트 구조(핵심 결과 → 방법·신뢰도 → 처리량 → 가격 대비 성능 → 짝 비교 → 세대 향상 →
// 패밀리/flex → 지연 → 기동 → 종합 판정·권고). 모든 수치는 envelope.analysis(scripts/dashboard/analysis.py)에서
// 오고, 문장도 그 값으로 조립한다 — HTML에 숫자를 하드코딩하지 않는다(데이터 갱신 시 본문이 어긋나지 않게).
import { archColor, fmt, metricTabChart, resultTable, badge, buildToc } from '../shared.js';
import {
  keyFindings, specTable, reliability, dotBar, ratioBars, pairTable, dumbbell, upliftTable, familyTable,
  priceTable, bandNote, x, pct, short, xRange,
} from '../report.js';

const SPEC_NAMES = ['c5.xlarge', 'c5a.xlarge', 'c6g.xlarge', 'c6i.xlarge', 'c7g.xlarge', 'c7i.xlarge', 'c7i-flex.xlarge',
  'c8g.xlarge', 'c8i.xlarge', 'c8i-flex.xlarge', 'c9g.xlarge', 'm8g.xlarge', 'm8i.xlarge', 'r8g.xlarge', 'r8i.xlarge'];

const p = (html) => `<p>${html}</p>`;
const findPair = (A, left, right) => A.pairs.find((q) => q.left === left && q.right === right)
  || A.flex_pairs.find((q) => q.left === left && q.right === right)
  || A.amd_pairs.find((q) => q.left === left && q.right === right);
const step = (A, from, to) => A.uplift.flatMap((u) => u.steps).find((s) => s.from === from && s.to === to);
const outliers = (A) => new Set(A.peer_outliers.flatMap((o) => [o.left]));

export async function render(root, { rows, envelope }) {
  const handles = [];
  const slot = (name) => root.querySelector(`[data-slot="${name}"]`);
  const fill = (name, html) => { const el = slot(name); if (el) el.innerHTML = html; };
  const AT = envelope.analysis.throughput;
  const AC = envelope.analysis.coldstart;
  const AP = envelope.analysis.p99;
  const T = AT.table;
  const odd = outliers(AT);
  const topPerf = AT.rank_perf.find((n) => !odd.has(n));
  const topPpd = AT.rank_ppd.find((n) => !odd.has(n));
  const g8 = findPair(AT, 'c8g.xlarge', 'c8i.xlarge');
  const g7 = findPair(AT, 'c7g.xlarge', 'c7i.xlarge');
  const g9 = findPair(AT, 'c9g.xlarge', 'c8i.xlarge');
  const up_g = step(AT, 'c7g.xlarge', 'c8g.xlarge');
  const up_i = step(AT, 'c7i.xlarge', 'c8i.xlarge');
  const coldTop = AC.rank_perf[0];
  const c7iflex = AT.peer_outliers.find((o) => o.left === 'c7i-flex.xlarge');
  // 11월 같은 세션 재측정(C2 전용, 호스트 여러 대) — 8세대·Graviton5 판정의 기준값. 4월 단일 세션 값(g8)은 재현되지 않음.
  const RM = envelope.remeasure || { pairs: [], hosts: {}, stats: {} };
  const rm8 = RM.pairs.find((q) => q.left === 'c8g.xlarge' && q.right === 'c8i.xlarge') || g8;
  const rm9 = RM.pairs.find((q) => q.left === 'c9g.xlarge' && q.right === 'c8i.xlarge') || g9;
  const rmUp = RM.pairs.find((q) => q.left === 'c9g.xlarge' && q.right === 'c8g.xlarge');
  const rmN = (n) => (RM.stats[n] ? `${RM.hosts[n]}개 호스트 × ${RM.stats[n].n}회` : '');

  // ---------- 핵심 결과 ----------
  fill('lead', [
    p(`xlarge(4 vCPU) ${Object.keys(T).length}개 인스턴스에서 Spring Boot 최대 처리량과 PetClinic 기동 시간을 측정했습니다. `
      + `가격 대비 성능은 서울 리전 On-Demand 가격으로 계산했고, ${AT.baseline}를 1.00배로 표시했습니다.`),
    p(`<strong>8세대에서는 Intel(c8i)이 앞섭니다.</strong> 같은 세션에서 호스트를 바꿔 가며 다시 잰 값(${rmN('c8g.xlarge')})으로 c8g.xlarge의 처리량은 c8i.xlarge의 ${x(rm8.perf)}, `
      + `가격 대비 성능은 ${x(rm8.ppd)}(${rm8.verdict})입니다. 처리량은 c8i가 높고, 시간당 가격이 ${x(rm8.price)}인 c8g의 가격 이점으로도 따라잡지 못합니다. `
      + `JVM 기본값(Tiered 켜짐)에서는 ${x(envelope.sustained_default.pairs[0].ppd)}로 Intel 우위가 더 뚜렷합니다(§10). 4월 본 데이터만 1.0배를 넘었는데(${x(g8.ppd)}), 재측정에서 재현되지 않았습니다(§2).`),
    p(`<strong>Graviton5(c9g)는 다릅니다.</strong> 같은 세션에서 c9g의 처리량은 c8i의 ${x(rm9.perf)}, 가격 대비 성능 <strong>${x(rm9.ppd)} (${rm9.verdict})</strong>로 측정한 모든 인스턴스 중 가장 높습니다${rmUp ? `(c8g 대비 처리량 ${x(rmUp.perf)})` : ''}. 7세대에서는 c7g가 c7i의 ${x(g7.ppd)}(${g7.verdict})였습니다. 판정과 권고는 §11에 정리했습니다.`),
  ].join(''));
  handles.push(keyFindings(slot('key-findings'), [
    { item: '최대 처리량 1위', result: topPerf, note: `${AT.baseline} 대비 ${x(T[topPerf].perf)}${c7iflex ? ` (c7i-flex ${x(T['c7i-flex.xlarge'].perf)}는 같은 프로세서와 어긋나는 이상치라 제외, §2)` : ''}` },
    { item: '가격 대비 성능 1위', result: topPpd, note: `${AT.baseline} 대비 ${x(T[topPpd].ppd)}` },
    { item: 'Graviton4 vs Intel 8세대 (같은 세션 재측정)', result: `c8g / c8i 가격 대비 성능 ${x(rm8.ppd)}`, note: `처리량 ${x(rm8.perf)}(c8i가 빠름), 가격 ${x(rm8.price)} — ${rm8.verdict}. 4월 단일 세션 값 ${x(g8.ppd)}는 재현 안 됨` },
    { item: 'Graviton5 vs Intel 8세대 (같은 세션 재측정)', result: `c9g / c8i 가격 대비 성능 ${x(rm9.ppd)}`, note: `처리량 ${x(rm9.perf)} — ${rm9.verdict}` },
    { item: 'JVM 기본값일 때', result: `c8g / c8i 가격 대비 성능 ${x(envelope.sustained_default.pairs[0].ppd)}`, note: `처리량 ${x(envelope.sustained_default.pairs[0].perf)} — ${envelope.sustained_default.pairs[0].verdict} (§10)` },
    { item: 'Graviton3 → Graviton4', result: pct(up_g.perf - 1), note: 'c7g → c8g 최대 처리량' },
    { item: 'Sapphire Rapids → Granite Rapids', result: pct(up_i.perf - 1), note: 'c7i → c8i 최대 처리량 (c7i는 호스트 편차 있음, §2)' },
    { item: '콜드 스타트 최단', result: coldTop, note: `PetClinic 기동 ${fmt(AC.table[coldTop].value, 2)}초, JVM 기본값${AC.flagged.includes(coldTop) ? ' — 회차 변동이 커서 순위는 잠정적' : ''}` },
  ]));

  // ---------- 1. 방법 ----------
  handles.push(specTable(slot('specs'), rows, SPEC_NAMES));

  // ---------- 2. 신뢰도 ----------
  handles.push(reliability(slot('reliability'), AT, {
    unit: 'req/s',
    extra: [`${AT.baseline}(기준선)도 회차가 두 무리(${T[AT.baseline].runs.map((v) => fmt(v)).join(', ')})로 갈립니다. 중앙값은 높은 쪽 무리에 속하지만, 기준선 대비 배수는 이 편차만큼 불확실합니다.`],
  }));
  // 같은 설정(C2 전용) 재측정만 사용: 2026-04 세션의 Graviton + 2026-11 재측정(모든 아키텍처, 라운드=호스트별)
  const drift = envelope.session_drift.filter((r) => r.same_config);
  const old = drift.filter((r) => !r.source.startsWith('2026-11'));
  const now = drift.filter((r) => r.source.startsWith('2026-11'));
  const stat = (rs) => {
    const a = rs.map((r) => Math.abs(r.change)).sort((x, y) => x - y);
    if (!a.length) return null;
    const m = a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2;
    return { n: a.length, med: m, max: a[a.length - 1], within: a.filter((v) => v <= AT.band).length };
  };
  const so = stat(old), sn = stat(now);
  const pc = (v) => `${(v * 100).toFixed(1)}%`;
  const roundTxt = (r) => (r.rounds ? Object.entries(r.rounds).map(([k, v]) => `${k.replace('round', '')} ${fmt(v)}`).join(' / ') : '');
  const off = now.filter((r) => Math.abs(r.change) > AT.band);
  const ok = now.filter((r) => Math.abs(r.change) <= AT.band);
  fill('drift-lead', [
    p(`벤치마크 값은 같은 인스턴스를 같은 조건으로 다시 재도 조금씩 달라집니다. 그 폭을 알아야 "두 인스턴스의 차이가 진짜인지"를 판단할 수 있어서, 일부 인스턴스를 다시 쟀습니다. `
      + `<strong>대부분 ±${AT.band * 100}% 안에서 같은 값이 다시 나왔습니다.</strong> 그래서 이 문서는 두 값의 차이가 ±${AT.band * 100}% 이내면 "비슷"으로 판정합니다.`),
    so && p(`<strong>4월에 다시 잰 Graviton ${so.n}개:</strong> 처음 값과의 차이는 보통 ${pc(so.med)}였고(가장 큰 것은 ${pc(so.max)}), ${so.n}개 중 ${so.within}개가 ±${AT.band * 100}% 안이었습니다.`),
    sn && p(`<strong>11월에 다시 잰 ${sn.n}개:</strong> 이번에는 인스턴스마다 서로 다른 서버(EC2 호스트) 2~3대에서 쟀습니다. `
      + (ok.length ? `${ok.map((r) => short(r.name)).join(', ')}는 처음과 거의 같게 나왔습니다. ` : '')
      + (off.length ? `${off.map((r) => `${short(r.name)}(${r.change > 0 ? '+' : ''}${pc(r.change)})`).join(', ')}는 처음 값이 다시 나오지 않았습니다. 처음 잰 날의 서버가 유독 빠르거나 느렸던 것으로 보고, 이 인스턴스들은 다시 잰 값을 기준으로 판정했습니다.` : '')),
  ].filter(Boolean).join(''));
  handles.push(ratioBars(slot('drift'), drift.map((r) => ({ label: `${short(r.name)} (${r.source.startsWith('2026-11') ? '11월' : '4월'})`, value: 1 + r.change })),
    { band: AT.band, title: '다시 잰 값 ÷ 처음 잰 값', neutral: true, min: 0.6 }));

  // ---------- 2-1. 진단 (parsers/springboot.py diagnostics) ----------
  const DG = envelope.diagnostics || { threads: {}, hosts: [] };
  const thr = Object.entries(DG.threads).filter(([, v]) => v['2'] && v['6']);
  const byInst = {};
  DG.hosts.forEach((h) => { (byInst[h.instance] = byInst[h.instance] || []).push(h); });
  const spread = Object.entries(byInst).filter(([, hs]) => hs.length > 1)
    .map(([n, hs]) => ({ n, lo: Math.min(...hs.map((h) => h.rps)), hi: Math.max(...hs.map((h) => h.rps)) }));
  const worst = spread.sort((a, b) => b.hi / b.lo - a.hi / a.lo)[0];
  fill('diag-lead', [
    thr.length && p(`<strong>클라이언트는 병목이 아닙니다.</strong> 같은 서버 호스트에서 wrk 스레드를 2개와 6개로 번갈아 쟀을 때 처리량 변화는 `
      + thr.map(([n, v]) => `${short(n)} ${pct(v['6'] / v['2'] - 1)}`).join(', ') + '였습니다. 클라이언트 스레드를 3배로 늘려도 처리량이 거의 그대로이므로, 측정값은 서버 쪽 상한입니다. '
      + 'c9g는 서버 CPU가 70% 안팎인데도 처리량이 오르지 않았는데, 가벼운 요청에서 Tomcat의 단일 I/O 스레드(NIO Poller)가 상한이 되는 현상(외부 재측정 리포트 §9)과 같은 양상으로 보입니다. 스레드별 CPU는 측정하지 않아 추정입니다.'),
    worst && p(`<strong>호스트 차이가 클럭보다 큽니다.</strong> 같은 타입을 다른 호스트에서 재면 ${short(worst.n)}처럼 최대 ${pct(worst.hi / worst.lo - 1)} 차이가 났고, 이때 부하 중 클럭은 거의 같았습니다(표 4-1). `
      + '부하 중 클럭은 Intel 비교의 보조 지표로 기록하지만, 이 데이터에서 호스트 간 처리량 차이의 주원인은 아니었습니다. 단일 호스트에서 ±5%를 넘는 차이가 나오면 다른 호스트로 재측정해야 하는 이유입니다.'),
  ].filter(Boolean).join(''));
  slot('diag').innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>인스턴스</th><th>EC2 호스트</th><th>AZ</th><th>회차</th><th>처리량 (중앙값)</th><th>부하 중 클럭</th></tr></thead><tbody>${
    DG.hosts.map((h) => `<tr><td>${short(h.instance)}</td><td><code>${h.host}</code></td><td>${h.zone.replace('ap-northeast-', '')}</td><td>${h.runs}</td><td>${fmt(h.rps)}</td><td>${h.mhz ? `${fmt(h.mhz)} MHz` : '—'}</td></tr>`).join('')
  }</tbody></table></div>`;

  // ---------- 3. 처리량 ----------
  fill('throughput-lead', p(`최대 처리량 지수는 회차마다 커넥션 50/100/200 단계 중 가장 높은 처리량을 고른 뒤, 5회의 중앙값을 취한 값입니다. `
    + `상위권은 Intel 8세대(c8i/m8i/r8i와 flex)가 차지하고, Graviton4(r8g/c8g/m8g)가 그 뒤를 잇습니다. `
    + `${c7iflex ? `c7i-flex.xlarge는 같은 Sapphire Rapids인 c7i.xlarge의 ${x(c7iflex.perf)}로, 같은 프로세서로는 설명되지 않는 차이라 재측정이 필요합니다.` : ''}`));
  handles.push(dotBar(slot('throughput-chart'), rows, AT, { names: AT.rank_perf, unit: 'req/s' }));

  // ---------- 4. 가격 대비 성능 ----------
  const pp = AT.rank_ppd.filter((n) => !odd.has(n)).slice(0, 3);
  fill('price-lead', p(`가격 대비 성능은 성능 배수를 시간당 가격 배수로 나눈 값입니다(${AT.baseline} = 1.00배). `
    + `이상치를 제외한 상위는 ${pp.map((n) => `${short(n)}(${x(T[n].ppd)})`).join(', ')}입니다. `
    + `시간당 가격이 c8i보다 ${pct(g8.price - 1)} 낮은 c8g가 처리량 손실(${pct(g8.perf - 1)})보다 가격 절감이 커서 앞섭니다. `
    + `요청 10억 건당 비용은 c8g $${T['c8g.xlarge'].cost.toFixed(2)}, c8i $${T['c8i.xlarge'].cost.toFixed(2)}, ${AT.baseline} $${T[AT.baseline].cost.toFixed(2)}입니다.`));
  handles.push(priceTable(slot('price-table'), rows, AT, { limit: 15 }));

  // ---------- 5. 짝 비교 ----------
  const gpairs = AT.pairs;
  const wins = (gen) => gpairs.filter((q) => q.group === gen);
  const summarizeGen = (gen) => { const ps = wins(gen); return ps.length ? `${gen} ${ps.map((q) => `${short(q.left)[0]} ${x(q.ppd)}`).join(' · ')}` : ''; };
  fill('pairs-lead', p(`같은 세대·같은 패밀리끼리 가격 대비 성능을 나누면 ${['6세대', '7세대', '8세대'].map(summarizeGen).filter(Boolean).join(', ')}입니다. `
    + `6·7세대 Graviton은 시간당 가격이 Intel의 약 0.8배인데 처리량이 ${x(Math.min(...['6세대', '7세대'].flatMap((g) => wins(g).map((q) => q.perf))))}~${x(Math.max(...['6세대', '7세대'].flatMap((g) => wins(g).map((q) => q.perf))))}라 가격 대비 성능에서 밀렸습니다. 8세대에서는 처리량이 ${x(Math.min(...wins('8세대').map((q) => q.perf)))}~${x(Math.max(...wins('8세대').map((q) => q.perf)))}로 올라와 가격 차이만큼 앞서거나 비슷해졌습니다.`));
  handles.push(ratioBars(slot('pairs-chart'), gpairs.map((q) => ({ label: `${short(q.left)} / ${short(q.right)}`, value: q.ppd })), { band: AT.band, title: '가격 대비 성능 (Graviton ÷ Intel)' }));
  handles.push(pairTable(slot('pairs-table'), gpairs));
  handles.push(pairTable(slot('amd-table'), AT.amd_pairs, { caption: '5세대 AMD(EPYC 7R32/7571)는 Intel 5세대보다 약 10% 저렴하지만 처리량이 더 크게 낮아 모든 패밀리에서 가격 대비 성능이 뒤졌습니다.' }));

  // ---------- 6. 세대 향상 ----------
  fill('uplift-lead', p(`세대 교체 효과는 Graviton이 더 컸습니다. c7g → c8g는 처리량 ${pct(up_g.perf - 1)}(가격 ${pct(up_g.price - 1)}, 가격 대비 성능 ${pct(up_g.ppd - 1)}), `
    + `c7i → c8i는 ${pct(up_i.perf - 1)}(가격 ${pct(up_i.price - 1)}, 가격 대비 성능 ${pct(up_i.ppd - 1)})입니다. Intel 쪽은 6 → 7세대 향상이 7 → 8세대보다 컸습니다. `
    + `노드 사양으로 보면 Graviton4는 코어(Neoverse V1 → V2)와 클럭(2.6 → 2.8 GHz)이, Granite Rapids는 클럭(3.2 → 3.9 GHz)이 바뀌었습니다.`));
  handles.push(dumbbell(slot('uplift-chart'), rows, AT, { unit: 'req/s' }));
  handles.push(upliftTable(slot('uplift-table'), rows, AT));

  // ---------- 7. 패밀리 / flex ----------
  const famPerf = AT.families.flatMap((f) => f.map((r) => r.perf));
  fill('family-lead', p(`같은 프로세서의 C/M/R은 처리량 차이가 ${x(Math.min(...famPerf))}~${x(Math.max(...famPerf))}로 작습니다(C = 1.00배). 메모리가 2배씩 늘면서 가격이 올라가므로, 힙을 RAM 비율로 잡은 이번 시험처럼 늘어난 메모리가 처리량에 기여하지 않는 워크로드에서는 C 패밀리의 가격 대비 성능이 가장 좋습니다.`));
  handles.push(familyTable(slot('family-table'), rows, AT));
  const fl8 = AT.flex_pairs.filter((q) => q.left.includes('8i-flex'));
  fill('flex-lead', p(`8세대 flex의 처리량은 표준의 ${xRange(fl8.map((q) => q.perf))}로 같고 가격이 약 5% 낮아, 가격 대비 성능이 그만큼 좋습니다. `
    + 'flex는 기준 성능 이상을 버스트로 제공하는 상품이므로 지속 부하에서 같은 성능이 유지되는지는 부록 A의 장시간 측정으로 확인하십시오. 7세대 flex의 큰 차이는 표준 쪽(c7i, m7i)의 호스트 편차가 섞여 있어 그대로 일반화하지 않습니다.'));
  handles.push(pairTable(slot('flex-table'), AT.flex_pairs));

  // ---------- 8. 지연 ----------
  handles.push(metricTabChart(slot('steps'), rows, [
    { field: 'steps.rps50.value', label: '50 connections', unit: 'req/s', direction: 'max' },
    { field: 'steps.rps100.value', label: '100 connections', unit: 'req/s', direction: 'max' },
    { field: 'steps.rps200.value', label: '200 connections', unit: 'req/s', direction: 'max' },
  ]));
  handles.push(dotBar(slot('p99-chart'), rows, AP, { topN: 20, digits: 2, unit: 'ms' }));

  // ---------- 9. 기동 ----------
  const cg8 = findPair(AC, 'c8g.xlarge', 'c8i.xlarge');
  const cg6 = findPair(AC, 'c6g.xlarge', 'c6i.xlarge');
  fill('cold-lead', p(`PetClinic 기동 시간은 ${short(AC.rank_perf[0])} ${fmt(AC.table[AC.rank_perf[0]].value, 2)}초, ${short(AC.rank_perf[1])} ${fmt(AC.table[AC.rank_perf[1]].value, 2)}초 순으로 짧습니다. `
    + `처리량과 달리 기동은 8세대에서 Graviton이 Intel보다 빨랐고(c8g/c8i ${x(cg8.perf)}), 6세대에서는 반대였습니다(c6g/c6i ${x(cg6.perf)}). `
    + `회차 간 변동계수 중앙값이 처리량보다 크므로(경고 임계 ${AC.thresholds.cv}%) ±${AC.band * 100}% 안의 순위 차이는 의미를 두지 않습니다.`));
  handles.push(dotBar(slot('cold-chart'), rows, AC, { topN: 20, digits: 2, unit: 's' }));
  handles.push(pairTable(slot('cold-pairs'), AC.pairs.map((q) => ({ ...q, ppd: q.perf, verdict: q.perf_verdict }))));
  fill('cold-excluded', `<p class="caption">비교 제외: ${envelope.coldstart_excluded.map(short).join(', ')} — 2026-07 백필 시점의 템플릿이 C2 전용(<code>-XX:-TieredCompilation</code>)이어서 다른 인스턴스(2026-01-20, JVM 기본값)와 프로파일이 다릅니다. C2 전용은 C1 컴파일러 없이 인터프리터로 시작해 기동이 느립니다.</p>`);

  // ---------- 10. JVM 프로파일 ----------
  const SD = envelope.sustained_default;
  const JE = envelope.jvm_profile_effect;
  const sd8 = SD.pairs.find((q) => q.left === 'c8g.xlarge');
  const effG = JE.filter((r) => r.arch === 'graviton');
  const effI = JE.filter((r) => r.arch !== 'graviton');
  fill('jvm-lead', p(`JVM 기본값으로 바꾸면 Graviton(${effG.map((r) => `${short(r.name)} ${pct(r.change)}`).join(', ')})은 처리량이 줄었고, `
    + `Intel(${effI.map((r) => `${short(r.name)} ${pct(r.change)}`).join(', ')})은 거의 변하지 않거나 오히려 늘었습니다. `
    + `그 결과 JVM 기본값에서는 c8g/c8i가 처리량 ${x(sd8.perf)}, 가격 대비 성능 <strong>${x(sd8.ppd)} (${sd8.verdict})</strong>로, C2 전용(${x(g8.ppd)}, ${g8.verdict})과 판정이 바뀝니다. `
    + `Graviton 표본이 c8g 하나이고 두 측정의 세션이 다르므로 크기는 잠정적이지만, 방향은 재측정 편차(±${AT.band * 100}%)보다 큽니다.`));
  handles.push(ratioBars(slot('jvm-chart'), JE.map((r) => ({ label: short(r.name), value: 1 + r.change })), { band: AT.band, title: 'JVM 기본값 ÷ C2 전용 (c100)', neutral: true, min: 0.8 }));
  handles.push(pairTable(slot('jvm-table'), SD.pairs.map((q) => ({ ...q, group: 'JVM 기본값' }))));

  // ---------- 11. 종합 판정 ----------
  const scen = [
    { name: '최대 처리량, 8세대 C — 11월 같은 세션 재측정', ...rm8 },
    { name: '최대 처리량, Graviton5 vs Intel 8세대 — 11월 재측정', ...rm9 },
    { name: '최대 처리량, 8세대 C — 4월 본 데이터(재현 안 됨)', ...g8 },
    { name: '지속 부하, 8세대 C (JVM 기본값)', ...sd8 },
    { name: '최대 처리량, 8세대 M', ...findPair(AT, 'm8g.xlarge', 'm8i.xlarge') },
    { name: '최대 처리량, 8세대 R', ...findPair(AT, 'r8g.xlarge', 'r8i.xlarge') },
    { name: '최대 처리량, 7세대 C', ...g7 },
    { name: '최대 처리량, 6세대 C', ...findPair(AT, 'c6g.xlarge', 'c6i.xlarge') },
    { name: '기동 속도, 8세대 C (가격 무관)', ...cg8, ppd: cg8.perf, verdict: cg8.perf_verdict, price: null },
  ];
  fill('verdict-lead', p(`이번 측정의 목적은 Spring Boot 워크로드에서 어떤 인스턴스의 가격 대비 성능이 좋은지 판단하는 것입니다. xlarge·서울 On-Demand 기준으로 `
    + `8세대 Graviton4(c8g)는 Intel(c8i)보다 처리량이 낮고 가격 대비 성능도 같은 세션 재측정 ${x(rm8.ppd)}, JVM 기본값 ${x(sd8.ppd)}로 Intel과 비슷하거나 뒤집니다. 7세대 이하도 Intel 우위입니다. `
    + `반면 Graviton5(c9g)는 처리량과 가격 대비 성능 모두 1위(c8i 대비 ${x(rm9.ppd)})입니다. 즉 Spring Boot에서는 <strong>8세대 기준 Intel, 최신 세대 기준 Graviton5</strong>가 현재 데이터와 맞는 결론입니다.`));
  handles.push(ratioBars(slot('verdict-chart'), scen.map((s) => ({ label: s.name, value: s.ppd })), { band: AT.band }));
  const vt = slot('verdict-table');
  vt.innerHTML = `<div class="table-scroll"><table class="report-table"><thead><tr><th>시나리오</th><th>비교</th><th>성능</th><th>가격</th><th>가격 대비 성능</th><th>판정</th></tr></thead><tbody>${scen.map((s) => `<tr><td>${s.name}</td><td>${short(s.left)} / ${short(s.right)}</td><td>${x(s.perf)}</td><td>${s.price == null ? '—' : x(s.price)}</td><td><strong>${x(s.ppd)}</strong></td><td><span class="verdict ${s.verdict === '비슷' ? 'verdict-even' : s.verdict.startsWith('Graviton') ? 'verdict-left' : 'verdict-right'}">${s.verdict}</span></td></tr>`).join('')}</tbody></table></div>`;
  fill('band-note', bandNote(AT));
  const fam8 = AT.families.find((f) => f[0].name === 'c8g.xlarge');
  const recs = [
    `서울 리전에서 Graviton5를 쓸 수 있다면 <strong>c9g</strong>를 기본으로 권고합니다. 같은 세션 기준 c8i 대비 처리량 ${x(rm9.perf)}, 가격 대비 성능 ${x(rm9.ppd)}이고 PetClinic 기동도 가장 빠릅니다.`,
    `8세대 안에서 고른다면 <strong>c8i</strong>(또는 같은 처리량에 약 5% 저렴한 c8i-flex)를 권고합니다. c8g / c8i 가격 대비 성능은 같은 세션 재측정 ${x(rm8.ppd)}, JVM 기본값 ${x(sd8.ppd)}이고 처리량은 c8i가 높습니다.`,
    'C2 전용 플래그(<code>-XX:-TieredCompilation</code>)는 Graviton의 처리량을 조금 올리지만(§10) 8세대 판정을 뒤집을 만큼은 아니고, 기동 시간을 늘립니다. 플래그를 바꾸기 전에 실제 서비스로 처리량과 기동 시간을 함께 측정하십시오.',
    `Graviton2/3(c6g, c7g)에서 운영 중이라면 교체 효과가 큽니다. c7g → c8g만으로 가격 대비 성능이 ${pct(up_g.ppd - 1)} 좋아집니다.`,
    `메모리가 많이 필요하지 않다면 C 패밀리가 유리합니다. 같은 Graviton4에서 m8g는 ${x(fam8[1].ppd)}, r8g는 ${x(fam8[2].ppd)}입니다(c8g = 1.00배).`,
    '8세대 Intel이 필요하면 flex를 먼저 검토하십시오. 처리량은 같고 가격이 약 5% 낮습니다. 다만 장시간 지속 부하 특성(부록 A)을 확인하십시오.',
    `5세대 AMD(c5a/m5a/r5a)는 같은 세대 Intel보다 약 10% 저렴하지만 가격 대비 성능이 ${AT.amd_pairs.map((q) => `${short(q.left)} ${x(q.ppd)}`).join(', ')}로 모든 패밀리에서 뒤지므로 신규 배치에서 제외합니다.`,
    '이 결과는 xlarge, 고정 문자열 응답, wrk 2스레드 조건입니다. 인스턴스 크기, 엔드포인트 구성(JSON·DB·락 경합), JVM 프로파일이 다르면 결론이 바뀔 수 있으므로 실제 요청 구성으로 다시 측정한 뒤 결정합니다. Savings Plans·Spot 가격을 쓸 때도 같은 방식으로 다시 계산해야 합니다.',
  ];
  fill('recommendations', `<ul class="recs">${recs.map((r) => `<li>${r}</li>`).join('')}</ul>`);

  // ---------- 부록 ----------
  handles.push(timeseriesSection(slot('timeseries'), envelope?.timeseries, rows));
  handles.push(resultTable(slot('table'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => badge(v) },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'peak.value', label: '최대 처리량', fmt },
    { field: 'peak.cv', label: 'CV (%)', fmt: (v) => fmt(v, 1) },
    { field: 'peak_p99_ms.value', label: 'p99 (ms)', fmt: (v) => fmt(v, 2) },
    { field: 'cold.value', label: '기동 (s)', fmt: (v) => fmt(v, 2) },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(4)}` },
  ]));
  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}

function timeseriesSection(hostEl, timeseries, rows) {
  const metrics = [
    { key: 'throughput', label: '처리량', unit: 'req/s', yTitle: 'req/s', digits: 0 },
    { key: 'lat_avg_ms', label: '평균 지연', unit: 'ms', yTitle: 'ms', digits: 2 },
    { key: 'lat_p99_ms', label: 'P99 지연', unit: 'ms', yTitle: 'ms', digits: 2 },
  ];
  hostEl.innerHTML = `
    <p class="description">Run 2, 60개 샘플(10초 간격, 600초)의 시계열 포인트 통계입니다. 5회 반복 평균이 아닙니다.</p>
    <div class="tab-buttons timeseries-tabs">
      ${metrics.map((metric, i) => `<button class="tab-btn${i === 0 ? ' active' : ''}" data-metric="${metric.key}">${metric.label}</button>`).join('')}
    </div>
    <div class="chart-container tall"><canvas></canvas></div>
    <div class="timeseries-stats"></div>
  `;

  const canvas = hostEl.querySelector('canvas');
  const statsEl = hostEl.querySelector('.timeseries-stats');
  const rowByName = new Map(rows.map((r) => [r.name, r]));
  const interval = timeseries?.interval_s || 10;
  const pointCount = timeseries?.points || 60;
  const labels = Array.from({ length: pointCount }, (_, i) => (i + 1) * interval);
  let chart = null;

  function seriesEntries() {
    return Object.entries(timeseries?.series || {});
  }

  function stats(values) {
    const nums = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
    if (!nums.length) return { mean: null, min: null, max: null, cv: null };
    const mean = nums.reduce((sum, v) => sum + v, 0) / nums.length;
    const variance = nums.reduce((sum, v) => sum + (v - mean) ** 2, 0) / nums.length;
    const stdev = Math.sqrt(variance);
    return {
      mean,
      min: Math.min(...nums),
      max: Math.max(...nums),
      cv: mean ? (stdev / mean) * 100 : null,
    };
  }

  function renderStats(metric) {
    const rowsHtml = seriesEntries().map(([instanceName, series]) => {
      const s = stats(series[metric.key] || []);
      return `
        <tr>
          <td><strong>${instanceName}</strong></td>
          <td>${fmt(s.mean, metric.digits)}</td>
          <td>${fmt(s.min, metric.digits)}</td>
          <td>${fmt(s.max, metric.digits)}</td>
          <td>${fmt(s.cv, 1)}</td>
        </tr>
      `;
    }).join('');

    statsEl.innerHTML = `
      <table>
        <thead>
          <tr><th>인스턴스</th><th>평균</th><th>최소</th><th>최대</th><th>CV(%)</th></tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    `;
  }

  function draw(metric) {
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: seriesEntries().map(([instanceName, series]) => {
          const row = rowByName.get(instanceName);
          const color = archColor(row?.arch, 1);
          return {
            label: instanceName,
            data: series[metric.key] || [],
            borderColor: color,
            backgroundColor: archColor(row?.arch, 0.12),
            borderWidth: 2,
            borderDash: instanceName.includes('-flex') ? [] : [5, 5],
            fill: false,
            pointRadius: 0,
            pointHoverRadius: 3,
            tension: 0.25,
          };
        }),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmt(ctx.raw, metric.digits)} ${metric.unit}`,
            },
          },
        },
        scales: {
          x: { title: { display: true, text: 'Elapsed seconds' } },
          y: { beginAtZero: true, title: { display: true, text: metric.yTitle } },
        },
      },
    });
    renderStats(metric);
  }

  draw(metrics[0]);
  const listeners = [];
  hostEl.querySelectorAll('.tab-btn').forEach((btn) => {
    const onClick = () => {
      const metric = metrics.find((m) => m.key === btn.dataset.metric) || metrics[0];
      hostEl.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      draw(metric);
    };
    btn.addEventListener('click', onClick);
    listeners.push([btn, onClick]);
  });

  return { destroy() { if (chart) chart.destroy(); listeners.forEach(([el, fn]) => el.removeEventListener('click', fn)); } };
}
