#!/usr/bin/env python3
import os, re, glob
from collections import defaultdict

RESULTS_DIR = '/home/ec2-user/benchmark/results/nginx'

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

    # Extract Requests/sec for different thread counts
    results = {}
    # Pattern: "Requests/sec:  84615.33"
    matches = re.findall(r'Requests/sec:\s+([\d.]+)', content)
    if len(matches) >= 3:
        results['rps_2t'] = float(matches[0])  # 2 threads
        results['rps_4t'] = float(matches[1])  # 4 threads
        results['rps_8t'] = float(matches[2])  # 8 threads

    # Extract latency for 4 threads test
    lat_match = re.search(r'4 threads.*?Latency\s+([\d.]+)(\w+)', content, re.DOTALL)
    if lat_match:
        val, unit = lat_match.groups()
        results['latency_4t'] = float(val) * (1000 if unit == 's' else 1)

    return results

# Collect data
data = defaultdict(list)
for inst_dir in sorted(glob.glob(f'{RESULTS_DIR}/*/')):
    inst = os.path.basename(inst_dir.rstrip('/'))
    for run in range(1, 6):
        logfile = f'{inst_dir}/run{run}.log'
        if os.path.exists(logfile) and os.path.getsize(logfile) > 100:
            try:
                r = parse_log(logfile)
                if r.get('rps_4t', 0) > 0:
                    data[inst].append(r)
            except: pass

# Calculate averages and generate report
results = []
for inst, runs in sorted(data.items()):
    if not runs: continue
    avg = {k: sum(r.get(k,0) for r in runs)/len(runs) for k in ['rps_2t', 'rps_4t', 'rps_8t', 'latency_4t']}
    price = PRICING.get(inst, 0.2)
    eff = avg.get('rps_4t', 0) / price / 1000
    results.append((inst, avg, price, eff))

results.sort(key=lambda x: -x[1].get('rps_4t', 0))

with open(f'{RESULTS_DIR}/report.md', 'w') as f:
    f.write("# Nginx Benchmark Report (wrk)\n\n")
    f.write("## Test Configuration\n")
    f.write("- wrk benchmark, 30s duration\n")
    f.write("- Tests: 2/4/8 threads with 100/200/400 connections\n\n")

    f.write("## Top 10 - 4 Threads Performance\n\n")
    f.write("| Rank | Instance | RPS (4T) | Latency | Price | Efficiency |\n")
    f.write("|------|----------|----------|---------|-------|------------|\n")
    for i, (inst, avg, price, eff) in enumerate(results[:10], 1):
        f.write(f"| {i} | {inst} | {avg['rps_4t']:,.0f} | {avg.get('latency_4t',0):.2f}ms | ${price:.2f} | {eff:.0f} |\n")

    f.write("\n## All Instances\n\n")
    f.write("| Rank | Instance | 2T RPS | 4T RPS | 8T RPS | Latency | Price | Eff |\n")
    f.write("|------|----------|--------|--------|--------|---------|-------|-----|\n")
    for i, (inst, avg, price, eff) in enumerate(results, 1):
        f.write(f"| {i} | {inst} | {avg['rps_2t']:,.0f} | {avg['rps_4t']:,.0f} | {avg['rps_8t']:,.0f} | {avg.get('latency_4t',0):.2f}ms | ${price:.2f} | {eff:.0f} |\n")

print(f"Report saved: {RESULTS_DIR}/report.md")
print(f"Instances: {len(results)}")
