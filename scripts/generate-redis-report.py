#!/usr/bin/env python3
"""
Redis Benchmark Report Generator
Parses all Redis benchmark logs and generates HTML report with multiple metrics
"""

import os
import re
import json
from pathlib import Path
from collections import defaultdict
import statistics

RESULTS_DIR = Path("/home/ec2-user/benchmark/results/redis")
OUTPUT_FILE = RESULTS_DIR / "report.html"

# Instance categories
INTEL_5TH = ['c5.xlarge', 'c5d.xlarge', 'c5n.xlarge', 'm5.xlarge', 'm5d.xlarge', 'm5zn.xlarge',
             'r5.xlarge', 'r5b.xlarge', 'r5d.xlarge', 'r5dn.xlarge', 'r5n.xlarge']
INTEL_6TH = ['c6i.xlarge', 'c6id.xlarge', 'c6in.xlarge', 'm6i.xlarge', 'm6id.xlarge', 'm6idn.xlarge', 'm6in.xlarge',
             'r6i.xlarge', 'r6id.xlarge']
INTEL_7TH = ['c7i.xlarge', 'c7i-flex.xlarge', 'm7i.xlarge', 'm7i-flex.xlarge', 'r7i.xlarge']
INTEL_8TH = ['c8i.xlarge', 'c8i-flex.xlarge', 'm8i.xlarge', 'r8i.xlarge', 'r8i-flex.xlarge']
AMD = ['c5a.xlarge', 'm5a.xlarge', 'm5ad.xlarge', 'r5a.xlarge', 'r5ad.xlarge']
GRAVITON2 = ['c6g.xlarge', 'c6gd.xlarge', 'c6gn.xlarge', 'm6g.xlarge', 'm6gd.xlarge', 'r6g.xlarge', 'r6gd.xlarge']
GRAVITON3 = ['c7g.xlarge', 'c7gd.xlarge', 'm7g.xlarge', 'm7gd.xlarge', 'r7g.xlarge', 'r7gd.xlarge']
GRAVITON4 = ['c8g.xlarge', 'm8g.xlarge', 'r8g.xlarge']

def get_category(instance):
    if instance in INTEL_5TH: return 'Intel 5th'
    if instance in INTEL_6TH: return 'Intel 6th'
    if instance in INTEL_7TH: return 'Intel 7th'
    if instance in INTEL_8TH: return 'Intel 8th'
    if instance in AMD: return 'AMD'
    if instance in GRAVITON2: return 'Graviton2'
    if instance in GRAVITON3: return 'Graviton3'
    if instance in GRAVITON4: return 'Graviton4'
    return 'Unknown'

def get_arch(instance):
    if any(g in instance for g in ['g.', 'gd.', 'gn.']):
        return 'arm64'
    return 'x86_64'

def parse_section(content, section_marker, next_section_marker=None):
    """Parse a benchmark section by extracting lines with 'requests per second, p50='"""
    results = {}
    lines = content.replace('\r', '\n').split('\n')

    # Pattern for final results with p50: "COMMAND: XXXXX.XX requests per second, p50=X.XXX msec"
    pattern = r'^([A-Z_0-9]+(?:\s*\([^)]+\))?):?\s*([\d.]+)\s*requests per second,\s*p50='

    in_section = False
    for line in lines:
        if section_marker in line:
            in_section = True
            continue
        if in_section and next_section_marker and next_section_marker in line:
            break
        if in_section and '---' in line and section_marker not in line:
            break
        if in_section:
            match = re.match(pattern, line.strip())
            if match:
                cmd = match.group(1).strip()
                # Simplify command names
                if '(' in cmd:
                    cmd = cmd.split('(')[0].strip()
                rps = float(match.group(2))
                results[cmd] = rps

    return results

def parse_standard_benchmark(content):
    """Parse standard benchmark section (50 clients, 100000 requests)"""
    return parse_section(content, '--- Standard Benchmark', '--- Pipeline')

def parse_pipeline_benchmark(content):
    """Parse pipeline benchmark section (16 commands per pipeline)"""
    return parse_section(content, '--- Pipeline Benchmark', '--- High Concurrency')

def parse_high_concurrency(content):
    """Parse high concurrency section (100 clients)"""
    return parse_section(content, '--- High Concurrency', '--- Latency Distribution')

def parse_large_value_test(content, size_kb):
    """Parse large value test section"""
    section_marker = f"--- Large Value Test ({size_kb}KB"
    next_marker = "--- Large Value Test (4KB" if size_kb == 1 else "===== Redis Benchmark Complete"
    return parse_section(content, section_marker, next_marker)

def parse_log_file(filepath):
    """Parse a single Redis benchmark log file"""
    with open(filepath, 'r') as f:
        content = f.read()

    return {
        'standard': parse_standard_benchmark(content),
        'pipeline': parse_pipeline_benchmark(content),
        'high_concurrency': parse_high_concurrency(content),
        'large_1kb': parse_large_value_test(content, 1),
        'large_4kb': parse_large_value_test(content, 4)
    }

def collect_all_results():
    """Collect results from all instance directories"""
    all_results = {}

    for instance_dir in RESULTS_DIR.iterdir():
        if not instance_dir.is_dir() or instance_dir.name.startswith('report'):
            continue

        instance = instance_dir.name
        runs = []

        for run_num in range(1, 6):
            log_file = instance_dir / f"run{run_num}.log"
            if log_file.exists():
                try:
                    runs.append(parse_log_file(log_file))
                except Exception as e:
                    print(f"Error parsing {log_file}: {e}")

        if runs:
            all_results[instance] = runs

    return all_results

def calculate_averages(results):
    """Calculate average metrics across all runs for each instance"""
    averages = {}

    for instance, runs in results.items():
        avg = {
            'standard': defaultdict(list),
            'pipeline': defaultdict(list),
            'high_concurrency': defaultdict(list),
            'large_1kb': defaultdict(list),
            'large_4kb': defaultdict(list)
        }

        for run in runs:
            for section in avg.keys():
                for cmd, value in run.get(section, {}).items():
                    avg[section][cmd].append(value)

        # Calculate means
        averages[instance] = {
            'category': get_category(instance),
            'arch': get_arch(instance),
            'runs': len(runs),
            'standard': {cmd: statistics.mean(vals) for cmd, vals in avg['standard'].items() if vals},
            'pipeline': {cmd: statistics.mean(vals) for cmd, vals in avg['pipeline'].items() if vals},
            'high_concurrency': {cmd: statistics.mean(vals) for cmd, vals in avg['high_concurrency'].items() if vals},
            'large_1kb': {cmd: statistics.mean(vals) for cmd, vals in avg['large_1kb'].items() if vals},
            'large_4kb': {cmd: statistics.mean(vals) for cmd, vals in avg['large_4kb'].items() if vals}
        }

    return averages

def generate_html_report(averages):
    """Generate HTML report"""

    # Key metrics to show
    key_commands = ['SET', 'GET', 'INCR', 'LPUSH', 'RPUSH', 'LPOP', 'RPOP', 'SADD', 'HSET', 'MSET']

    # Sort instances by category then name
    category_order = ['Intel 5th', 'Intel 6th', 'Intel 7th', 'Intel 8th', 'AMD', 'Graviton2', 'Graviton3', 'Graviton4']
    sorted_instances = sorted(averages.keys(), key=lambda x: (category_order.index(averages[x]['category']), x))

    # Find best performers for each metric
    def find_best(metric_section, command):
        best = None
        best_val = 0
        for inst, data in averages.items():
            val = data.get(metric_section, {}).get(command, 0)
            if val > best_val:
                best_val = val
                best = inst
        return best, best_val

    html = '''<!DOCTYPE html>
<html>
<head>
    <title>Redis Benchmark Report - 51 EC2 Instance Types</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f5f5f5; }
        h1, h2, h3 { color: #333; }
        .container { max-width: 1800px; margin: 0 auto; }
        .summary { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }
        .summary-card { background: #f8f9fa; padding: 15px; border-radius: 6px; text-align: center; }
        .summary-card h4 { margin: 0 0 10px 0; color: #666; font-size: 14px; }
        .summary-card .value { font-size: 24px; font-weight: bold; color: #2196F3; }
        .summary-card .instance { font-size: 12px; color: #999; margin-top: 5px; }
        table { border-collapse: collapse; width: 100%; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 30px; }
        th, td { padding: 10px 12px; text-align: right; border-bottom: 1px solid #eee; font-size: 13px; }
        th { background: #2196F3; color: white; position: sticky; top: 0; font-weight: 500; }
        th:first-child, td:first-child { text-align: left; position: sticky; left: 0; background: inherit; }
        tr:nth-child(even) { background: #fafafa; }
        tr:hover { background: #e3f2fd; }
        .best { background: #c8e6c9 !important; font-weight: bold; }
        .category { background: #e3f2fd; font-weight: bold; }
        .intel5 { border-left: 4px solid #1976D2; }
        .intel6 { border-left: 4px solid #2196F3; }
        .intel7 { border-left: 4px solid #42A5F5; }
        .intel8 { border-left: 4px solid #64B5F6; }
        .amd { border-left: 4px solid #F44336; }
        .graviton2 { border-left: 4px solid #FF9800; }
        .graviton3 { border-left: 4px solid #FFC107; }
        .graviton4 { border-left: 4px solid #FFEB3B; }
        .section { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; overflow-x: auto; }
        .legend { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px; }
        .legend-item { display: flex; align-items: center; gap: 8px; font-size: 13px; }
        .legend-color { width: 20px; height: 20px; border-radius: 4px; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        .tab { padding: 10px 20px; background: #e0e0e0; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
        .tab.active { background: #2196F3; color: white; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .metric-value { font-family: monospace; }
        .nav { position: fixed; top: 20px; right: 20px; background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); }
        .nav a { display: block; padding: 5px 0; color: #2196F3; text-decoration: none; font-size: 13px; }
        .nav a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔴 Redis Benchmark Report</h1>
        <p>51 EC2 Instance Types (xlarge, 4 vCPU) × 5 Runs | redis-benchmark with 50-100 clients</p>

        <div class="nav">
            <strong>Quick Nav</strong>
            <a href="#summary">Summary</a>
            <a href="#standard">Standard (50 clients)</a>
            <a href="#pipeline">Pipeline (16 cmds)</a>
            <a href="#highconc">High Concurrency</a>
            <a href="#large">Large Values</a>
        </div>

        <div class="legend">
            <div class="legend-item"><div class="legend-color" style="background: #1976D2;"></div> Intel 5th Gen</div>
            <div class="legend-item"><div class="legend-color" style="background: #2196F3;"></div> Intel 6th Gen</div>
            <div class="legend-item"><div class="legend-color" style="background: #42A5F5;"></div> Intel 7th Gen</div>
            <div class="legend-item"><div class="legend-color" style="background: #64B5F6;"></div> Intel 8th Gen</div>
            <div class="legend-item"><div class="legend-color" style="background: #F44336;"></div> AMD</div>
            <div class="legend-item"><div class="legend-color" style="background: #FF9800;"></div> Graviton2</div>
            <div class="legend-item"><div class="legend-color" style="background: #FFC107;"></div> Graviton3</div>
            <div class="legend-item"><div class="legend-color" style="background: #FFEB3B;"></div> Graviton4</div>
        </div>
'''

    # Summary section
    html += '<div class="summary" id="summary"><h2>📊 Top Performers</h2><div class="summary-grid">'

    for cmd in ['SET', 'GET', 'LPUSH', 'HSET']:
        best_inst, best_val = find_best('standard', cmd)
        if best_inst:
            html += f'''
            <div class="summary-card">
                <h4>{cmd} (Standard)</h4>
                <div class="value">{best_val:,.0f}</div>
                <div class="instance">{best_inst} ({averages[best_inst]["category"]})</div>
            </div>'''

    for cmd in ['SET', 'GET']:
        best_inst, best_val = find_best('pipeline', cmd)
        if best_inst:
            html += f'''
            <div class="summary-card">
                <h4>{cmd} (Pipeline 16x)</h4>
                <div class="value">{best_val:,.0f}</div>
                <div class="instance">{best_inst} ({averages[best_inst]["category"]})</div>
            </div>'''

    html += '</div></div>'

    # Standard Benchmark Table
    html += '<div class="section" id="standard"><h2>Standard Benchmark (50 clients, 100K requests)</h2>'
    html += '<table><thead><tr><th>Instance</th><th>Category</th>'
    for cmd in key_commands:
        html += f'<th>{cmd}</th>'
    html += '</tr></thead><tbody>'

    # Find best for each command
    best_standard = {cmd: find_best('standard', cmd)[0] for cmd in key_commands}

    for instance in sorted_instances:
        data = averages[instance]
        cat_class = data['category'].lower().replace(' ', '').replace('graviton', 'graviton')
        if 'intel' in cat_class:
            cat_class = 'intel' + cat_class[-1]

        html += f'<tr class="{cat_class}"><td><strong>{instance}</strong></td><td>{data["category"]}</td>'
        for cmd in key_commands:
            val = data['standard'].get(cmd, 0)
            is_best = instance == best_standard.get(cmd)
            cell_class = 'best' if is_best else ''
            html += f'<td class="{cell_class} metric-value">{val:,.0f}</td>'
        html += '</tr>'

    html += '</tbody></table></div>'

    # Pipeline Benchmark Table
    html += '<div class="section" id="pipeline"><h2>Pipeline Benchmark (16 commands per pipeline)</h2>'
    html += '<table><thead><tr><th>Instance</th><th>Category</th>'
    for cmd in key_commands:
        html += f'<th>{cmd}</th>'
    html += '</tr></thead><tbody>'

    best_pipeline = {cmd: find_best('pipeline', cmd)[0] for cmd in key_commands}

    for instance in sorted_instances:
        data = averages[instance]
        cat_class = data['category'].lower().replace(' ', '').replace('graviton', 'graviton')
        if 'intel' in cat_class:
            cat_class = 'intel' + cat_class[-1]

        html += f'<tr class="{cat_class}"><td><strong>{instance}</strong></td><td>{data["category"]}</td>'
        for cmd in key_commands:
            val = data['pipeline'].get(cmd, 0)
            is_best = instance == best_pipeline.get(cmd)
            cell_class = 'best' if is_best else ''
            html += f'<td class="{cell_class} metric-value">{val:,.0f}</td>'
        html += '</tr>'

    html += '</tbody></table></div>'

    # High Concurrency Table
    html += '<div class="section" id="highconc"><h2>High Concurrency (100 clients, 200K requests)</h2>'
    html += '<table><thead><tr><th>Instance</th><th>Category</th>'
    for cmd in key_commands:
        html += f'<th>{cmd}</th>'
    html += '</tr></thead><tbody>'

    best_highconc = {cmd: find_best('high_concurrency', cmd)[0] for cmd in key_commands}

    for instance in sorted_instances:
        data = averages[instance]
        cat_class = data['category'].lower().replace(' ', '').replace('graviton', 'graviton')
        if 'intel' in cat_class:
            cat_class = 'intel' + cat_class[-1]

        html += f'<tr class="{cat_class}"><td><strong>{instance}</strong></td><td>{data["category"]}</td>'
        for cmd in key_commands:
            val = data['high_concurrency'].get(cmd, 0)
            is_best = instance == best_highconc.get(cmd)
            cell_class = 'best' if is_best else ''
            html += f'<td class="{cell_class} metric-value">{val:,.0f}</td>'
        html += '</tr>'

    html += '</tbody></table></div>'

    # Large Value Tests
    html += '<div class="section" id="large"><h2>Large Value Tests</h2>'
    html += '<h3>1KB Values (50K requests)</h3>'
    html += '<table><thead><tr><th>Instance</th><th>Category</th><th>SET</th><th>GET</th></tr></thead><tbody>'

    best_1kb_set = find_best('large_1kb', 'SET')[0]
    best_1kb_get = find_best('large_1kb', 'GET')[0]

    for instance in sorted_instances:
        data = averages[instance]
        cat_class = data['category'].lower().replace(' ', '').replace('graviton', 'graviton')
        if 'intel' in cat_class:
            cat_class = 'intel' + cat_class[-1]

        set_val = data['large_1kb'].get('SET', 0)
        get_val = data['large_1kb'].get('GET', 0)

        html += f'<tr class="{cat_class}"><td><strong>{instance}</strong></td><td>{data["category"]}</td>'
        html += f'<td class="{"best" if instance == best_1kb_set else ""} metric-value">{set_val:,.0f}</td>'
        html += f'<td class="{"best" if instance == best_1kb_get else ""} metric-value">{get_val:,.0f}</td>'
        html += '</tr>'

    html += '</tbody></table>'

    html += '<h3>4KB Values (20K requests)</h3>'
    html += '<table><thead><tr><th>Instance</th><th>Category</th><th>SET</th><th>GET</th></tr></thead><tbody>'

    best_4kb_set = find_best('large_4kb', 'SET')[0]
    best_4kb_get = find_best('large_4kb', 'GET')[0]

    for instance in sorted_instances:
        data = averages[instance]
        cat_class = data['category'].lower().replace(' ', '').replace('graviton', 'graviton')
        if 'intel' in cat_class:
            cat_class = 'intel' + cat_class[-1]

        set_val = data['large_4kb'].get('SET', 0)
        get_val = data['large_4kb'].get('GET', 0)

        html += f'<tr class="{cat_class}"><td><strong>{instance}</strong></td><td>{data["category"]}</td>'
        html += f'<td class="{"best" if instance == best_4kb_set else ""} metric-value">{set_val:,.0f}</td>'
        html += f'<td class="{"best" if instance == best_4kb_get else ""} metric-value">{get_val:,.0f}</td>'
        html += '</tr>'

    html += '</tbody></table></div>'

    # Footer
    html += f'''
        <div class="summary">
            <p><strong>Test Configuration:</strong></p>
            <ul>
                <li>Redis 7.x (Alpine image)</li>
                <li>Standard: 50 clients, 100,000 requests</li>
                <li>Pipeline: 16 commands per pipeline</li>
                <li>High Concurrency: 100 clients, 200,000 requests</li>
                <li>Large Values: 1KB and 4KB payloads</li>
                <li>5 runs per instance, averaged results</li>
            </ul>
            <p><em>Generated from {len(averages)} instances</em></p>
        </div>
    </div>
</body>
</html>'''

    return html

def main():
    print("Collecting Redis benchmark results...")
    results = collect_all_results()
    print(f"Found {len(results)} instances")

    print("Calculating averages...")
    averages = calculate_averages(results)

    print("Generating HTML report...")
    html = generate_html_report(averages)

    with open(OUTPUT_FILE, 'w') as f:
        f.write(html)

    print(f"Report saved to {OUTPUT_FILE}")

    # Also save JSON data
    json_file = RESULTS_DIR / "report-data.json"
    with open(json_file, 'w') as f:
        json.dump(averages, f, indent=2)
    print(f"Data saved to {json_file}")

if __name__ == '__main__':
    main()
