#!/usr/bin/env python3
"""
Elasticsearch Benchmark Report Generator
Parses all log files and generates a comprehensive HTML report
"""

import os
import re
import json
from collections import defaultdict
from datetime import datetime
import statistics

RESULTS_DIR = "/home/ec2-user/benchmark/results/elasticsearch"
OUTPUT_FILE = "/home/ec2-user/benchmark/reports/elasticsearch/index.html"

def get_processor_type(instance):
    """Determine processor type from instance name"""
    if instance.endswith('a.xlarge') or instance.endswith('ad.xlarge'):
        if not any(x in instance for x in ['6g', '7g', '8g']):
            return 'AMD'
    if 'g.' in instance or 'gd.' in instance or 'gn.' in instance:
        return 'Graviton'
    return 'Intel'

def get_generation(instance):
    """Extract generation from instance name"""
    match = re.search(r'[cmr](\d)', instance)
    if match:
        return int(match.group(1))
    return 0

def get_family(instance):
    """Extract instance family (c, m, r)"""
    if instance.startswith('c'):
        return 'c'
    elif instance.startswith('m'):
        return 'm'
    elif instance.startswith('r'):
        return 'r'
    return 'unknown'

def parse_log_file(filepath):
    """Parse a single log file and extract metrics"""
    metrics = {}
    try:
        with open(filepath, 'r') as f:
            content = f.read()

        # Extract metrics
        patterns = {
            'cold_start': r'COLD_START_MS:\s*(\d+)',
            'seq_index': r'SEQUENTIAL_INDEX_100_MS:\s*(\d+)',
            'bulk_index': r'BULK_INDEX_1000_MS:\s*(\d+)',
            'search_all': r'SEARCH_MATCH_ALL_AVG_MS:\s*(\d+)',
            'search_term': r'SEARCH_TERM_AVG_MS:\s*(\d+)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                metrics[key] = int(match.group(1))

    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return metrics

def parse_all_results():
    """Parse all result directories and aggregate data"""
    results = {}

    for instance_dir in os.listdir(RESULTS_DIR):
        instance_path = os.path.join(RESULTS_DIR, instance_dir)
        if not os.path.isdir(instance_path):
            continue

        runs = []
        for log_file in sorted(os.listdir(instance_path)):
            if log_file.endswith('.log'):
                log_path = os.path.join(instance_path, log_file)
                metrics = parse_log_file(log_path)
                if metrics:
                    runs.append(metrics)

        if runs:
            results[instance_dir] = runs

    return results

def calculate_stats(runs, metric):
    """Calculate statistics for a metric across runs"""
    values = [r.get(metric) for r in runs if r.get(metric) is not None]
    if not values:
        return None

    return {
        'avg': statistics.mean(values),
        'min': min(values),
        'max': max(values),
        'std': statistics.stdev(values) if len(values) > 1 else 0,
        'count': len(values)
    }

def generate_html(results):
    """Generate comprehensive HTML report"""

    # Calculate aggregated stats for each instance
    instances_data = []
    for instance, runs in results.items():
        data = {
            'instance': instance,
            'processor': get_processor_type(instance),
            'generation': get_generation(instance),
            'family': get_family(instance),
            'runs': len(runs)
        }

        for metric in ['cold_start', 'seq_index', 'bulk_index', 'search_all', 'search_term']:
            stats = calculate_stats(runs, metric)
            if stats:
                data[metric] = stats
            else:
                data[metric] = {'avg': 0, 'min': 0, 'max': 0, 'std': 0, 'count': 0}

        instances_data.append(data)

    # Sort by cold start average
    instances_data.sort(key=lambda x: x['cold_start']['avg'] if x['cold_start']['avg'] > 0 else float('inf'))

    # Calculate overall stats
    all_cold_starts = [d['cold_start']['avg'] for d in instances_data if d['cold_start']['avg'] > 0]
    all_bulk_index = [d['bulk_index']['avg'] for d in instances_data if d['bulk_index']['avg'] > 0]
    all_seq_index = [d['seq_index']['avg'] for d in instances_data if d['seq_index']['avg'] > 0]
    all_search_all = [d['search_all']['avg'] for d in instances_data if d['search_all']['avg'] > 0]
    all_search_term = [d['search_term']['avg'] for d in instances_data if d['search_term']['avg'] > 0]

    # Processor averages
    processor_stats = defaultdict(lambda: defaultdict(list))
    for d in instances_data:
        proc = d['processor']
        if d['cold_start']['avg'] > 0:
            processor_stats[proc]['cold_start'].append(d['cold_start']['avg'])
        if d['bulk_index']['avg'] > 0:
            processor_stats[proc]['bulk_index'].append(d['bulk_index']['avg'])
        if d['seq_index']['avg'] > 0:
            processor_stats[proc]['seq_index'].append(d['seq_index']['avg'])
        if d['search_all']['avg'] > 0:
            processor_stats[proc]['search_all'].append(d['search_all']['avg'])
        if d['search_term']['avg'] > 0:
            processor_stats[proc]['search_term'].append(d['search_term']['avg'])

    proc_avgs = {}
    for proc in ['Intel', 'AMD', 'Graviton']:
        proc_avgs[proc] = {}
        for metric in ['cold_start', 'bulk_index', 'seq_index', 'search_all', 'search_term']:
            vals = processor_stats[proc][metric]
            proc_avgs[proc][metric] = statistics.mean(vals) if vals else 0

    # Generation averages
    gen_stats = defaultdict(lambda: defaultdict(list))
    for d in instances_data:
        gen = d['generation']
        if d['cold_start']['avg'] > 0:
            gen_stats[gen]['cold_start'].append(d['cold_start']['avg'])
        if d['bulk_index']['avg'] > 0:
            gen_stats[gen]['bulk_index'].append(d['bulk_index']['avg'])
        if d['seq_index']['avg'] > 0:
            gen_stats[gen]['seq_index'].append(d['seq_index']['avg'])

    gen_avgs = {}
    for gen in [5, 6, 7, 8]:
        gen_avgs[gen] = {}
        for metric in ['cold_start', 'bulk_index', 'seq_index']:
            vals = gen_stats[gen][metric]
            gen_avgs[gen][metric] = statistics.mean(vals) if vals else 0
        gen_avgs[gen]['count'] = len(gen_stats[gen]['cold_start'])

    # Best performers per metric
    best_cold_start = min(instances_data, key=lambda x: x['cold_start']['avg'] if x['cold_start']['avg'] > 0 else float('inf'))
    best_bulk = min(instances_data, key=lambda x: x['bulk_index']['avg'] if x['bulk_index']['avg'] > 0 else float('inf'))
    best_seq = min(instances_data, key=lambda x: x['seq_index']['avg'] if x['seq_index']['avg'] > 0 else float('inf'))
    best_search_all = min(instances_data, key=lambda x: x['search_all']['avg'] if x['search_all']['avg'] > 0 else float('inf'))
    best_search_term = min(instances_data, key=lambda x: x['search_term']['avg'] if x['search_term']['avg'] > 0 else float('inf'))

    # Generate chart data
    def get_bar_color(proc):
        colors = {
            'Intel': 'rgba(0, 114, 198, 0.8)',
            'AMD': 'rgba(237, 28, 36, 0.8)',
            'Graviton': 'rgba(255, 153, 0, 0.8)'
        }
        return colors.get(proc, 'rgba(128, 128, 128, 0.8)')

    # Cold start chart data (sorted)
    cold_start_data = [(d['instance'], d['cold_start']['avg'], get_bar_color(d['processor']))
                       for d in instances_data if d['cold_start']['avg'] > 0]

    # Bulk index chart data (sorted by bulk index)
    bulk_sorted = sorted([d for d in instances_data if d['bulk_index']['avg'] > 0],
                        key=lambda x: x['bulk_index']['avg'])
    bulk_data = [(d['instance'], d['bulk_index']['avg'], get_bar_color(d['processor'])) for d in bulk_sorted]

    # Sequential index chart data (sorted by seq index)
    seq_sorted = sorted([d for d in instances_data if d['seq_index']['avg'] > 0],
                       key=lambda x: x['seq_index']['avg'])
    seq_data = [(d['instance'], d['seq_index']['avg'], get_bar_color(d['processor'])) for d in seq_sorted]

    # Search latency chart data (sorted by search_all)
    search_sorted = sorted([d for d in instances_data if d['search_all']['avg'] > 0],
                          key=lambda x: x['search_all']['avg'])
    search_data = [(d['instance'], d['search_all']['avg'], d['search_term']['avg'], get_bar_color(d['processor']))
                   for d in search_sorted]

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Elasticsearch Benchmark Report - Complete Analysis</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --primary-color: #1a73e8;
            --secondary-color: #5f6368;
            --background-color: #f8f9fa;
            --card-background: #ffffff;
            --border-color: #e0e0e0;
            --intel-color: #0072c6;
            --amd-color: #ed1c24;
            --graviton-color: #ff9900;
            --success-color: #34a853;
            --warning-color: #fbbc04;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--background-color);
            color: #333;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1800px;
            margin: 0 auto;
            padding: 20px;
        }}

        header {{
            background: linear-gradient(135deg, #00897b 0%, #004d40 100%);
            color: white;
            padding: 40px 20px;
            text-align: center;
            margin-bottom: 30px;
            border-radius: 10px;
        }}

        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}

        header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}

        .card {{
            background: var(--card-background);
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            overflow: hidden;
        }}

        .card-header {{
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            padding: 15px 20px;
            border-bottom: 1px solid var(--border-color);
        }}

        .card-header h2 {{
            font-size: 1.4em;
            color: #333;
        }}

        .card-body {{
            padding: 20px;
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}

        .summary-item {{
            background: linear-gradient(135deg, #00897b 0%, #004d40 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }}

        .summary-item.intel {{
            background: linear-gradient(135deg, #0072c6 0%, #00a2e8 100%);
        }}

        .summary-item.amd {{
            background: linear-gradient(135deg, #ed1c24 0%, #ff6b6b 100%);
        }}

        .summary-item.graviton {{
            background: linear-gradient(135deg, #ff9900 0%, #ffcc00 100%);
        }}

        .summary-item.cold-start {{
            background: linear-gradient(135deg, #5c6bc0 0%, #3f51b5 100%);
        }}

        .summary-item.bulk-index {{
            background: linear-gradient(135deg, #26a69a 0%, #009688 100%);
        }}

        .summary-item.seq-index {{
            background: linear-gradient(135deg, #42a5f5 0%, #1e88e5 100%);
        }}

        .summary-item.search {{
            background: linear-gradient(135deg, #ab47bc 0%, #8e24aa 100%);
        }}

        .summary-item h3 {{
            font-size: 0.85em;
            opacity: 0.9;
            margin-bottom: 5px;
        }}

        .summary-item .value {{
            font-size: 1.8em;
            font-weight: bold;
        }}

        .summary-item .unit {{
            font-size: 0.75em;
            opacity: 0.8;
        }}

        .summary-item .detail {{
            font-size: 0.7em;
            opacity: 0.7;
            margin-top: 5px;
        }}

        .chart-container {{
            position: relative;
            height: 400px;
            margin: 20px 0;
        }}

        .chart-container.large {{
            height: 600px;
        }}

        .chart-container.xlarge {{
            height: 700px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85em;
        }}

        th, td {{
            padding: 10px 8px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }}

        th {{
            background-color: #f5f7fa;
            font-weight: 600;
            color: #555;
            position: sticky;
            top: 0;
            z-index: 10;
        }}

        tr:hover {{
            background-color: #f8f9fa;
        }}

        .table-wrapper {{
            max-height: 700px;
            overflow-y: auto;
        }}

        .processor-intel {{
            color: var(--intel-color);
            font-weight: bold;
        }}

        .processor-amd {{
            color: var(--amd-color);
            font-weight: bold;
        }}

        .processor-graviton {{
            color: var(--graviton-color);
            font-weight: bold;
        }}

        .best {{
            background-color: #e8f5e9;
        }}

        .worst {{
            background-color: #ffebee;
        }}

        .top3 {{
            background-color: #e3f2fd;
        }}

        .legend {{
            display: flex;
            justify-content: center;
            gap: 30px;
            margin: 20px 0;
            flex-wrap: wrap;
        }}

        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 4px;
        }}

        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
        }}

        .metric-explanation {{
            background: #e8f5e9;
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
            border-left: 4px solid #4caf50;
        }}

        .metric-explanation h4 {{
            color: #2e7d32;
            margin-bottom: 10px;
        }}

        .metric-explanation ul {{
            margin-left: 20px;
        }}

        .metric-explanation li {{
            margin-bottom: 5px;
        }}

        .highlight-box {{
            background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
            border-left: 4px solid #ff9800;
        }}

        .highlight-box h4 {{
            color: #e65100;
            margin-bottom: 10px;
        }}

        .tabs {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}

        .tab {{
            padding: 10px 20px;
            background: #e0e0e0;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
        }}

        .tab.active {{
            background: #00897b;
            color: white;
        }}

        .tab-content {{
            display: none;
        }}

        .tab-content.active {{
            display: block;
        }}

        footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 0.9em;
        }}

        .stats-comparison {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin: 20px 0;
        }}

        .stat-box {{
            background: #f5f5f5;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}

        .stat-box.intel {{
            border-left: 4px solid var(--intel-color);
        }}

        .stat-box.amd {{
            border-left: 4px solid var(--amd-color);
        }}

        .stat-box.graviton {{
            border-left: 4px solid var(--graviton-color);
        }}

        @media (max-width: 768px) {{
            .charts-grid {{
                grid-template-columns: 1fr;
            }}

            .stats-comparison {{
                grid-template-columns: 1fr;
            }}

            header h1 {{
                font-size: 1.8em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Elasticsearch Benchmark Report</h1>
            <p>EC2 Instance Performance Comparison - Complete Analysis</p>
            <p>51 Instance Types (xlarge, 4 vCPU) | 5th-8th Generation</p>
            <p>Generated: {timestamp}</p>
        </header>

        <!-- Overall Summary -->
        <div class="card">
            <div class="card-header">
                <h2>Executive Summary / 종합 요약</h2>
            </div>
            <div class="card-body">
                <div class="summary-grid">
                    <div class="summary-item">
                        <h3>Total Instances / 테스트 인스턴스</h3>
                        <div class="value">{len(instances_data)}</div>
                        <div class="unit">instance types</div>
                    </div>
                    <div class="summary-item cold-start">
                        <h3>Best Cold Start / 최고 성능</h3>
                        <div class="value">{best_cold_start['cold_start']['avg']:.0f}</div>
                        <div class="unit">ms ({best_cold_start['instance']})</div>
                    </div>
                    <div class="summary-item bulk-index">
                        <h3>Best Bulk Index / 벌크 인덱싱</h3>
                        <div class="value">{best_bulk['bulk_index']['avg']:.0f}</div>
                        <div class="unit">ms ({best_bulk['instance']})</div>
                    </div>
                    <div class="summary-item seq-index">
                        <h3>Best Sequential Index / 순차 인덱싱</h3>
                        <div class="value">{best_seq['seq_index']['avg']:.0f}</div>
                        <div class="unit">ms ({best_seq['instance']})</div>
                    </div>
                    <div class="summary-item search">
                        <h3>Best Search Latency / 검색 지연</h3>
                        <div class="value">{best_search_all['search_all']['avg']:.0f}</div>
                        <div class="unit">ms ({best_search_all['instance']})</div>
                    </div>
                </div>

                <div class="legend">
                    <div class="legend-item">
                        <div class="legend-color" style="background-color: var(--intel-color);"></div>
                        <span>Intel</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background-color: var(--amd-color);"></div>
                        <span>AMD</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background-color: var(--graviton-color);"></div>
                        <span>AWS Graviton</span>
                    </div>
                </div>

                <div class="metric-explanation">
                    <h4>Metrics Explanation / 메트릭 설명</h4>
                    <ul>
                        <li><strong>COLD_START_MS</strong>: Elasticsearch HTTP ready time (JVM start to HTTP responding) / ES 시작부터 HTTP 응답까지 시간</li>
                        <li><strong>SEQUENTIAL_INDEX_100_MS</strong>: Time to index 100 documents one by one / 100개 문서 순차 인덱싱 시간</li>
                        <li><strong>BULK_INDEX_1000_MS</strong>: Time to bulk index 1000 documents in one request / 1000개 문서 벌크 인덱싱 시간</li>
                        <li><strong>SEARCH_MATCH_ALL_AVG_MS</strong>: Average match_all query latency (10 runs) / match_all 쿼리 평균 지연시간</li>
                        <li><strong>SEARCH_TERM_AVG_MS</strong>: Average term query latency (10 runs) / term 쿼리 평균 지연시간</li>
                    </ul>
                </div>
            </div>
        </div>

        <!-- Processor Comparison -->
        <div class="card">
            <div class="card-header">
                <h2>Processor Performance Comparison / 프로세서별 성능 비교</h2>
            </div>
            <div class="card-body">
                <div class="stats-comparison">
                    <div class="stat-box intel">
                        <h4 style="color: var(--intel-color);">Intel</h4>
                        <p><strong>Cold Start:</strong> {proc_avgs['Intel']['cold_start']:.0f} ms</p>
                        <p><strong>Bulk Index:</strong> {proc_avgs['Intel']['bulk_index']:.0f} ms</p>
                        <p><strong>Seq Index:</strong> {proc_avgs['Intel']['seq_index']:.0f} ms</p>
                        <p><strong>Search All:</strong> {proc_avgs['Intel']['search_all']:.0f} ms</p>
                        <p><strong>Search Term:</strong> {proc_avgs['Intel']['search_term']:.0f} ms</p>
                    </div>
                    <div class="stat-box amd">
                        <h4 style="color: var(--amd-color);">AMD</h4>
                        <p><strong>Cold Start:</strong> {proc_avgs['AMD']['cold_start']:.0f} ms</p>
                        <p><strong>Bulk Index:</strong> {proc_avgs['AMD']['bulk_index']:.0f} ms</p>
                        <p><strong>Seq Index:</strong> {proc_avgs['AMD']['seq_index']:.0f} ms</p>
                        <p><strong>Search All:</strong> {proc_avgs['AMD']['search_all']:.0f} ms</p>
                        <p><strong>Search Term:</strong> {proc_avgs['AMD']['search_term']:.0f} ms</p>
                    </div>
                    <div class="stat-box graviton">
                        <h4 style="color: var(--graviton-color);">Graviton</h4>
                        <p><strong>Cold Start:</strong> {proc_avgs['Graviton']['cold_start']:.0f} ms</p>
                        <p><strong>Bulk Index:</strong> {proc_avgs['Graviton']['bulk_index']:.0f} ms</p>
                        <p><strong>Seq Index:</strong> {proc_avgs['Graviton']['seq_index']:.0f} ms</p>
                        <p><strong>Search All:</strong> {proc_avgs['Graviton']['search_all']:.0f} ms</p>
                        <p><strong>Search Term:</strong> {proc_avgs['Graviton']['search_term']:.0f} ms</p>
                    </div>
                </div>

                <div class="charts-grid">
                    <div class="chart-container">
                        <canvas id="processorColdStartChart"></canvas>
                    </div>
                    <div class="chart-container">
                        <canvas id="processorIndexChart"></canvas>
                    </div>
                </div>
            </div>
        </div>

        <!-- Generation Comparison -->
        <div class="card">
            <div class="card-header">
                <h2>Generation Comparison / 세대별 비교</h2>
            </div>
            <div class="card-body">
                <table>
                    <thead>
                        <tr>
                            <th>Generation / 세대</th>
                            <th>Instance Count</th>
                            <th>Avg Cold Start (ms)</th>
                            <th>Avg Bulk Index (ms)</th>
                            <th>Avg Seq Index (ms)</th>
                            <th>Cold Start vs 5th Gen</th>
                        </tr>
                    </thead>
                    <tbody>'''

    gen5_cold = gen_avgs[5]['cold_start'] if gen_avgs[5]['cold_start'] > 0 else 1
    for gen in [5, 6, 7, 8]:
        improvement = ((gen5_cold - gen_avgs[gen]['cold_start']) / gen5_cold * 100) if gen_avgs[gen]['cold_start'] > 0 else 0
        html += f'''
                        <tr>
                            <td>{gen}th Gen</td>
                            <td>{gen_avgs[gen]['count']}</td>
                            <td>{gen_avgs[gen]['cold_start']:.0f}</td>
                            <td>{gen_avgs[gen]['bulk_index']:.0f}</td>
                            <td>{gen_avgs[gen]['seq_index']:.0f}</td>
                            <td style="color: {'green' if improvement > 0 else 'gray'};">{'+' if improvement > 0 else ''}{improvement:.1f}%</td>
                        </tr>'''

    html += '''
                    </tbody>
                </table>

                <div class="charts-grid">
                    <div class="chart-container">
                        <canvas id="generationColdStartChart"></canvas>
                    </div>
                    <div class="chart-container">
                        <canvas id="generationIndexChart"></canvas>
                    </div>
                </div>
            </div>
        </div>

        <!-- Cold Start Chart -->
        <div class="card">
            <div class="card-header">
                <h2>Cold Start Time by Instance / 인스턴스별 Cold Start 시간</h2>
            </div>
            <div class="card-body">
                <p style="margin-bottom: 15px; color: #666;">Lower is better / 낮을수록 좋음</p>
                <div class="chart-container xlarge">
                    <canvas id="coldStartChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Bulk Index Chart -->
        <div class="card">
            <div class="card-header">
                <h2>Bulk Index Time (1000 docs) / 벌크 인덱싱 시간</h2>
            </div>
            <div class="card-body">
                <p style="margin-bottom: 15px; color: #666;">Lower is better / 낮을수록 좋음</p>
                <div class="chart-container xlarge">
                    <canvas id="bulkIndexChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Sequential Index Chart -->
        <div class="card">
            <div class="card-header">
                <h2>Sequential Index Time (100 docs) / 순차 인덱싱 시간</h2>
            </div>
            <div class="card-body">
                <p style="margin-bottom: 15px; color: #666;">Lower is better / 낮을수록 좋음</p>
                <div class="chart-container xlarge">
                    <canvas id="seqIndexChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Search Latency Chart -->
        <div class="card">
            <div class="card-header">
                <h2>Search Query Latency / 검색 쿼리 지연시간</h2>
            </div>
            <div class="card-body">
                <p style="margin-bottom: 15px; color: #666;">Lower is better / 낮을수록 좋음</p>
                <div class="chart-container xlarge">
                    <canvas id="searchLatencyChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Detailed Results Table -->
        <div class="card">
            <div class="card-header">
                <h2>Detailed Results - All Metrics / 상세 결과 - 모든 메트릭</h2>
            </div>
            <div class="card-body">
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Instance Type</th>
                                <th>Processor</th>
                                <th>Gen</th>
                                <th>Cold Start Avg (ms)</th>
                                <th>Cold Start Min</th>
                                <th>Cold Start Max</th>
                                <th>Std Dev</th>
                                <th>Bulk Index (ms)</th>
                                <th>Seq Index (ms)</th>
                                <th>Search All (ms)</th>
                                <th>Search Term (ms)</th>
                                <th>Runs</th>
                            </tr>
                        </thead>
                        <tbody>'''

    for rank, d in enumerate(instances_data, 1):
        row_class = ''
        if rank == 1:
            row_class = 'best'
        elif rank <= 3:
            row_class = 'top3'
        elif rank == len(instances_data):
            row_class = 'worst'

        proc_class = f'processor-{d["processor"].lower()}'

        html += f'''
                            <tr class="{row_class}">
                                <td>{rank}</td>
                                <td><strong>{d['instance']}</strong></td>
                                <td class="{proc_class}">{d['processor']}</td>
                                <td>{d['generation']}th</td>
                                <td>{d['cold_start']['avg']:.0f}</td>
                                <td>{d['cold_start']['min']:.0f}</td>
                                <td>{d['cold_start']['max']:.0f}</td>
                                <td>{d['cold_start']['std']:.1f}</td>
                                <td>{d['bulk_index']['avg']:.0f}</td>
                                <td>{d['seq_index']['avg']:.0f}</td>
                                <td>{d['search_all']['avg']:.0f}</td>
                                <td>{d['search_term']['avg']:.0f}</td>
                                <td>{d['runs']}</td>
                            </tr>'''

    html += '''
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Top Performers -->
        <div class="card">
            <div class="card-header">
                <h2>Top Performers by Metric / 메트릭별 최고 성능</h2>
            </div>
            <div class="card-body">
                <div class="charts-grid">
                    <div>
                        <h3 style="margin-bottom: 15px;">Best Cold Start (Top 10)</h3>
                        <table>
                            <thead>
                                <tr><th>Rank</th><th>Instance</th><th>Processor</th><th>Time (ms)</th></tr>
                            </thead>
                            <tbody>'''

    for i, d in enumerate(instances_data[:10], 1):
        proc_class = f'processor-{d["processor"].lower()}'
        html += f'''
                                <tr>
                                    <td>{i}</td>
                                    <td><strong>{d['instance']}</strong></td>
                                    <td class="{proc_class}">{d['processor']}</td>
                                    <td>{d['cold_start']['avg']:.0f}</td>
                                </tr>'''

    html += '''
                            </tbody>
                        </table>
                    </div>
                    <div>
                        <h3 style="margin-bottom: 15px;">Best Bulk Index (Top 10)</h3>
                        <table>
                            <thead>
                                <tr><th>Rank</th><th>Instance</th><th>Processor</th><th>Time (ms)</th></tr>
                            </thead>
                            <tbody>'''

    bulk_top10 = sorted(instances_data, key=lambda x: x['bulk_index']['avg'] if x['bulk_index']['avg'] > 0 else float('inf'))[:10]
    for i, d in enumerate(bulk_top10, 1):
        proc_class = f'processor-{d["processor"].lower()}'
        html += f'''
                                <tr>
                                    <td>{i}</td>
                                    <td><strong>{d['instance']}</strong></td>
                                    <td class="{proc_class}">{d['processor']}</td>
                                    <td>{d['bulk_index']['avg']:.0f}</td>
                                </tr>'''

    html += '''
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="charts-grid" style="margin-top: 30px;">
                    <div>
                        <h3 style="margin-bottom: 15px;">Best Sequential Index (Top 10)</h3>
                        <table>
                            <thead>
                                <tr><th>Rank</th><th>Instance</th><th>Processor</th><th>Time (ms)</th></tr>
                            </thead>
                            <tbody>'''

    seq_top10 = sorted(instances_data, key=lambda x: x['seq_index']['avg'] if x['seq_index']['avg'] > 0 else float('inf'))[:10]
    for i, d in enumerate(seq_top10, 1):
        proc_class = f'processor-{d["processor"].lower()}'
        html += f'''
                                <tr>
                                    <td>{i}</td>
                                    <td><strong>{d['instance']}</strong></td>
                                    <td class="{proc_class}">{d['processor']}</td>
                                    <td>{d['seq_index']['avg']:.0f}</td>
                                </tr>'''

    html += '''
                            </tbody>
                        </table>
                    </div>
                    <div>
                        <h3 style="margin-bottom: 15px;">Best Search Latency (Top 10)</h3>
                        <table>
                            <thead>
                                <tr><th>Rank</th><th>Instance</th><th>Processor</th><th>Match All (ms)</th><th>Term (ms)</th></tr>
                            </thead>
                            <tbody>'''

    search_top10 = sorted(instances_data, key=lambda x: x['search_all']['avg'] if x['search_all']['avg'] > 0 else float('inf'))[:10]
    for i, d in enumerate(search_top10, 1):
        proc_class = f'processor-{d["processor"].lower()}'
        html += f'''
                                <tr>
                                    <td>{i}</td>
                                    <td><strong>{d['instance']}</strong></td>
                                    <td class="{proc_class}">{d['processor']}</td>
                                    <td>{d['search_all']['avg']:.0f}</td>
                                    <td>{d['search_term']['avg']:.0f}</td>
                                </tr>'''

    html += '''
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- Key Insights -->
        <div class="card">
            <div class="card-header">
                <h2>Key Insights / 주요 인사이트</h2>
            </div>
            <div class="card-body">
                <div class="highlight-box">
                    <h4>Performance Highlights / 성능 하이라이트</h4>
                    <ul>'''

    # Calculate improvement percentages
    graviton_vs_intel_cold = ((proc_avgs['Intel']['cold_start'] - proc_avgs['Graviton']['cold_start']) / proc_avgs['Intel']['cold_start'] * 100) if proc_avgs['Intel']['cold_start'] > 0 else 0
    graviton_vs_intel_bulk = ((proc_avgs['Intel']['bulk_index'] - proc_avgs['Graviton']['bulk_index']) / proc_avgs['Intel']['bulk_index'] * 100) if proc_avgs['Intel']['bulk_index'] > 0 else 0
    gen8_vs_gen5_cold = ((gen_avgs[5]['cold_start'] - gen_avgs[8]['cold_start']) / gen_avgs[5]['cold_start'] * 100) if gen_avgs[5]['cold_start'] > 0 else 0

    html += f'''
                        <li><strong>Best Overall:</strong> {best_cold_start['instance']} with {best_cold_start['cold_start']['avg']:.0f}ms cold start / 최고 성능: {best_cold_start['instance']}</li>
                        <li><strong>Graviton vs Intel (Cold Start):</strong> {abs(graviton_vs_intel_cold):.1f}% {'faster' if graviton_vs_intel_cold > 0 else 'slower'} / Graviton이 Intel보다 {abs(graviton_vs_intel_cold):.1f}% {'빠름' if graviton_vs_intel_cold > 0 else '느림'}</li>
                        <li><strong>Graviton vs Intel (Bulk Index):</strong> {abs(graviton_vs_intel_bulk):.1f}% {'faster' if graviton_vs_intel_bulk > 0 else 'slower'} / Graviton이 Intel보다 {abs(graviton_vs_intel_bulk):.1f}% {'빠름' if graviton_vs_intel_bulk > 0 else '느림'}</li>
                        <li><strong>8th Gen vs 5th Gen (Cold Start):</strong> {abs(gen8_vs_gen5_cold):.1f}% improvement / 8세대가 5세대보다 {abs(gen8_vs_gen5_cold):.1f}% 향상</li>
                        <li><strong>Best for Cold Start:</strong> 8th Gen Graviton (c8g, m8g, r8g) / Cold Start 최적: 8세대 Graviton</li>
                        <li><strong>Best for Indexing:</strong> 8th Gen instances / 인덱싱 최적: 8세대 인스턴스</li>
                    </ul>
                </div>
            </div>
        </div>

        <footer>
            <p>EKS EC2 Node Benchmark - Elasticsearch Performance Test</p>
            <p>All tests run with 4 vCPU (xlarge) instances, 5 runs each with node isolation</p>
            <p>Elasticsearch version: 8.11.0 | JVM: OpenJDK 21</p>
        </footer>
    </div>

    <script>
        // Chart colors
        const intelColor = 'rgba(0, 114, 198, 0.8)';
        const amdColor = 'rgba(237, 28, 36, 0.8)';
        const gravitonColor = 'rgba(255, 153, 0, 0.8)';

        // Cold Start Chart Data
        const coldStartLabels = ''' + json.dumps([d[0] for d in cold_start_data]) + ''';
        const coldStartValues = ''' + json.dumps([d[1] for d in cold_start_data]) + ''';
        const coldStartColors = ''' + json.dumps([d[2] for d in cold_start_data]) + ''';

        new Chart(document.getElementById('coldStartChart'), {
            type: 'bar',
            data: {
                labels: coldStartLabels,
                datasets: [{
                    label: 'Cold Start Time (ms)',
                    data: coldStartValues,
                    backgroundColor: coldStartColors,
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Cold Start Time by Instance (Lower is Better)' }
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Time (ms)' } },
                    x: { ticks: { maxRotation: 90, minRotation: 45 } }
                }
            }
        });

        // Bulk Index Chart Data
        const bulkLabels = ''' + json.dumps([d[0] for d in bulk_data]) + ''';
        const bulkValues = ''' + json.dumps([d[1] for d in bulk_data]) + ''';
        const bulkColors = ''' + json.dumps([d[2] for d in bulk_data]) + ''';

        new Chart(document.getElementById('bulkIndexChart'), {
            type: 'bar',
            data: {
                labels: bulkLabels,
                datasets: [{
                    label: 'Bulk Index Time (ms)',
                    data: bulkValues,
                    backgroundColor: bulkColors,
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Bulk Index 1000 Documents Time (Lower is Better)' }
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Time (ms)' } },
                    x: { ticks: { maxRotation: 90, minRotation: 45 } }
                }
            }
        });

        // Sequential Index Chart Data
        const seqLabels = ''' + json.dumps([d[0] for d in seq_data]) + ''';
        const seqValues = ''' + json.dumps([d[1] for d in seq_data]) + ''';
        const seqColors = ''' + json.dumps([d[2] for d in seq_data]) + ''';

        new Chart(document.getElementById('seqIndexChart'), {
            type: 'bar',
            data: {
                labels: seqLabels,
                datasets: [{
                    label: 'Sequential Index Time (ms)',
                    data: seqValues,
                    backgroundColor: seqColors,
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Sequential Index 100 Documents Time (Lower is Better)' }
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Time (ms)' } },
                    x: { ticks: { maxRotation: 90, minRotation: 45 } }
                }
            }
        });

        // Search Latency Chart Data
        const searchLabels = ''' + json.dumps([d[0] for d in search_data]) + ''';
        const searchAllValues = ''' + json.dumps([d[1] for d in search_data]) + ''';
        const searchTermValues = ''' + json.dumps([d[2] for d in search_data]) + ''';
        const searchColors = ''' + json.dumps([d[3] for d in search_data]) + ''';

        new Chart(document.getElementById('searchLatencyChart'), {
            type: 'bar',
            data: {
                labels: searchLabels,
                datasets: [{
                    label: 'Match All Query (ms)',
                    data: searchAllValues,
                    backgroundColor: 'rgba(94, 53, 177, 0.7)',
                    borderWidth: 1
                }, {
                    label: 'Term Query (ms)',
                    data: searchTermValues,
                    backgroundColor: 'rgba(156, 39, 176, 0.5)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: 'Search Query Latency (Lower is Better)' }
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Time (ms)' } },
                    x: { ticks: { maxRotation: 90, minRotation: 45 } }
                }
            }
        });

        // Processor Cold Start Chart
        new Chart(document.getElementById('processorColdStartChart'), {
            type: 'bar',
            data: {
                labels: ['Intel', 'AMD', 'Graviton'],
                datasets: [{
                    label: 'Average Cold Start (ms)',
                    data: [''' + str(proc_avgs['Intel']['cold_start']) + ''', ''' + str(proc_avgs['AMD']['cold_start']) + ''', ''' + str(proc_avgs['Graviton']['cold_start']) + '''],
                    backgroundColor: [intelColor, amdColor, gravitonColor],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: 'Average Cold Start by Processor Type' }
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Time (ms)' } }
                }
            }
        });

        // Processor Index Chart
        new Chart(document.getElementById('processorIndexChart'), {
            type: 'bar',
            data: {
                labels: ['Intel', 'AMD', 'Graviton'],
                datasets: [{
                    label: 'Bulk Index (ms)',
                    data: [''' + str(proc_avgs['Intel']['bulk_index']) + ''', ''' + str(proc_avgs['AMD']['bulk_index']) + ''', ''' + str(proc_avgs['Graviton']['bulk_index']) + '''],
                    backgroundColor: [intelColor, amdColor, gravitonColor],
                    borderWidth: 1
                }, {
                    label: 'Sequential Index (ms)',
                    data: [''' + str(proc_avgs['Intel']['seq_index']) + ''', ''' + str(proc_avgs['AMD']['seq_index']) + ''', ''' + str(proc_avgs['Graviton']['seq_index']) + '''],
                    backgroundColor: ['rgba(0, 114, 198, 0.5)', 'rgba(237, 28, 36, 0.5)', 'rgba(255, 153, 0, 0.5)'],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: 'Indexing Performance by Processor Type' }
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Time (ms)' } }
                }
            }
        });

        // Generation Cold Start Chart
        new Chart(document.getElementById('generationColdStartChart'), {
            type: 'bar',
            data: {
                labels: ['5th Gen', '6th Gen', '7th Gen', '8th Gen'],
                datasets: [{
                    label: 'Average Cold Start (ms)',
                    data: [''' + str(gen_avgs[5]['cold_start']) + ''', ''' + str(gen_avgs[6]['cold_start']) + ''', ''' + str(gen_avgs[7]['cold_start']) + ''', ''' + str(gen_avgs[8]['cold_start']) + '''],
                    backgroundColor: [
                        'rgba(102, 126, 234, 0.8)',
                        'rgba(118, 75, 162, 0.8)',
                        'rgba(237, 137, 54, 0.8)',
                        'rgba(46, 213, 115, 0.8)'
                    ],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: 'Average Cold Start by Generation' }
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Time (ms)' } }
                }
            }
        });

        // Generation Index Chart
        new Chart(document.getElementById('generationIndexChart'), {
            type: 'bar',
            data: {
                labels: ['5th Gen', '6th Gen', '7th Gen', '8th Gen'],
                datasets: [{
                    label: 'Bulk Index (ms)',
                    data: [''' + str(gen_avgs[5]['bulk_index']) + ''', ''' + str(gen_avgs[6]['bulk_index']) + ''', ''' + str(gen_avgs[7]['bulk_index']) + ''', ''' + str(gen_avgs[8]['bulk_index']) + '''],
                    backgroundColor: [
                        'rgba(102, 126, 234, 0.8)',
                        'rgba(118, 75, 162, 0.8)',
                        'rgba(237, 137, 54, 0.8)',
                        'rgba(46, 213, 115, 0.8)'
                    ],
                    borderWidth: 1
                }, {
                    label: 'Sequential Index (ms)',
                    data: [''' + str(gen_avgs[5]['seq_index']) + ''', ''' + str(gen_avgs[6]['seq_index']) + ''', ''' + str(gen_avgs[7]['seq_index']) + ''', ''' + str(gen_avgs[8]['seq_index']) + '''],
                    backgroundColor: [
                        'rgba(102, 126, 234, 0.5)',
                        'rgba(118, 75, 162, 0.5)',
                        'rgba(237, 137, 54, 0.5)',
                        'rgba(46, 213, 115, 0.5)'
                    ],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: 'Indexing Performance by Generation' }
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Time (ms)' } }
                }
            }
        });
    </script>
</body>
</html>'''

    return html

def main():
    print("Parsing Elasticsearch benchmark results...")
    results = parse_all_results()
    print(f"Found {len(results)} instances with results")

    print("Generating HTML report...")
    html = generate_html(results)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, 'w') as f:
        f.write(html)

    print(f"Report generated: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
