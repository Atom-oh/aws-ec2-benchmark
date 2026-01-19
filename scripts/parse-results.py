#!/usr/bin/env python3
"""Parse benchmark raw logs and generate summary CSVs"""

import os
import re
import csv
from pathlib import Path

RESULTS_DIR = '/home/ec2-user/benchmark/results'

def parse_redis_logs():
    """Parse Redis benchmark logs and generate summary CSV"""
    redis_dir = Path(f'{RESULTS_DIR}/redis')
    output_file = f'{RESULTS_DIR}/redis-summary.csv'

    results = []
    for logfile in sorted(redis_dir.glob('*.log')):
        instance = logfile.stem
        content = logfile.read_text()

        # Extract SET ops/sec from Standard Benchmark section
        set_match = re.search(r'SET:\s+(\d+\.?\d*)\s+requests per second', content)
        get_match = re.search(r'GET:\s+(\d+\.?\d*)\s+requests per second', content)

        set_ops = float(set_match.group(1)) if set_match else 0
        get_ops = float(get_match.group(1)) if get_match else 0

        results.append({
            'Instance Type': instance,
            'SET (ops/sec)': int(set_ops),
            'GET (ops/sec)': int(get_ops),
        })

    # Write CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['Instance Type', 'SET (ops/sec)', 'GET (ops/sec)'])
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda x: x['Instance Type']))

    print(f"Generated: {output_file} ({len(results)} instances)")

def parse_nginx_logs():
    """Parse Nginx benchmark logs and generate summary CSV"""
    nginx_dir = Path(f'{RESULTS_DIR}/nginx')
    output_file = f'{RESULTS_DIR}/nginx-summary.csv'

    results = []
    for logfile in sorted(nginx_dir.glob('*.log')):
        instance = logfile.stem
        content = logfile.read_text()

        # Extract Requests/sec from different test configurations
        # Look for pattern like "Requests/sec:  35506.83"
        req_matches = re.findall(r'Requests/sec:\s+(\d+\.?\d*)', content)

        # Get the highest throughput value
        if req_matches:
            req_sec = max(float(r) for r in req_matches)
        else:
            req_sec = 0

        results.append({
            'Instance Type': instance,
            'Requests/sec': int(req_sec),
        })

    # Write CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['Instance Type', 'Requests/sec'])
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda x: x['Instance Type']))

    print(f"Generated: {output_file} ({len(results)} instances)")

def parse_springboot_csv():
    """Copy/format Spring Boot results"""
    input_file = f'{RESULTS_DIR}/springboot/startup-times-full.csv'
    output_file = f'{RESULTS_DIR}/springboot-summary.csv'

    # Read existing CSV
    with open(input_file, 'r') as f:
        reader = csv.DictReader(f)
        results = []
        for row in reader:
            results.append({
                'Instance Type': row['instance_type'],
                'Startup (sec)': row['startup_seconds'],
                'Process (sec)': row['process_seconds'],
                'Cold Start (ms)': row.get('coldstart_ms', ''),
            })

    # Write formatted CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['Instance Type', 'Startup (sec)', 'Process (sec)', 'Cold Start (ms)'])
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda x: x['Instance Type']))

    print(f"Generated: {output_file} ({len(results)} instances)")

def main():
    print("Parsing benchmark results...")
    parse_redis_logs()
    parse_nginx_logs()
    parse_springboot_csv()
    print("\nAll summary CSVs generated!")

if __name__ == '__main__':
    main()
