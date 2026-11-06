#!/usr/bin/env python3
"""Build qualified comparisons without modifying the authoritative analyzer output."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import statistics
from pathlib import Path
from traffic48_analysis import percentile, expected_offered

BASE='m7i.xlarge'
IDLE_FLAG='boost: incomplete boost sample coverage'
COUNTS=['offered','started','completed','success','http_errors','transport_errors','timeouts','dropped']

def qualify(row, schedule, quality):
    errors=list(row['validation_errors'])
    boost=row.get('sources',{}).get('boost')
    sources=quality.get('sources',{})
    clean=all(sources.get(s,{}).get('outcome')=='COMPLETE' and not sources[s].get('accounting_errors') and not sources[s].get('validation_errors') for s in ['base','boost'])
    idle=bool(boost and schedule and expected_offered(schedule)==0 and boost.get('expected_offered')==0
              and all(boost.get(k)==0 for k in COUNTS) and not boost.get('histogram')
              and row['sources']['base']['accounting_valid'] and clean)
    waived=idle and IDLE_FLAG in errors
    if waived:errors.remove(IDLE_FLAG)
    return dict(qualified=not errors, idle_coverage_waived=waived, remaining_errors=errors)

def pool(rows):
    if not rows:return None
    h=Counter();sec=sum(r['seconds'] for r in rows)
    for r in rows:h.update(r['histogram'])
    totals={k:sum(r[k] for r in rows) for k in COUNTS}
    def mean(k):
        valid=[r for r in rows if r['memory_gc'].get(k) is not None]
        return sum(r['memory_gc'][k]*r['seconds'] for r in valid)/sum(r['seconds'] for r in valid) if valid else None
    def maximum(k):return max((r['memory_gc'][k] for r in rows if r['memory_gc'].get(k) is not None),default=None)
    return dict(phases=len(rows),hours=sec/3600,**totals,success_rps=totals['success']/sec,
                drop_pct=100*totals['dropped']/totals['offered'],error_pct=100*(totals['completed']-totals['success'])/totals['completed'] if totals['completed'] else None,
                p95_ms=percentile(h,.95),p99_ms=percentile(h,.99),cpu_pct=mean('jvm_cpu_mean_pct'),
                heap_mean_gib=(mean('heap_used_mean_bytes') or 0)/2**30,heap_max_gib=(maximum('heap_used_max_bytes') or 0)/2**30,
                gc_pause_max_ms=maximum('gc_log_pause_max_ms'),
                gc_pause_seconds_lower_bound=sum(r['memory_gc'].get('gc_log_pause_total_ms',0) or 0 for r in rows)/1000,
                gc_count_lower_bound=sum(r['memory_gc'].get('gc_log_pause_count',0) or 0 for r in rows),
                original_valid_phases=sum(r['valid'] for r in rows))

def compare(phases,name,mode):
    selected=[p for p in phases if mode=='observed' or all(p['instances'][n]['valid'] if mode=='strict' else p['instances'][n]['qualification']['qualified'] for n in [BASE,name])]
    a=pool([p['instances'][name] for p in selected]);b=pool([p['instances'][BASE] for p in selected])
    return dict(instance=name,mode=mode,phase_names=[p['name'] for p in selected],target=a,baseline=b,
                rps_ratio=a['success_rps']/b['success_rps'] if a else None,
                p99_ratio=a['p99_ms']/b['p99_ms'] if a else None)

def build(run):
    data=json.loads((run/'progress-latest.json').read_text());meta=json.loads((run/'metadata.json').read_text())
    schedules={p['name']:p for p in meta['boost']['phases']};elapsed=0
    for p in data['phases']:
        p['hour_start']=elapsed/3600;elapsed+=p['duration_seconds'];p['hour_end']=elapsed/3600
        for name,row in p['instances'].items():row['qualification']=qualify(row,schedules.get(p['name']),data['quality'][name])
    groups={'all':data['phases'],'day1':[p for p in data['phases'] if p['name'].startswith('d1')],
            'day2_low':[p for p in data['phases'] if p['name'].startswith('d2') and '-l40-' in p['name']],
            'peak90':[p for p in data['phases'] if p['rate_rps']==90000]}
    for seconds in [60,300,900,3600]:groups[f'peak_{seconds}s']=[p for p in groups['peak90'] if p['name'].startswith('d2') and p['duration_seconds']==seconds]
    comparisons={group:{mode:[compare(ps,n,mode) for n in data['quality']] for mode in ['observed','strict','idle_qualified']} for group,ps in groups.items()}
    quality={}
    for n,q in data['quality'].items():
        rows=[p['instances'][n] for p in data['phases']]
        quality[n]=dict(original_valid=sum(r['valid'] for r in rows),idle_qualified=sum(r['qualification']['qualified'] for r in rows),
                        idle_waivers=sum(r['qualification']['idle_coverage_waived'] for r in rows),
                        dispatch_flag_phases=sum(any('dispatch lag >25ms' in f for f in r['validation_errors']) for r in rows),
                        flags=dict(Counter(f for r in rows for f in r['validation_errors'])),
                        outcome=q['outcome'],uptime_resets=q['uptime_resets'],metrics_errors=q['metrics_errors'],
                        source_drop_reasons={s:v.get('drop_reasons') for s,v in q['sources'].items()},
                        recovery_valid=sum(r['valid'] for r in data['recovery'][n]),recovery_total=len(data['recovery'][n]))
    # Every scalar/quality flag is retained in the compact phase view; histogram bins remain in the raw archive.
    phases=[]
    for p in data['phases']:
        item={k:v for k,v in p.items() if k!='instances'};item['instances']={}
        for n,r in p['instances'].items():
            item['instances'][n]={k:v for k,v in r.items() if k not in ['histogram','sources','coverage','source_coverage','cpu_coverage','uptime_coverage']}
        phases.append(item)
    supplemental={}
    flex=run.parents[1]/'springboot-flex48/20261104t0120'
    for n in ['m7i-flex.xlarge','m8i-flex.xlarge']:
        rows=list(csv.DictReader((flex/n/'samples.csv').open()))
        end=max(float(r['elapsed_sec']) for r in rows)
        first=[r for r in rows if float(r['elapsed_sec'])<=3600]
        last=[r for r in rows if float(r['elapsed_sec'])>end-1800]
        early=statistics.mean(float(r['probe_rps']) for r in first)
        late=statistics.mean(float(r['probe_rps']) for r in last)
        supplemental[n]=dict(samples=len(rows),last_elapsed_seconds=end,status=(flex/n/'status.txt').read_text().strip(),
                             first_hour_samples=len(first),last30_samples=len(last),first_hour_probe_rps_mean=early,last30_probe_rps_mean=late,
                             change_pct=(late/early-1)*100,last30_per_probe_p99_median_ms=statistics.median(float(r['p99_latency_ms']) for r in last))
    source_hash=hashlib.sha256((run/'progress-latest.json').read_bytes()).hexdigest()
    return dict(benchmark='springboot-traffic48',generated='2026-11-06',coverage=len(quality),
                headline={'field':'success_rps','direction':'max','label':'전체 기간 관측 RPS (제약 있음)','unit':'RPS'},
                instances={n:pool([p['instances'][n] for p in data['phases']]) for n in quality},
                notes=['48h execution ended; canonical complete=false and comparison_valid=false remain unchanged.'],
                supplemental_flex48=supplemental,run_id=meta['run_id'],start_epoch=meta['start_epoch'],duration_seconds=elapsed,zone=meta['zone'],
                source_sha256=source_hash,canonical_complete=data['complete'],comparison_valid=data['comparison_valid'],
                metadata={k:v for k,v in meta.items() if k not in ['phases','calibrated','boost']},calibration={k:meta['calibrated'][k] for k in ['low_rps','capacity_rps','peak_rps','method']},
                phases=phases,comparisons=comparisons,quality=quality,recovery=data['recovery'],latency_spikes=data['latency_spikes'])

def table(rows):
    lines=['| 인스턴스 | 구간 / 시간 | 성공 RPS | m7i 대비 | p99 ms | p99 배수 | 미발생 % |', '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        a=r['target']
        if not a:lines.append(f"| {r['instance']} | 0 / 0h | — | — | — | — | — |");continue
        lines.append(f"| {r['instance']} | {a['phases']} / {a['hours']:.2f}h | {a['success_rps']:,.0f} | {r['rps_ratio']:.3f}× | {a['p99_ms']:.3f} | {r['p99_ratio']:.3f}× | {a['drop_pct']:.4f} |")
    return '\n'.join(lines)

def write(data,out,site):
    out.mkdir(parents=True,exist_ok=True);site.parent.mkdir(parents=True,exist_ok=True)
    encoded=json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n'
    site.write_text(encoded)
    with (out/'phases.csv').open('w') as f:
        fields=['phase','instance','hour_start','hour_end','target_rps','original_valid','idle_qualified','idle_coverage_waived','success_rps','p95_ms','p99_ms','offered','started','completed','success','dropped','http_errors','transport_errors','timeouts','cpu_pct','heap_mean_bytes','heap_max_bytes','gc_pause_total_ms_lower_bound','gc_pause_max_ms','gc_coverage_estimate','client_cpu_pct','max_dispatch_lag_ms','original_flags','remaining_flags']
        w=csv.DictWriter(f,fields,lineterminator="\n");w.writeheader()
        for p in data['phases']:
            for n,r in p['instances'].items():
                m=r['memory_gc'];q=r['qualification']
                row=dict(phase=p['name'],instance=n,hour_start=p['hour_start'],hour_end=p['hour_end'],target_rps=p['rate_rps'],original_valid=r['valid'],idle_qualified=q['qualified'],idle_coverage_waived=q['idle_coverage_waived'],cpu_pct=m['jvm_cpu_mean_pct'],heap_mean_bytes=m['heap_used_mean_bytes'],heap_max_bytes=m['heap_used_max_bytes'],gc_pause_total_ms_lower_bound=m['gc_log_pause_total_ms'],gc_pause_max_ms=m['gc_log_pause_max_ms'],gc_coverage_estimate=m['gc_log_coverage_fraction'],original_flags='; '.join(r['validation_errors']),remaining_flags='; '.join(q['remaining_errors']))
                row.update({k:r[k] for k in COUNTS+['success_rps','p95_ms','p99_ms','client_cpu_pct','max_dispatch_lag_ms']});w.writerow(row)
    with (out/'comparisons.csv').open('w') as f:
        fields=['group','mode','instance','phases','hours','success_rps','baseline_rps','rps_ratio','p99_ms','baseline_p99_ms','p99_ratio','drop_pct','phase_names'];w=csv.DictWriter(f,fields,lineterminator="\n");w.writeheader()
        for group,modes in data['comparisons'].items():
            for mode,rows in modes.items():
                for r in rows:
                    a=r['target'] or {};b=r['baseline'] or {}
                    w.writerow(dict(group=group,mode=mode,instance=r['instance'],phases=a.get('phases',0),hours=a.get('hours',0),success_rps=a.get('success_rps'),baseline_rps=b.get('success_rps'),rps_ratio=r['rps_ratio'],p99_ms=a.get('p99_ms'),baseline_p99_ms=b.get('p99_ms'),p99_ratio=r['p99_ratio'],drop_pct=a.get('drop_pct'),phase_names=';'.join(r['phase_names'])))
    (out/'tables.md').write_text('# 비교표 해석\n\nobserved: 품질 제약을 포함한 전체 관측. strict: 원래 판정 통과. idle_qualified: 예정 도착 0인 boost 휴지 coverage 예외만 적용. 후자의 두 mode는 대상과 m7i가 모두 통과한 구간의 교집합이다. 행마다 선택 구간과 m7i 분모가 달라 행 간 직접 순위화하지 않는다. p99는 히스토그램 합산값이다. [전체 설명](README.md), [각 행의 기준 수치·구간 목록](comparisons.csv).\n\n'+'\n\n'.join(f'## {g} / {m}\n\n'+table(rows) for g,modes in data['comparisons'].items() for m,rows in modes.items())+'\n')
    (out/'quality.json').write_text(json.dumps(data['quality'],ensure_ascii=False,indent=2)+'\n')
    template=(Path(__file__).resolve().parents[1]/'docs/springboot-traffic48-report-template.md').read_text()
    for group,modes in data['comparisons'].items():
        for mode,rows in modes.items():template=template.replace('{{table:'+group+':'+mode+'}}',table(rows))
    quality=['| 인스턴스 | 원래 통과 /96 | 휴지 예외 후 통과 /96 | dispatch >25ms 구간 | client CPU ≥80% 구간 |','|---|---:|---:|---:|---:|']
    for n,q in data['quality'].items():quality.append(f"| {n} | {q['original_valid']} | {q['idle_qualified']} | {q['dispatch_flag_phases']} | {q['flags'].get('client CPU >=80%',0)} |")
    gc=['| 인스턴스 | 평균 / 최대 힙 GiB | 관측 GC 횟수 ≥ | 관측 GC 정지 합계 ≥초 | 관측 최대 pause ms |','|---|---:|---:|---:|---:|']
    for n,a in data['instances'].items():gc.append(f"| {n} | {a['heap_mean_gib']:.2f} / {a['heap_max_gib']:.2f} | {a['gc_count_lower_bound']:,} | {a['gc_pause_seconds_lower_bound']:.2f} | {a['gc_pause_max_ms']:.3f} |")
    appendix=['| 인스턴스 | 표본 / 마지막 경과시간 | 첫 1시간 probe 평균 RPS | 마지막 약 30분 probe 평균 RPS | 변화 | 마지막 probe p99 중앙값 ms |','|---|---:|---:|---:|---:|---:|']
    for n,a in data['supplemental_flex48'].items():appendix.append(f"| {n} | {a['samples']} / {a['last_elapsed_seconds']/3600:.2f}h | {a['first_hour_probe_rps_mean']:,.0f} | {a['last30_probe_rps_mean']:,.0f} | {a['change_pct']:.1f}% | {a['last30_per_probe_p99_median_ms']:.3f} |")
    template=template.replace('{{supplemental}}','\n'.join(appendix))
    manifest=json.loads((out/'raw/manifest.json').read_text())
    archive=f"원본 **{manifest['file_count']}개 파일 / {manifest['raw_bytes']:,} bytes**, 압축 **{manifest['compressed_bytes']:,} bytes / {len(manifest['parts'])}개 조각**(조각당 최대 48 MiB)."
    template=template.replace('{{quality}}','\n'.join(quality)).replace('{{gc}}','\n'.join(gc)).replace('{{archive}}',archive).replace('{{source}}','원본 최종 집계 SHA-256: `'+data['source_sha256']+'`.')
    (out/'README.md').write_text(template)
    print(json.dumps({'source_sha256':data['source_sha256'],'phases':len(data['phases']),'quality':data['quality']},ensure_ascii=False))

def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--output',type=Path,default=Path('reports/traffic48-final'));p.add_argument('--site',type=Path,default=Path('site/data/springboot-traffic48.json'));a=p.parse_args();write(build(a.run),a.output,a.site)
if __name__=='__main__':main()
