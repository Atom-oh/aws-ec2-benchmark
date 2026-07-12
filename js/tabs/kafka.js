// Kafka — 이미 데이터 주도(json envelope)인 레거시 리포트를 표준 컴포넌트+bespoke SLOT A로 이식.
// SLOT A: 3-phase 구조(베이스라인/§9 포화+코덱/§10 램프) 통째 이식, 레이턴시 커브 다중선택(≤5),
// empty-state 처리. 동적 인사이트 계산은 레거시 renderProduceChart/renderSatSection/renderRampSection의
// 로직을 그대로 포팅(재작성 아님) — computed 패턴의 레퍼런스.
import {
  buildToc, summaryCards, topNBar, metricTabChart, familyChart, genImprovement, priceSection, resultTable, fmt, ARCH_COLOR,
} from '../shared.js';

const CURVE_MAX = 5;

export async function render(root, { rows }) {
  const handles = [];
  const top = [...rows].filter((r) => r.produce_mb_per_sec != null).sort((a, b) => b.produce_mb_per_sec - a.produce_mb_per_sec);
  const bestValue = rows.filter((r) => r.value).sort((a, b) => b.value - a.value)[0];
  const bestConsume = [...rows].filter((r) => r.consume_mb_per_sec != null).sort((a, b) => b.consume_mb_per_sec - a.consume_mb_per_sec)[0];
  const gravitonMedian = median(rows.filter((r) => r.arch === 'graviton').map((r) => r.produce_mb_per_sec).filter((v) => v != null));
  const intelMedian = median(rows.filter((r) => r.arch === 'intel').map((r) => r.produce_mb_per_sec).filter((v) => v != null));

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 produce 처리량', value: top[0].name, detail: `${fmt(top[0].produce_mb_per_sec)} MB/s` },
    { label: '최고 가성비', value: bestValue.name, detail: `${fmt(bestValue.value)} MB/s per $` },
    { label: '최고 consume 처리량', value: bestConsume.name, detail: `${fmt(bestConsume.consume_mb_per_sec)} MB/s` },
    { label: 'Graviton 중앙값 (produce)', value: `${fmt(gravitonMedian)} MB/s`, detail: '' },
    { label: 'Intel 중앙값 (produce)', value: `${fmt(intelMedian)} MB/s`, detail: '' },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="produce-top"]'), rows, {
    metrics: [{ field: 'produce_mb_per_sec', label: 'Produce', unit: 'MB/s', direction: 'max' }],
    n: 54,
  }));
  const gravitonBest = top.find((r) => r.arch === 'graviton');
  root.querySelector('[data-slot="produce-insight"]').innerHTML = `<h4>핵심 인사이트</h4><ul>
    <li><strong>${top[0].name}</strong>가 최고 produce 처리량 (${fmt(top[0].produce_mb_per_sec)} MB/s)</li>
    ${gravitonBest ? `<li>Graviton 최고: <strong>${gravitonBest.name}</strong> (${fmt(gravitonBest.produce_mb_per_sec)} MB/s)</li>` : ''}
  </ul>`;

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'produce_mb_per_sec', label: 'Produce', unit: 'MB/s', direction: 'max' },
    gridMetrics: [
      { field: 'produce_mb_per_sec', label: 'Produce', unit: 'MB/s', direction: 'max' },
      { field: 'consume_mb_per_sec', label: 'Consume', unit: 'MB/s', direction: 'max' },
    ],
  }));

  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), rows, [
    { field: 'produce_mb_per_sec', label: 'Produce', unit: 'MB/s', direction: 'max' },
    { field: 'consume_mb_per_sec', label: 'Consume', unit: 'MB/s', direction: 'max' },
  ]));
  handles.push(familyChart(root.querySelector('[data-slot="family"]'), rows, { field: 'produce_mb_per_sec', unit: 'MB/s' }));

  // RAM 티어별 (8/16/32GB) — 표준 컴포넌트에 없는 그루핑, bespoke
  const ramCanvasHost = root.querySelector('[data-slot="ram"]');
  ramCanvasHost.innerHTML = '<div class="grid-2"><div class="chart-container"><canvas></canvas></div><div class="chart-container"><canvas></canvas></div></div>';
  const [ramProduceCanvas, ramConsumeCanvas] = ramCanvasHost.querySelectorAll('canvas');
  const tiers = [['8GB', 8192], ['16GB', 16384], ['32GB', 32768]];
  const ramProduceChart = new Chart(ramProduceCanvas, barCfg(tiers.map((t) => t[0]), [{
    label: 'produce MB/s', data: tiers.map((t) => median(rows.filter((r) => r.mem_mb === t[1]).map((r) => r.produce_mb_per_sec).filter((v) => v != null))), backgroundColor: '#3b82f6',
  }]));
  const ramConsumeChart = new Chart(ramConsumeCanvas, barCfg(tiers.map((t) => t[0]), [{
    label: 'consume MB/s', data: tiers.map((t) => median(rows.filter((r) => r.mem_mb === t[1]).map((r) => r.consume_mb_per_sec).filter((v) => v != null))), backgroundColor: '#10b981',
  }]));
  handles.push({ destroy() { ramProduceChart.destroy(); ramConsumeChart.destroy(); } });

  handles.push(genImprovement(root.querySelector('[data-slot="improvement"]'), rows, { field: 'produce_mb_per_sec' }));

  handles.push(topNBar(root.querySelector('[data-slot="avoid"]'), rows, {
    metrics: [{ field: 'produce_mb_per_sec', label: 'Produce', unit: 'MB/s', direction: 'max' }],
    n: 10,
    ascending: true,
  }));

  // Phase 2: 포화(saturation) — max.uncompressed 값이 있는 것만
  rows.forEach((r) => {
    r.__sat_mb = r.max?.uncompressed?.produce_mb_per_sec ?? null;
    r.__zstd_ratio = r.max?.zstd?.compression_ratio ?? null;
  });
  const satRows = rows.filter((r) => r.__sat_mb != null);
  const satInsightEl = root.querySelector('[data-slot="sat-insight"]');
  if (!satRows.length) {
    root.querySelector('[data-slot="sat-top"]').innerHTML = '<p style="color:var(--muted);font-style:italic;padding:2rem;text-align:center;">포화(max) 시나리오 데이터 없음</p>';
    satInsightEl.innerHTML = '';
  } else {
    const satTop = [...satRows].sort((a, b) => b.__sat_mb - a.__sat_mb);
    handles.push(topNBar(root.querySelector('[data-slot="sat-top"]'), satRows, {
      metrics: [{ field: '__sat_mb', label: '포화 produce (8-way, uncompressed)', unit: 'MB/s', direction: 'max' }],
      n: 54,
    }));

    const top15 = satTop.slice(0, 15);
    const codecCanvas = root.querySelector('[data-slot="codec-chart"]');
    const codecChart = new Chart(codecCanvas, barCfg(top15.map((r) => r.name), ['uncompressed', 'lz4', 'zstd'].map((codec, i) => ({
      label: codec, data: top15.map((r) => r.max?.[codec]?.produce_mb_per_sec ?? null), backgroundColor: ['#94a3b8', '#3b82f6', '#f59e0b'][i],
    })), { indexAxis: 'x' }));
    handles.push({ destroy() { codecChart.destroy(); } });

    const scaled = [...satRows].filter((r) => r.scaling_8way != null).sort((a, b) => b.scaling_8way - a.scaling_8way).slice(0, 20);
    const scalingCanvas = root.querySelector('[data-slot="scaling-chart"]');
    const scalingChart = new Chart(scalingCanvas, barCfg(scaled.map((r) => r.name), [{ label: '스케일링(x)', data: scaled.map((r) => r.scaling_8way), backgroundColor: '#8b5cf6' }]));
    handles.push({ destroy() { scalingChart.destroy(); } });

    const bestSat = satTop[0];
    const bestScale = scaled[0];
    const STORAGE_CAP_MB = 2000;
    const nearCap = satRows.filter((r) => r.__sat_mb >= STORAGE_CAP_MB * 0.9).length;
    satInsightEl.innerHTML = `<h4>포화 시나리오 핵심 인사이트</h4><ul>
      <li>8-way 병렬(무압축) 최고 처리량: <strong>${bestSat.name}</strong> (${fmt(bestSat.__sat_mb)} MB/s, 베이스라인 대비 ${fmt(bestSat.scaling_8way, 2)}x)</li>
      ${bestScale ? `<li>병렬화 여력이 가장 큰 인스턴스: <strong>${bestScale.name}</strong> (${fmt(bestScale.scaling_8way, 2)}x 스케일링)</li>` : ''}
      <li>zstd는 압축률이 lz4보다 높지만 브로커 CPU 비용도 커서 produce MB/s가 하락 — 압축률과 처리량은 트레이드오프.</li>
      ${nearCap > 0
        ? `<li><strong>⚠️ 상위 ${nearCap}개 인스턴스가 gp3 볼륨 캡(${STORAGE_CAP_MB}MB/s)의 90% 이상에 몰려있음</strong></li>`
        : `<li>전 인스턴스가 gp3 볼륨 캡(${STORAGE_CAP_MB}MB/s)의 90%에도 못 미침 — 스토리지가 병목이 아님.</li>`}
    </ul>`;
  }

  // Phase 3: 램프업
  const rampRows = rows.filter((r) => r.ramp && r.ramp.curve && r.ramp.curve.length);
  const rampInsightEl = root.querySelector('[data-slot="ramp-insight"]');
  if (!rampRows.length) {
    root.querySelector('[data-slot="ramp-chart"]').closest('.chart-container').outerHTML = '<p style="color:var(--muted);font-style:italic;padding:2rem;text-align:center;">램프업(Phase 3) 데이터 없음</p>';
    rampInsightEl.innerHTML = '';
  } else {
    const bySat = [...rampRows].filter((r) => r.ramp.saturation_mb_per_sec != null).sort((a, b) => b.ramp.saturation_mb_per_sec - a.ramp.saturation_mb_per_sec);
    const rampCanvas = root.querySelector('[data-slot="ramp-chart"]');
    const rampChart = new Chart(rampCanvas, barCfg(bySat.map((r) => r.name), [{
      label: '포화점 처리량 (MB/s)', data: bySat.map((r) => r.ramp.saturation_mb_per_sec), backgroundColor: bySat.map((r) => ARCH_COLOR[r.arch] || '#94a3b8'),
    }], { indexAxis: 'y' }));
    handles.push({ destroy() { rampChart.destroy(); } });

    let curveSelection = bySat.slice(0, CURVE_MAX).map((r) => r.name);
    const curveCanvas = root.querySelector('[data-slot="curve-chart"]');
    const selectEl = root.querySelector('[data-slot="curve-select"]');
    const countEl = root.querySelector('[data-slot="curve-count"]');
    let curveChart = null;

    function drawCurve() {
      const chosen = bySat.filter((r) => curveSelection.includes(r.name));
      countEl.textContent = `${chosen.length} / ${CURVE_MAX}개 선택`;
      if (curveChart) { curveChart.destroy(); curveChart = null; }
      if (!chosen.length) return;
      const palette = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];
      curveChart = new Chart(curveCanvas, {
        type: 'line',
        data: { datasets: chosen.map((r, i) => ({
          label: r.name, data: r.ramp.curve.map((s) => ({ x: s.achieved_mb, y: s.lat_p99_ms })),
          borderColor: palette[i % palette.length], backgroundColor: palette[i % palette.length], showLine: true, tension: 0.2,
        })) },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { x: { type: 'linear', title: { display: true, text: '처리량 (MB/s)' } }, y: { title: { display: true, text: 'p99 지연 (ms)' } } },
        },
      });
    }

    selectEl.innerHTML = bySat.map((r) => `<option value="${r.name}">${r.name} — ${fmt(r.ramp.saturation_mb_per_sec)} MB/s</option>`).join('');
    [...selectEl.options].forEach((o) => { o.selected = curveSelection.includes(o.value); });
    const onSelectChange = () => {
      let chosen = [...selectEl.selectedOptions].map((o) => o.value);
      if (chosen.length > CURVE_MAX) {
        chosen = chosen.slice(0, CURVE_MAX);
        [...selectEl.options].forEach((o) => { o.selected = chosen.includes(o.value); });
      }
      curveSelection = chosen;
      drawCurve();
    };
    selectEl.addEventListener('change', onSelectChange);
    drawCurve();
    handles.push({ destroy() { selectEl.removeEventListener('change', onSelectChange); if (curveChart) curveChart.destroy(); } });

    const reached = rampRows.filter((r) => r.ramp.saturation_reached === 'yes').length;
    const best = bySat[0];
    rampInsightEl.innerHTML = `<h4>램프업 핵심 인사이트</h4><ul>
      <li>측정된 ${rampRows.length}개 인스턴스 중 <strong>${reached}개</strong>가 테스트 범위(baseline의 160%) 안에서 실제 포화점에 도달함.</li>
      ${best ? `<li>포화점 최고: <strong>${best.name}</strong> (${fmt(best.ramp.saturation_mb_per_sec)} MB/s, p99 ${fmt(best.ramp.saturation_lat_p99_ms)}ms)</li>` : ''}
      <li>⚠️ 1회 측정 — run-to-run 변동은 베이스라인/§9의 5회 반복 결과보다 클 수 있음.</li>
    </ul>`;
  }

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'mem_mb', label: 'RAM(MB)', fmt: fmt },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
    { field: 'produce_mb_per_sec', label: 'Produce MB/s', fmt: fmt },
    { field: 'produce_lat_p99_ms', label: 'p99(ms)', fmt: fmt },
    { field: 'consume_mb_per_sec', label: 'Consume MB/s', fmt: fmt },
    { field: 'value', label: 'Value', fmt: fmt },
    { field: '__sat_mb', label: '포화 MB/s(8-way)', fmt: fmt },
  ]));

  // 결론 (computed)
  const bestSatOverall = [...rows].filter((r) => r.__sat_mb).sort((a, b) => b.__sat_mb - a.__sat_mb)[0];
  root.querySelector('[data-slot="conclusion"]').innerHTML = `<h4>핵심 시사점</h4><ul>
    <li>베이스라인(싱글) 최고 처리량: <strong>${top[0].name}</strong> (${fmt(top[0].produce_mb_per_sec)} MB/s produce)</li>
    <li>최고 가성비: <strong>${bestValue.name}</strong> (${fmt(bestValue.value)} MB/s per $)</li>
    ${bestSatOverall ? `<li>포화(8-way, 무압축) 최고 처리량: <strong>${bestSatOverall.name}</strong> (${fmt(bestSatOverall.__sat_mb)} MB/s)</li>` : ''}
    <li>네트워크가 결과에 포함되므로 순수 CPU/메모리 비교가 필요하면 iperf3 탭을 함께 참고할 것.</li>
  </ul>`;

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}

function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function barCfg(labels, datasets, opts = {}) {
  return {
    type: 'bar',
    data: { labels, datasets },
    options: Object.assign({
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: datasets.length > 1 } },
      scales: { x: { beginAtZero: true } },
      indexAxis: 'y',
    }, opts),
  };
}
