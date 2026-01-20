#!/usr/bin/env python3
"""
Redis Benchmark Report Generator v2
Creates detailed HTML report with generation comparison charts
"""

import os
import json
from pathlib import Path

RESULTS_DIR = Path("/home/ec2-user/benchmark/results/redis")
OUTPUT_FILE = RESULTS_DIR / "report.html"

def load_data():
    """Load benchmark data from JSON"""
    with open(RESULTS_DIR / "report-data.json", 'r') as f:
        return json.load(f)

def get_m_series_instances():
    """Get M-series instances for generation comparison"""
    return {
        'm5.xlarge': {'gen': '5th', 'arch': 'Intel', 'color': '#1976D2'},
        'm6i.xlarge': {'gen': '6th', 'arch': 'Intel', 'color': '#2196F3'},
        'm6g.xlarge': {'gen': '6th', 'arch': 'Graviton2', 'color': '#FF9800'},
        'm7i.xlarge': {'gen': '7th', 'arch': 'Intel', 'color': '#42A5F5'},
        'm7g.xlarge': {'gen': '7th', 'arch': 'Graviton3', 'color': '#FFC107'},
        'm8i.xlarge': {'gen': '8th', 'arch': 'Intel', 'color': '#64B5F6'},
        'm8g.xlarge': {'gen': '8th', 'arch': 'Graviton4', 'color': '#FFEB3B'},
    }

def generate_html(data):
    """Generate detailed HTML report"""
    m_series = get_m_series_instances()
    metrics = ['SET', 'GET', 'INCR', 'LPUSH', 'HSET']

    # Extract M-series data
    m_data = {}
    for inst, info in m_series.items():
        if inst in data:
            m_data[inst] = {
                'info': info,
                'standard': data[inst].get('standard', {}),
                'pipeline': data[inst].get('pipeline', {}),
                'high_concurrency': data[inst].get('high_concurrency', {})
            }

    # Find top performers
    def find_best(section, metric):
        best_inst = None
        best_val = 0
        for inst, d in data.items():
            val = d.get(section, {}).get(metric, 0)
            if val > best_val:
                best_val = val
                best_inst = inst
        return best_inst, best_val

    # Instance categorization
    categories = {
        'Intel 5th': ['c5.xlarge', 'c5d.xlarge', 'c5n.xlarge', 'm5.xlarge', 'm5d.xlarge', 'm5zn.xlarge',
                      'r5.xlarge', 'r5b.xlarge', 'r5d.xlarge', 'r5dn.xlarge', 'r5n.xlarge'],
        'Intel 6th': ['c6i.xlarge', 'c6id.xlarge', 'c6in.xlarge', 'm6i.xlarge', 'm6id.xlarge',
                      'm6idn.xlarge', 'm6in.xlarge', 'r6i.xlarge', 'r6id.xlarge'],
        'Intel 7th': ['c7i.xlarge', 'c7i-flex.xlarge', 'm7i.xlarge', 'm7i-flex.xlarge', 'r7i.xlarge'],
        'Intel 8th': ['c8i.xlarge', 'c8i-flex.xlarge', 'm8i.xlarge', 'r8i.xlarge', 'r8i-flex.xlarge'],
        'AMD': ['c5a.xlarge', 'm5a.xlarge', 'm5ad.xlarge', 'r5a.xlarge', 'r5ad.xlarge'],
        'Graviton2': ['c6g.xlarge', 'c6gd.xlarge', 'c6gn.xlarge', 'm6g.xlarge', 'm6gd.xlarge',
                      'r6g.xlarge', 'r6gd.xlarge'],
        'Graviton3': ['c7g.xlarge', 'c7gd.xlarge', 'm7g.xlarge', 'm7gd.xlarge', 'r7g.xlarge', 'r7gd.xlarge'],
        'Graviton4': ['c8g.xlarge', 'm8g.xlarge', 'r8g.xlarge']
    }

    html = '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Redis Benchmark Report - 51 EC2 Instance Types</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans KR', sans-serif;
            background: #f8fafc;
            color: #1e293b;
            line-height: 1.6;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }

        /* Header */
        .header {
            background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
            color: white;
            padding: 40px 20px;
            text-align: center;
            margin-bottom: 30px;
            border-radius: 12px;
        }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .header p { opacity: 0.9; font-size: 1.1em; }

        /* Summary Cards */
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .summary-card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            text-align: center;
        }
        .summary-card h4 { color: #64748b; font-size: 14px; margin-bottom: 10px; text-transform: uppercase; }
        .summary-card .value { font-size: 32px; font-weight: 700; color: #dc2626; }
        .summary-card .instance { font-size: 14px; color: #94a3b8; margin-top: 8px; }
        .summary-card .category {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            margin-top: 8px;
        }
        .cat-intel { background: #dbeafe; color: #1d4ed8; }
        .cat-graviton { background: #fef3c7; color: #d97706; }
        .cat-amd { background: #fee2e2; color: #dc2626; }

        /* Section */
        .section {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        }
        .section h2 {
            font-size: 1.5em;
            color: #1e293b;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #f1f5f9;
        }
        .section h3 { font-size: 1.2em; color: #475569; margin: 25px 0 15px 0; }

        /* Charts */
        .chart-container {
            height: 400px;
            margin-bottom: 30px;
            position: relative;
        }
        .chart-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
        }
        @media (max-width: 900px) {
            .chart-row { grid-template-columns: 1fr; }
        }

        /* Legend */
        .legend {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-bottom: 25px;
            padding: 15px;
            background: #f8fafc;
            border-radius: 8px;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
        }
        .legend-color {
            width: 16px;
            height: 16px;
            border-radius: 4px;
        }

        /* Table */
        .table-container { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        th, td {
            padding: 12px 10px;
            text-align: right;
            border-bottom: 1px solid #e2e8f0;
        }
        th {
            background: #f8fafc;
            font-weight: 600;
            color: #475569;
            position: sticky;
            top: 0;
        }
        th:first-child, td:first-child { text-align: left; font-weight: 500; }
        tr:hover { background: #f8fafc; }
        .best { background: #dcfce7 !important; color: #166534; font-weight: 600; }

        /* Category badges */
        .cat-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
        }
        .intel-5 { background: #bfdbfe; color: #1e40af; }
        .intel-6 { background: #93c5fd; color: #1e40af; }
        .intel-7 { background: #60a5fa; color: white; }
        .intel-8 { background: #3b82f6; color: white; }
        .amd { background: #fecaca; color: #991b1b; }
        .graviton-2 { background: #fed7aa; color: #9a3412; }
        .graviton-3 { background: #fcd34d; color: #92400e; }
        .graviton-4 { background: #fde047; color: #854d0e; }

        /* Insight box */
        .insight {
            background: #fef3c7;
            border-left: 4px solid #f59e0b;
            padding: 15px 20px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
        }
        .insight h4 { color: #92400e; margin-bottom: 8px; }
        .insight ul { margin-left: 20px; color: #78350f; }

        /* Navigation */
        .nav {
            position: fixed;
            top: 20px;
            right: 20px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 100;
        }
        .nav a {
            display: block;
            padding: 5px 0;
            color: #3b82f6;
            text-decoration: none;
            font-size: 13px;
        }
        .nav a:hover { text-decoration: underline; }
        @media (max-width: 1200px) { .nav { display: none; } }

        /* Methodology */
        .method-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        .method-item {
            background: #f8fafc;
            padding: 15px;
            border-radius: 8px;
        }
        .method-item strong { color: #475569; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔴 Redis Benchmark Report</h1>
            <p>51 EC2 Instance Types (xlarge, 4 vCPU) × 5 Runs | redis-benchmark</p>
        </div>

        <nav class="nav">
            <strong>Quick Nav</strong>
            <a href="#summary">Top Performers</a>
            <a href="#generation">Generation Compare</a>
            <a href="#standard">Standard Results</a>
            <a href="#pipeline">Pipeline Results</a>
            <a href="#highconc">High Concurrency</a>
            <a href="#methodology">Methodology</a>
        </nav>
'''

    # Summary section
    html += '<div class="summary-grid" id="summary">'
    for metric in ['SET', 'GET', 'LPUSH', 'HSET']:
        best_inst, best_val = find_best('standard', metric)
        if best_inst and best_inst in data:
            cat = data[best_inst]['category']
            cat_class = 'cat-graviton' if 'Graviton' in cat else ('cat-amd' if 'AMD' in cat else 'cat-intel')
            html += f'''
            <div class="summary-card">
                <h4>{metric} (Standard)</h4>
                <div class="value">{best_val:,.0f}</div>
                <div class="instance">{best_inst}</div>
                <span class="category {cat_class}">{cat}</span>
            </div>'''
    html += '</div>'

    # Generation Comparison Section
    html += '''
        <div class="section" id="generation">
            <h2>📊 Generation Comparison (M-series)</h2>
            <p style="color: #64748b; margin-bottom: 20px;">
                M-series 인스턴스를 기준으로 세대별/아키텍처별 Redis 성능 비교
            </p>

            <div class="legend">
                <div class="legend-item"><div class="legend-color" style="background: #1976D2;"></div> m5 (Intel 5th)</div>
                <div class="legend-item"><div class="legend-color" style="background: #2196F3;"></div> m6i (Intel 6th)</div>
                <div class="legend-item"><div class="legend-color" style="background: #FF9800;"></div> m6g (Graviton2)</div>
                <div class="legend-item"><div class="legend-color" style="background: #42A5F5;"></div> m7i (Intel 7th)</div>
                <div class="legend-item"><div class="legend-color" style="background: #FFC107;"></div> m7g (Graviton3)</div>
                <div class="legend-item"><div class="legend-color" style="background: #64B5F6;"></div> m8i (Intel 8th)</div>
                <div class="legend-item"><div class="legend-color" style="background: #FFEB3B;"></div> m8g (Graviton4)</div>
            </div>
'''

    # Chart data for M-series
    m_instances = ['m5.xlarge', 'm6i.xlarge', 'm6g.xlarge', 'm7i.xlarge', 'm7g.xlarge', 'm8i.xlarge', 'm8g.xlarge']
    m_colors = ['#1976D2', '#2196F3', '#FF9800', '#42A5F5', '#FFC107', '#64B5F6', '#FFEB3B']
    m_labels = ['m5 (5th)', 'm6i (6th)', 'm6g (G2)', 'm7i (7th)', 'm7g (G3)', 'm8i (8th)', 'm8g (G4)']

    # Charts for each metric
    for i, metric in enumerate(metrics):
        std_vals = [data.get(inst, {}).get('standard', {}).get(metric, 0) for inst in m_instances]
        pipe_vals = [data.get(inst, {}).get('pipeline', {}).get(metric, 0) for inst in m_instances]

        html += f'''
            <h3>{metric} Performance</h3>
            <div class="chart-row">
                <div class="chart-container">
                    <canvas id="chart_{metric}_std"></canvas>
                </div>
                <div class="chart-container">
                    <canvas id="chart_{metric}_pipe"></canvas>
                </div>
            </div>
'''

    # Insight box
    html += '''
            <div class="insight">
                <h4>💡 Key Insights</h4>
                <ul>
                    <li><strong>Intel 6th (m6i)</strong>가 Redis Standard 벤치마크에서 가장 높은 성능</li>
                    <li><strong>Graviton3 (m7g)</strong>가 ARM 아키텍처 중 최고 성능</li>
                    <li>Pipeline 모드에서는 <strong>Intel 8th (m8i)</strong>가 SET/GET에서 우수</li>
                    <li>Redis는 싱글스레드 특성상 클럭 속도와 메모리 레이턴시가 중요</li>
                </ul>
            </div>
        </div>
'''

    # Standard Benchmark Table
    html += '''
        <div class="section" id="standard">
            <h2>📋 Standard Benchmark Results (50 clients, 100K requests)</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Instance</th>
                            <th>Category</th>
                            <th>SET</th>
                            <th>GET</th>
                            <th>INCR</th>
                            <th>LPUSH</th>
                            <th>RPUSH</th>
                            <th>LPOP</th>
                            <th>SADD</th>
                            <th>HSET</th>
                            <th>MSET</th>
                        </tr>
                    </thead>
                    <tbody>
'''

    # Find best for each metric
    best_standard = {}
    for metric in ['SET', 'GET', 'INCR', 'LPUSH', 'RPUSH', 'LPOP', 'SADD', 'HSET', 'MSET']:
        best_standard[metric] = find_best('standard', metric)[0]

    # Sort instances by category
    category_order = ['Intel 5th', 'Intel 6th', 'Intel 7th', 'Intel 8th', 'AMD', 'Graviton2', 'Graviton3', 'Graviton4']
    sorted_instances = sorted(data.keys(), key=lambda x: (
        category_order.index(data[x]['category']) if data[x]['category'] in category_order else 99,
        x
    ))

    for inst in sorted_instances:
        d = data[inst]
        cat = d['category']
        cat_class = cat.lower().replace(' ', '-').replace('graviton', 'graviton-')
        if 'intel' in cat_class:
            cat_class = f"intel-{cat_class[-1]}"

        html += f'<tr><td><strong>{inst}</strong></td>'
        html += f'<td><span class="cat-badge {cat_class}">{cat}</span></td>'

        for metric in ['SET', 'GET', 'INCR', 'LPUSH', 'RPUSH', 'LPOP', 'SADD', 'HSET', 'MSET']:
            val = d.get('standard', {}).get(metric, 0)
            is_best = inst == best_standard.get(metric)
            cell_class = 'best' if is_best else ''
            html += f'<td class="{cell_class}">{val:,.0f}</td>'
        html += '</tr>'

    html += '''
                    </tbody>
                </table>
            </div>
        </div>
'''

    # Pipeline Benchmark Table
    html += '''
        <div class="section" id="pipeline">
            <h2>⚡ Pipeline Benchmark Results (16 commands per pipeline)</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Instance</th>
                            <th>Category</th>
                            <th>SET</th>
                            <th>GET</th>
                            <th>INCR</th>
                            <th>LPUSH</th>
                            <th>RPUSH</th>
                            <th>SADD</th>
                            <th>HSET</th>
                        </tr>
                    </thead>
                    <tbody>
'''

    best_pipeline = {}
    for metric in ['SET', 'GET', 'INCR', 'LPUSH', 'RPUSH', 'SADD', 'HSET']:
        best_pipeline[metric] = find_best('pipeline', metric)[0]

    for inst in sorted_instances:
        d = data[inst]
        cat = d['category']
        cat_class = cat.lower().replace(' ', '-').replace('graviton', 'graviton-')
        if 'intel' in cat_class:
            cat_class = f"intel-{cat_class[-1]}"

        html += f'<tr><td><strong>{inst}</strong></td>'
        html += f'<td><span class="cat-badge {cat_class}">{cat}</span></td>'

        for metric in ['SET', 'GET', 'INCR', 'LPUSH', 'RPUSH', 'SADD', 'HSET']:
            val = d.get('pipeline', {}).get(metric, 0)
            is_best = inst == best_pipeline.get(metric)
            cell_class = 'best' if is_best else ''
            html += f'<td class="{cell_class}">{val:,.0f}</td>'
        html += '</tr>'

    html += '''
                    </tbody>
                </table>
            </div>
        </div>
'''

    # High Concurrency Table
    html += '''
        <div class="section" id="highconc">
            <h2>🔥 High Concurrency Results (100 clients, 200K requests)</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Instance</th>
                            <th>Category</th>
                            <th>SET</th>
                            <th>GET</th>
                            <th>INCR</th>
                            <th>LPUSH</th>
                            <th>HSET</th>
                        </tr>
                    </thead>
                    <tbody>
'''

    best_highconc = {}
    for metric in ['SET', 'GET', 'INCR', 'LPUSH', 'HSET']:
        best_highconc[metric] = find_best('high_concurrency', metric)[0]

    for inst in sorted_instances:
        d = data[inst]
        cat = d['category']
        cat_class = cat.lower().replace(' ', '-').replace('graviton', 'graviton-')
        if 'intel' in cat_class:
            cat_class = f"intel-{cat_class[-1]}"

        html += f'<tr><td><strong>{inst}</strong></td>'
        html += f'<td><span class="cat-badge {cat_class}">{cat}</span></td>'

        for metric in ['SET', 'GET', 'INCR', 'LPUSH', 'HSET']:
            val = d.get('high_concurrency', {}).get(metric, 0)
            is_best = inst == best_highconc.get(metric)
            cell_class = 'best' if is_best else ''
            html += f'<td class="{cell_class}">{val:,.0f}</td>'
        html += '</tr>'

    html += '''
                    </tbody>
                </table>
            </div>
        </div>
'''

    # Methodology Section
    html += '''
        <div class="section" id="methodology">
            <h2>📝 Test Methodology</h2>
            <div class="method-grid">
                <div class="method-item">
                    <strong>Standard Test</strong><br>
                    50 clients, 100,000 requests
                </div>
                <div class="method-item">
                    <strong>Pipeline Test</strong><br>
                    16 commands per pipeline
                </div>
                <div class="method-item">
                    <strong>High Concurrency</strong><br>
                    100 clients, 200,000 requests
                </div>
                <div class="method-item">
                    <strong>Runs</strong><br>
                    5 runs per instance, averaged
                </div>
                <div class="method-item">
                    <strong>Redis Version</strong><br>
                    7.x (Alpine image)
                </div>
                <div class="method-item">
                    <strong>Instance Size</strong><br>
                    xlarge (4 vCPU)
                </div>
            </div>
            <p style="margin-top: 20px; color: #64748b;">
                <strong>Generated:</strong> ''' + f'{len(data)} instances tested' + '''
            </p>
        </div>
    </div>
'''

    # Chart.js Scripts
    html += '''
    <script>
        const mLabels = ''' + json.dumps(m_labels) + ''';
        const mColors = ''' + json.dumps(m_colors) + ''';
'''

    for metric in metrics:
        std_vals = [data.get(inst, {}).get('standard', {}).get(metric, 0) for inst in m_instances]
        pipe_vals = [data.get(inst, {}).get('pipeline', {}).get(metric, 0) for inst in m_instances]

        html += f'''
        // {metric} Standard Chart
        new Chart(document.getElementById('chart_{metric}_std'), {{
            type: 'bar',
            data: {{
                labels: mLabels,
                datasets: [{{
                    label: '{metric} (Standard)',
                    data: {std_vals},
                    backgroundColor: mColors
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    title: {{ display: true, text: '{metric} - Standard (50 clients)', font: {{ size: 14 }} }},
                    legend: {{ display: false }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        title: {{ display: true, text: 'req/sec' }},
                        ticks: {{ callback: v => v.toLocaleString() }}
                    }}
                }}
            }}
        }});

        // {metric} Pipeline Chart
        new Chart(document.getElementById('chart_{metric}_pipe'), {{
            type: 'bar',
            data: {{
                labels: mLabels,
                datasets: [{{
                    label: '{metric} (Pipeline)',
                    data: {pipe_vals},
                    backgroundColor: mColors
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    title: {{ display: true, text: '{metric} - Pipeline (16 cmds)', font: {{ size: 14 }} }},
                    legend: {{ display: false }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        title: {{ display: true, text: 'req/sec' }},
                        ticks: {{ callback: v => v.toLocaleString() }}
                    }}
                }}
            }}
        }});
'''

    html += '''
    </script>
</body>
</html>
'''

    return html

def main():
    print("Loading Redis benchmark data...")
    data = load_data()
    print(f"Found {len(data)} instances")

    print("Generating HTML report...")
    html = generate_html(data)

    with open(OUTPUT_FILE, 'w') as f:
        f.write(html)

    print(f"Report saved to {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
