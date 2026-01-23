#!/usr/bin/env python3
"""Parse Redis benchmark logs and generate JSON data for report."""

import os
import re
import json
from pathlib import Path

# Instance pricing (hourly USD)
INSTANCE_PRICES = {
    'c5.xlarge': 0.17, 'c5a.xlarge': 0.154, 'c5d.xlarge': 0.192, 'c5n.xlarge': 0.216,
    'c6i.xlarge': 0.17, 'c6id.xlarge': 0.2016, 'c6in.xlarge': 0.2268,
    'c7i.xlarge': 0.1785, 'c7i-flex.xlarge': 0.15129,
    'c8i.xlarge': 0.18743, 'c8i-flex.xlarge': 0.15894,
    'c6g.xlarge': 0.136, 'c6gd.xlarge': 0.1536, 'c6gn.xlarge': 0.1728,
    'c7g.xlarge': 0.1454, 'c7gd.xlarge': 0.16314,
    'c8g.xlarge': 0.15267,
    'm5.xlarge': 0.192, 'm5a.xlarge': 0.172, 'm5ad.xlarge': 0.206, 'm5d.xlarge': 0.226, 'm5zn.xlarge': 0.3303,
    'm6i.xlarge': 0.192, 'm6id.xlarge': 0.2268, 'm6idn.xlarge': 0.27108, 'm6in.xlarge': 0.2421,
    'm7i.xlarge': 0.2016, 'm7i-flex.xlarge': 0.17136,
    'm8i.xlarge': 0.21168,
    'm6g.xlarge': 0.154, 'm6gd.xlarge': 0.1808,
    'm7g.xlarge': 0.163, 'm7gd.xlarge': 0.19068,
    'm8g.xlarge': 0.17115,
    'r5.xlarge': 0.252, 'r5a.xlarge': 0.226, 'r5ad.xlarge': 0.262, 'r5b.xlarge': 0.298, 'r5d.xlarge': 0.288, 'r5dn.xlarge': 0.334, 'r5n.xlarge': 0.298,
    'r6i.xlarge': 0.252, 'r6id.xlarge': 0.2898,
    'r7i.xlarge': 0.2646,
    'r8i.xlarge': 0.27783, 'r8i-flex.xlarge': 0.23625,
    'r6g.xlarge': 0.2016, 'r6gd.xlarge': 0.2304,
    'r7g.xlarge': 0.2142, 'r7gd.xlarge': 0.24451,
    'r8g.xlarge': 0.22491,
}

def get_arch(instance):
    """Determine architecture from instance type."""
    if 'g.' in instance or 'gd.' in instance or 'gn.' in instance:
        return 'Graviton'
    elif 'a.' in instance or 'ad.' in instance:
        return 'AMD'
    else:
        return 'Intel'

def get_generation(instance):
    """Extract generation from instance type."""
    match = re.search(r'[cmr](\d+)', instance)
    if match:
        return int(match.group(1))
    return 0

def get_family(instance):
    """Extract family from instance type."""
    if instance.startswith('c'):
        return 'C'
    elif instance.startswith('m'):
        return 'M'
    elif instance.startswith('r'):
        return 'R'
    return 'Unknown'

def parse_redis_log(filepath):
    """Parse a single Redis benchmark log file."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

    result = {
        'set_rps': None,
        'get_rps': None,
        'set_avg_latency': None,
        'get_avg_latency': None,
        'set_p99_latency': None,
        'get_p99_latency': None,
    }

    # Parse SET latency test (Test 5)
    set_match = re.search(r'--- Test 5: Latency Test SET.*?\n"test","rps".*?\n"SET","([\d.]+)","([\d.]+)","[\d.]+","[\d.]+","[\d.]+","([\d.]+)"', content, re.DOTALL)
    if set_match:
        result['set_rps'] = float(set_match.group(1))
        result['set_avg_latency'] = float(set_match.group(2))
        result['set_p99_latency'] = float(set_match.group(3))

    # Parse GET latency test (Test 6)
    get_match = re.search(r'--- Test 6: Latency Test GET.*?\n"test","rps".*?\n"GET","([\d.]+)","([\d.]+)","[\d.]+","[\d.]+","[\d.]+","([\d.]+)"', content, re.DOTALL)
    if get_match:
        result['get_rps'] = float(get_match.group(1))
        result['get_avg_latency'] = float(get_match.group(2))
        result['get_p99_latency'] = float(get_match.group(3))

    # If latency tests not found, try to extract from Test 1/2 progress
    if result['set_rps'] is None:
        # Try to find last SET rps from progress line
        set_progress = re.findall(r'SET: rps=[\d.]+ \(overall: ([\d.]+)\)', content)
        if set_progress:
            result['set_rps'] = float(set_progress[-1])

    if result['get_rps'] is None:
        # Try to find last GET rps from progress line
        get_progress = re.findall(r'GET: rps=[\d.]+ \(overall: ([\d.]+)\)', content)
        if get_progress:
            result['get_rps'] = float(get_progress[-1])

    return result

def main():
    results_dir = Path('/home/ec2-user/benchmark/results/redis')
    all_data = []

    for instance_dir in sorted(results_dir.iterdir()):
        if not instance_dir.is_dir():
            continue

        instance = instance_dir.name
        runs_data = []

        for run_num in range(1, 6):
            log_file = instance_dir / f'run{run_num}.log'
            if log_file.exists():
                data = parse_redis_log(log_file)
                if data and data['set_rps'] is not None:
                    runs_data.append(data)

        if runs_data:
            # Calculate averages
            set_rps_values = [d['set_rps'] for d in runs_data if d['set_rps']]
            get_rps_values = [d['get_rps'] for d in runs_data if d['get_rps']]
            set_latency_values = [d['set_avg_latency'] for d in runs_data if d['set_avg_latency']]
            get_latency_values = [d['get_avg_latency'] for d in runs_data if d['get_avg_latency']]
            set_p99_values = [d['set_p99_latency'] for d in runs_data if d['set_p99_latency']]
            get_p99_values = [d['get_p99_latency'] for d in runs_data if d['get_p99_latency']]

            price = INSTANCE_PRICES.get(instance, 0.2)
            set_rps_avg = sum(set_rps_values) / len(set_rps_values) if set_rps_values else 0
            get_rps_avg = sum(get_rps_values) / len(get_rps_values) if get_rps_values else 0

            entry = {
                'instance': instance,
                'arch': get_arch(instance),
                'gen': get_generation(instance),
                'family': get_family(instance),
                'price': price,
                'runs': len(runs_data),
                'set_rps_avg': round(set_rps_avg, 2),
                'set_rps_all': [round(v, 2) for v in set_rps_values],
                'get_rps_avg': round(get_rps_avg, 2),
                'get_rps_all': [round(v, 2) for v in get_rps_values],
                'set_latency_avg': round(sum(set_latency_values) / len(set_latency_values), 3) if set_latency_values else None,
                'get_latency_avg': round(sum(get_latency_values) / len(get_latency_values), 3) if get_latency_values else None,
                'set_p99_avg': round(sum(set_p99_values) / len(set_p99_values), 3) if set_p99_values else None,
                'get_p99_avg': round(sum(get_p99_values) / len(get_p99_values), 3) if get_p99_values else None,
                'set_perf_per_dollar': round(set_rps_avg / price, 2) if price > 0 else 0,
                'get_perf_per_dollar': round(get_rps_avg / price, 2) if price > 0 else 0,
            }
            all_data.append(entry)
            print(f"{instance}: SET {entry['set_rps_avg']:.0f} ops/s, GET {entry['get_rps_avg']:.0f} ops/s ({len(runs_data)} runs)")

    # Sort by SET rps descending
    all_data.sort(key=lambda x: x['set_rps_avg'], reverse=True)

    # Output JSON
    output_file = results_dir / 'benchmark_data.json'
    with open(output_file, 'w') as f:
        json.dump(all_data, f, indent=2)

    print(f"\nSaved {len(all_data)} instances to {output_file}")

    # Print summary
    print("\n=== Top 10 by SET ops/s ===")
    for i, d in enumerate(all_data[:10], 1):
        print(f"{i}. {d['instance']}: {d['set_rps_avg']:.0f} ops/s ({d['arch']})")

    print("\n=== Top 10 by Performance/$ ===")
    by_perf_dollar = sorted(all_data, key=lambda x: x['set_perf_per_dollar'], reverse=True)
    for i, d in enumerate(by_perf_dollar[:10], 1):
        print(f"{i}. {d['instance']}: {d['set_perf_per_dollar']:.0f} ops/$/hr ({d['arch']})")

if __name__ == '__main__':
    main()
