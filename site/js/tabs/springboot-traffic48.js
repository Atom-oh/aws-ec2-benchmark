import { fmt } from '../shared.js';

const COLORS = ['#2563eb','#9333ea','#0891b2','#db2777','#059669','#d97706'];
const REPO = 'https://github.com/Atom-oh/aws-ec2-benchmark/blob/report/traffic48-final-raw/reports/traffic48-final/';
const cell = (v,d=3) => v == null ? '—' : fmt(v,d);

export async function render(root,{envelope:e}) {
  const handles=[];
  const group=root.querySelector('[data-select="group"]');
  const mode=root.querySelector('[data-select="mode"]');
  function comparison() {
    const rows=e.comparisons[group.value][mode.value];
    root.querySelector('[data-slot="comparison-note"]').textContent=mode.value==='observed'
      ? '품질 플래그를 포함한 전체 관측입니다. 서버 성능의 확정 순위가 아닙니다.'
      : '각 대상과 m7i 양쪽이 판정을 통과한 같은 구간만 합산합니다. 비교 가능한 구간이 없으면 —로 표시합니다.';
    root.querySelector('[data-slot="comparison"]').innerHTML=`<div class="table-scroll" tabindex="0"><table><thead><tr><th>인스턴스</th><th>구간 / 시간</th><th>성공 RPS</th><th>m7i 대비</th><th>p99 ms</th><th>p99 배수</th><th>미발생 %</th></tr></thead><tbody>${rows.map(r=>{
      const a=r.target;
      return `<tr><td>${r.instance}</td><td>${a ? `${a.phases} / ${cell(a.hours,2)}h` : '0 / 0h'}</td><td>${cell(a?.success_rps,0)}</td><td>${cell(r.rps_ratio)}</td><td>${cell(a?.p99_ms)}</td><td>${cell(r.p99_ratio)}</td><td>${cell(a?.drop_pct,4)}</td></tr>`;
    }).join('')}</tbody></table></div>`;
  }
  group.addEventListener('change',comparison);mode.addEventListener('change',comparison);comparison();
  handles.push({destroy(){group.removeEventListener('change',comparison);mode.removeEventListener('change',comparison);}});
  const metrics=[
    ['성공 처리량 · RPS',r=>r.success_rps],
    ['p99 · ms (예정 시각부터 완료)',r=>r.p99_ms],
    ['JVM CPU · % (수집값)',r=>r.memory_gc.jvm_cpu_mean_pct],
    ['미발생 요청 · %',r=>100*r.dropped/r.offered],
    ['관측 최대 힙 · GiB',r=>r.memory_gc.heap_used_max_bytes/2**30],
    ['관측 최대 GC pause · ms',r=>r.memory_gc.gc_log_pause_max_ms],
  ];
  const chartHost=root.querySelector('[data-slot="charts"]');
  for(const [title,value] of metrics){
    const section=document.createElement('div');section.innerHTML=`<h3>${title}</h3><div style="height:300px;position:relative"><canvas aria-label="${title}"></canvas></div>`;chartHost.append(section);
    const datasets=Object.keys(e.instances).map((n,i)=>({label:n,borderColor:COLORS[i],backgroundColor:COLORS[i],borderWidth:n==='m7i.xlarge'?3:1.5,pointRadius:2,tension:0,
      data:e.phases.map(p=>({x:p.hour_end,y:value(p.instances[n]),flags:p.instances[n].validation_errors,phase:p.name})),spanGaps:false}));
    if(title.startsWith('성공'))datasets.push({label:'목표 RPS (구간 끝값)',borderColor:'#64748b',borderDash:[5,4],pointRadius:0,data:e.phases.map(p=>({x:p.hour_end,y:p.rate_rps,phase:p.name,flags:[]}))});
    handles.push(new Chart(section.querySelector('canvas'),{type:'line',data:{datasets},options:{responsive:true,maintainAspectRatio:false,animation:false,
      scales:{x:{type:'linear',min:0,max:48,title:{display:true,text:'측정 시작 후 시간 · 구간 종료'}},y:{beginAtZero:true}},
      plugins:{legend:{position:'bottom'},tooltip:{callbacks:{afterLabel:ctx=>[ctx.raw.phase,...(ctx.raw.flags.length?ctx.raw.flags:['원래 구간 판정 통과'])]}}}}}));
  }
  root.querySelector('[data-slot="quality"]').innerHTML=`<div class="table-scroll" tabindex="0"><table><thead><tr><th>인스턴스</th><th>원래 통과 /96</th><th>휴지 예외 후 /96</th><th>JVM 재시작 관측</th></tr></thead><tbody>${Object.entries(e.quality).map(([n,q])=>`<tr><td>${n}</td><td>${q.original_valid}</td><td>${q.idle_qualified}</td><td>${q.uptime_resets}</td></tr>`).join('')}</tbody></table></div>`;
  root.querySelector('[data-slot="downloads"]').innerHTML=[['README.md','전체 리포트'],['phases.csv','구간 CSV'],['comparisons.csv','비교 CSV'],['tables.md','전체 비교표'],['raw/manifest.json','원본 체크섬'],['raw','원본 조각'],['timeseries.png','차트 PNG']].map(([p,n])=>`<a href="${REPO+p}">${n}</a>`).join(' · ');
  return {destroy(){handles.forEach(h=>h.destroy());}};
}
