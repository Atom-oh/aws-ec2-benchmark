#!/usr/bin/env python3
import os, re, glob
from collections import defaultdict

RESULTS_DIR = '/home/ec2-user/benchmark/results/redis'

# Pricing
PRICING = {
    "c5.xlarge": 0.192, "c5a.xlarge": 0.172, "c5d.xlarge": 0.218, "c5n.xlarge": 0.242,
    "m5.xlarge": 0.214, "m5a.xlarge": 0.192, "m5ad.xlarge": 0.232, "m5d.xlarge": 0.254, "m5zn.xlarge": 0.413,
    "r5.xlarge": 0.282, "r5a.xlarge": 0.252, "r5ad.xlarge": 0.292, "r5b.xlarge": 0.336, "r5d.xlarge": 0.322, "r5dn.xlarge": 0.376, "r5n.xlarge": 0.334,
    "c6i.xlarge": 0.192, "c6id.xlarge": 0.242, "c6in.xlarge": 0.254, "m6i.xlarge": 0.214, "m6id.xlarge": 0.268, "m6idn.xlarge": 0.322, "m6in.xlarge": 0.268,
    "r6i.xlarge": 0.282, "r6id.xlarge": 0.336, "c7i.xlarge": 0.202, "c7i-flex.xlarge": 0.162, "m7i.xlarge": 0.226, "m7i-flex.xlarge": 0.181, "r7i.xlarge": 0.298,
    "c8i.xlarge": 0.212, "c8i-flex.xlarge": 0.170, "m8i.xlarge": 0.237, "r8i.xlarge": 0.313, "r8i-flex.xlarge": 0.250,
    "c6g.xlarge": 0.154, "c6gd.xlarge": 0.194, "c6gn.xlarge": 0.194, "m6g.xlarge": 0.172, "m6gd.xlarge": 0.206, "r6g.xlarge": 0.226, "r6gd.xlarge": 0.260,
    "c7g.xlarge": 0.163, "c7gd.xlarge": 0.206, "m7g.xlarge": 0.183, "m7gd.xlarge": 0.226, "r7g.xlarge": 0.240, "r7gd.xlarge": 0.283,
    "c8g.xlarge": 0.172, "m8g.xlarge": 0.193, "r8g.xlarge": 0.253,
}

def parse_log(filepath):
    with open(filepath) as f:
        content = f.read()

    results = {}
    # Standard benchmark pattern: "SET: 40650.41 requests per second"
    patterns = ['SET', 'GET', 'INCR', 'LPUSH', 'LPOP']

    # Find Pipeline section
    pipeline_start = content.find('Pipeline Benchmark')
    standard = content[:pipeline_start] if pipeline_start > 0 else content
    pipeline = content[pipeline_start:] if pipeline_start > 0 else ''

    for p in patterns:
        match = re.search(rf'^\s*{p}: ([\d.]+) requests per second', standard, re.MULTILINE)
        results[f'std_{p.lower()}'] = float(match.group(1)) if match else 0

    # Pipeline SET
    match = re.search(r'^\s*SET: ([\d.]+) requests per second', pipeline, re.MULTILINE)
    results['pipe_set'] = float(match.group(1)) if match else 0

    return results

# Collect all data
data = defaultdict(list)
for inst_dir in sorted(glob.glob(f'{RESULTS_DIR}/*/')):
    inst = os.path.basename(inst_dir.rstrip('/'))
    if inst == 'summary.csv': continue

    for run in range(1, 6):
        logfile = f'{inst_dir}/run{run}.log'
        if os.path.exists(logfile) and os.path.getsize(logfile) > 100:
            try:
                r = parse_log(logfile)
                data[inst].append(r)
            except: pass

# Generate summary
print("instance,std_set,std_get,std_incr,pipe_set,price,efficiency")
results = []
for inst, runs in sorted(data.items()):
    if not runs: continue
    avg = {k: sum(r.get(k,0) for r in runs)/len(runs) for k in runs[0]}
    price = PRICING.get(inst, 0.2)
    eff = avg.get('std_set', 0) / price / 1000
    results.append((inst, avg, price, eff))
    print(f"{inst},{avg.get('std_set',0):.0f},{avg.get('std_get',0):.0f},{avg.get('std_incr',0):.0f},{avg.get('pipe_set',0):.0f},{price},{eff:.1f}")

# Generate report
results.sort(key=lambda x: -x[1].get('std_set', 0))
with open(f'{RESULTS_DIR}/report.md', 'w') as f:
    f.write("# Redis Benchmark Report\n\n")
    f.write("## Test Configuration\n")
    f.write("- Redis 7.4.7, 50 clients, 100,000 requests\n")
    f.write("- Metrics: SET/GET/INCR ops/sec, Pipeline SET ops/sec\n\n")

    f.write("## Top 10 - SET Performance\n\n")
    f.write("| Rank | Instance | SET (ops/s) | Price ($/hr) | Efficiency |\n")
    f.write("|------|----------|-------------|--------------|------------|\n")
    for i, (inst, avg, price, eff) in enumerate(results[:10], 1):
        f.write(f"| {i} | {inst} | {avg['std_set']:,.0f} | ${price:.3f} | {eff:.1f} |\n")

    f.write("\n## All 51 Instances\n\n")
    f.write("| Rank | Instance | SET | GET | INCR | Pipeline SET | Price | Eff |\n")
    f.write("|------|----------|-----|-----|------|--------------|-------|-----|\n")
    for i, (inst, avg, price, eff) in enumerate(results, 1):
        f.write(f"| {i} | {inst} | {avg['std_set']:,.0f} | {avg['std_get']:,.0f} | {avg['std_incr']:,.0f} | {avg['pipe_set']:,.0f} | ${price:.2f} | {eff:.0f} |\n")

print(f"\nReport saved to {RESULTS_DIR}/report.md")
