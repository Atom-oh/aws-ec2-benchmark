#!/usr/bin/env python3
"""Export standalone report figures from the same published derived data."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def main():
    root=Path(__file__).resolve().parents[1]
    d=json.loads((root/'site/data/springboot-traffic48.json').read_text())
    fig,axes=plt.subplots(3,2,figsize=(16,13),sharex=True,layout='constrained')
    metrics=[('Success RPS',lambda r:r['success_rps']),('P99 ms (scheduled to complete)',lambda r:r['p99_ms']),('JVM CPU % (reported)',lambda r:r['memory_gc']['jvm_cpu_mean_pct']),('Dropped / offered %',lambda r:100*r['dropped']/r['offered']),('Observed max heap GiB',lambda r:r['memory_gc']['heap_used_max_bytes']/2**30),('Observed max GC pause ms',lambda r:r['memory_gc']['gc_log_pause_max_ms'])]
    for ax,(title,value) in zip(axes.flat,metrics):
        for name in d['instances']:
            ax.plot([p['hour_end'] for p in d['phases']],[value(p['instances'][name]) for p in d['phases']],label=name,linewidth=2 if name=='m7i.xlarge' else 1,marker='.',markersize=3)
        if title=='Success RPS':ax.plot([p['hour_end'] for p in d['phases']],[p['rate_rps'] for p in d['phases']],label='Target (phase end)',color='gray',linestyle='--',linewidth=1)
        ax.set(title=title,xlim=(0,48),ylim=(0,None));ax.grid(alpha=.2);ax.axvline(24,color='gray',linestyle=':',linewidth=1)
    for ax in axes[-1]:ax.set_xlabel('Hours since measurement start; points summarize phases ending here')
    axes[0,0].legend(fontsize=8,ncol=2)
    fig.suptitle('48-hour traffic experiment: descriptive observations, quality flags included\nSingle host/type; client limits confound peak attribution; GC retention is estimated',fontsize=14)
    out=root/'reports/traffic48-final'
    for suffix in ['png','svg']:fig.savefig(out/f'timeseries.{suffix}',dpi=160)
    svg=out/'timeseries.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    plt.close(fig)
if __name__=='__main__':main()
