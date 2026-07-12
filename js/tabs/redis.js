// redis 고유 SLOT B: 인스턴스 상세 모달(테이블 행 클릭 → 5-run 통계 + CV 해석).
// GET 효율은 레거시 리포트의 조작값(SET×1.1/1.05)을 폐기하고 이 파서의 실측 get_rps를 사용 —
// 데이터 스키마 설계에서 결정한 "드롭이 아닌 실측 교체".
import {
  buildToc, summaryCards, topNBar, metricTabChart, familyChart, genImprovement, priceSection, resultTable, fmt,
} from '../shared.js';

export async function render(root, { rows }) {
  const handles = [];
  const topSet = [...rows].filter((r) => r.set_rps != null).sort((a, b) => b.set_rps - a.set_rps)[0];
  const topGet = [...rows].filter((r) => r.get_rps != null).sort((a, b) => b.get_rps - a.get_rps)[0];
  const topEff = rows.filter((r) => r.set_rps != null && r.price).map((r) => ({ ...r, __eff: r.set_rps / r.price }))
    .sort((a, b) => b.__eff - a.__eff)[0];

  handles.push(summaryCards(root.querySelector('[data-slot="summary-cards"]'), [
    { label: '최고 SET 처리량', value: topSet.name, detail: `${fmt(topSet.set_rps)} ops/s` },
    { label: '최고 GET 처리량', value: topGet.name, detail: `${fmt(topGet.get_rps)} ops/s` },
    { label: '최고 가성비', value: topEff.name, detail: `${fmt(topEff.__eff)} ops/s per $/hr` },
  ]));

  handles.push(topNBar(root.querySelector('[data-slot="top20"]'), rows, {
    metrics: [
      { field: 'set_rps', label: 'SET ops/sec', unit: 'ops/s', direction: 'max', icon: '📝' },
      { field: 'get_rps', label: 'GET ops/sec', unit: 'ops/s', direction: 'max', icon: '📖' },
    ],
    n: 20,
  }));

  handles.push(metricTabChart(root.querySelector('[data-slot="arch-gen"]'), rows, [
    { field: 'set_rps', label: 'SET ops/sec', unit: 'ops/s', direction: 'max', icon: '📝' },
    { field: 'get_rps', label: 'GET ops/sec', unit: 'ops/s', direction: 'max', icon: '📖' },
  ]));

  handles.push(familyChart(root.querySelector('[data-slot="family"]'), rows, { field: 'set_rps', unit: 'ops/s' }));
  handles.push(genImprovement(root.querySelector('[data-slot="improvement"]'), rows, { field: 'set_rps' }));

  handles.push(priceSection(root.querySelector('[data-slot="price"]'), rows, {
    mainMetric: { field: 'set_rps', label: 'SET ops/sec', unit: 'ops/s', direction: 'max' },
    gridMetrics: [
      { field: 'set_rps', label: 'SET', unit: 'ops/s', direction: 'max' },
      { field: 'get_rps', label: 'GET', unit: 'ops/s', direction: 'max' },
    ],
  }));

  handles.push(topNBar(root.querySelector('[data-slot="avoid"]'), rows, {
    metrics: [{ field: 'set_rps', label: 'SET ops/sec', unit: 'ops/s', direction: 'max' }],
    n: 10,
    ascending: true,
  }));

  // 모달
  const modal = root.querySelector('[data-slot="modal"]');
  const modalTitle = root.querySelector('[data-slot="modal-title"]');
  const modalBody = root.querySelector('[data-slot="modal-body"]');
  function openModal(row) {
    modalTitle.textContent = row.name;
    const setAll = row.set_rps_all || [];
    const getAll = row.get_rps_all || [];
    const cv = setAll.length ? (stdev(setAll) / avg(setAll)) * 100 : null;
    modalBody.innerHTML = `
      <div class="detail-section">
        <h4>SET 처리량 (5회)</h4>
        <div class="detail-grid">
          <div class="detail-item"><div class="label">평균</div><div class="value">${fmt(row.set_rps)}</div></div>
          <div class="detail-item"><div class="label">최대</div><div class="value">${fmt(Math.max(...setAll))}</div></div>
          <div class="detail-item"><div class="label">최소</div><div class="value">${fmt(Math.min(...setAll))}</div></div>
          <div class="detail-item"><div class="label">표준편차</div><div class="value">${fmt(stdev(setAll))}</div></div>
        </div>
        <div style="margin-top:0.75rem;font-size:0.8rem;color:var(--muted);">
          변동 계수: ${cv != null ? cv.toFixed(2) : '—'}% ${cv != null ? (cv < 2 ? '(매우 안정적)' : cv < 5 ? '(안정적)' : '(변동 있음)') : ''}
        </div>
      </div>
      <div class="detail-section">
        <h4>Latency 비교</h4>
        <div class="detail-grid">
          <div class="detail-item"><div class="label">SET Latency</div><div class="value">${row.set_lat_ms != null ? row.set_lat_ms.toFixed(3) : '—'}ms</div></div>
          <div class="detail-item"><div class="label">GET Latency</div><div class="value">${row.get_lat_ms != null ? row.get_lat_ms.toFixed(3) : '—'}ms</div></div>
        </div>
      </div>
      <div class="detail-section">
        <h4>GET 처리량 (5회)</h4>
        <div class="detail-grid">
          <div class="detail-item"><div class="label">평균</div><div class="value">${fmt(row.get_rps)}</div></div>
          <div class="detail-item"><div class="label">최대</div><div class="value">${getAll.length ? fmt(Math.max(...getAll)) : '—'}</div></div>
        </div>
      </div>
    `;
    modal.classList.add('show');
  }
  function closeModal() { modal.classList.remove('show'); }
  const onModalClick = (e) => { if (e.target === modal) closeModal(); };
  const onCloseClick = () => closeModal();
  const onKeydown = (e) => { if (e.key === 'Escape') closeModal(); };
  modal.addEventListener('click', onModalClick);
  root.querySelector('[data-slot="modal-close"]').addEventListener('click', onCloseClick);
  document.addEventListener('keydown', onKeydown);
  handles.push({
    destroy() {
      modal.removeEventListener('click', onModalClick);
      document.removeEventListener('keydown', onKeydown);
    },
  });

  handles.push(resultTable(root.querySelector('[data-slot="table"]'), rows, [
    { field: 'name', label: '인스턴스', fmt: (v) => `<strong>${v}</strong>` },
    { field: 'arch', label: '아키텍처', fmt: (v) => `<span class="badge badge-${v}">${v.toUpperCase()}</span>` },
    { field: 'gen', label: '세대', fmt: (v) => `${v}세대` },
    { field: 'set_rps', label: 'SET ops/s', fmt: fmt },
    { field: 'get_rps', label: 'GET ops/s', fmt: fmt },
    { field: 'set_lat_ms', label: 'SET Lat (ms)', fmt: (v) => fmt(v, 3) },
    { field: 'get_lat_ms', label: 'GET Lat (ms)', fmt: (v) => fmt(v, 3) },
    { field: 'price', label: '$/hr', fmt: (v) => `$${v.toFixed(3)}` },
  ], { onRowClick: openModal }));

  handles.push(buildToc(root));

  return { destroy() { handles.forEach((h) => h && h.destroy && h.destroy()); } };
}

function avg(arr) { return arr.reduce((a, b) => a + b, 0) / arr.length; }
function stdev(arr) {
  const m = avg(arr);
  return Math.sqrt(arr.reduce((s, v) => s + (v - m) ** 2, 0) / arr.length);
}
