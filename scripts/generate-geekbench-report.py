#!/usr/bin/env python3
"""Geekbench 6 벤치마크 결과 리포트 생성"""

import csv
import os
from collections import defaultdict
from datetime import datetime

# AWS 온디맨드 가격 (ap-northeast-2, xlarge, USD/hour)
PRICES = {
    'c5.xlarge': 0.192, 'c5a.xlarge': 0.172, 'c5d.xlarge': 0.218, 'c5n.xlarge': 0.244,
    'c6g.xlarge': 0.154, 'c6gd.xlarge': 0.185, 'c6gn.xlarge': 0.194, 'c6i.xlarge': 0.192,
    'c6id.xlarge': 0.240, 'c6in.xlarge': 0.252, 'c7g.xlarge': 0.162, 'c7gd.xlarge': 0.193,
    'c7i.xlarge': 0.201, 'c7i-flex.xlarge': 0.181, 'c8g.xlarge': 0.170, 'c8i.xlarge': 0.211,
    'c8i-flex.xlarge': 0.190,
    'm5.xlarge': 0.216, 'm5a.xlarge': 0.194, 'm5ad.xlarge': 0.234, 'm5d.xlarge': 0.254,
    'm5zn.xlarge': 0.367, 'm6g.xlarge': 0.173, 'm6gd.xlarge': 0.208, 'm6i.xlarge': 0.216,
    'm6id.xlarge': 0.270, 'm6in.xlarge': 0.284, 'm6idn.xlarge': 0.338, 'm7g.xlarge': 0.182,
    'm7gd.xlarge': 0.217, 'm7i.xlarge': 0.226, 'm7i-flex.xlarge': 0.204, 'm8g.xlarge': 0.191,
    'm8i.xlarge': 0.238,
    'r5.xlarge': 0.284, 'r5a.xlarge': 0.256, 'r5ad.xlarge': 0.296, 'r5b.xlarge': 0.340,
    'r5d.xlarge': 0.324, 'r5dn.xlarge': 0.380, 'r5n.xlarge': 0.340, 'r6g.xlarge': 0.227,
    'r6gd.xlarge': 0.273, 'r6i.xlarge': 0.284, 'r6id.xlarge': 0.355, 'r7g.xlarge': 0.238,
    'r7gd.xlarge': 0.284, 'r7i.xlarge': 0.298, 'r8g.xlarge': 0.250, 'r8i.xlarge': 0.313,
    'r8i-flex.xlarge': 0.282
}

def get_arch(instance):
    return 'Graviton' if 'g.' in instance or 'gd.' in instance or 'gn.' in instance else 'Intel' if 'a.' not in instance and 'ad.' not in instance else 'AMD'

def get_gen(instance):
    if instance.startswith(('c8', 'm8', 'r8')): return 8
    if instance.startswith(('c7', 'm7', 'r7')): return 7
    if instance.startswith(('c6', 'm6', 'r6')): return 6
    return 5

def get_family(instance):
    if instance.startswith('c'): return 'C (Compute)'
    if instance.startswith('m'): return 'M (General)'
    return 'R (Memory)'

def load_data(csv_path):
    """CSV에서 데이터 로드하고 인스턴스별 평균 계산"""
    data = defaultdict(lambda: {'single': [], 'multi': []})

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            inst = row['instance']
            single = int(row['single_core']) if row['single_core'] else 0
            multi = int(row['multi_core']) if row['multi_core'] else 0
            if single > 0 and multi > 0:
                data[inst]['single'].append(single)
                data[inst]['multi'].append(multi)

    results = []
    for inst, scores in data.items():
        if scores['single'] and scores['multi']:
            single_avg = sum(scores['single']) / len(scores['single'])
            multi_avg = sum(scores['multi']) / len(scores['multi'])
            results.append({
                'instance': inst,
                'single_core': round(single_avg),
                'multi_core': round(multi_avg),
                'runs': len(scores['single']),
                'arch': get_arch(inst),
                'gen': get_gen(inst),
                'family': get_family(inst),
                'price': PRICES.get(inst, 0.2)
            })

    # 가성비 계산 (멀티코어 점수 / 시간당 가격)
    for r in results:
        r['value'] = round(r['multi_core'] / r['price']) if r['price'] > 0 else 0

    return sorted(results, key=lambda x: x['multi_core'], reverse=True)

def generate_html(results, output_path):
    """HTML 리포트 생성"""
    # Top performers
    top_single = sorted(results, key=lambda x: x['single_core'], reverse=True)
    top_multi = sorted(results, key=lambda x: x['multi_core'], reverse=True)
    top_value = sorted(results, key=lambda x: x['value'], reverse=True)

    # Group by arch for comparison
    graviton = [r for r in results if r['arch'] == 'Graviton']
    intel = [r for r in results if r['arch'] == 'Intel']
    amd = [r for r in results if r['arch'] == 'AMD']

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Geekbench 6 벤치마크 리포트</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --graviton: #10b981;
            --intel: #3b82f6;
            --amd: #ef4444;
            --bg: #f8fafc;
            --card: #ffffff;
            --text: #1e293b;
            --muted: #64748b;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}
        .container {{ max-width: 1600px; margin: 0 auto; padding: 2rem; }}
        header {{
            text-align: center;
            margin-bottom: 2rem;
            padding: 2rem;
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a855f7 100%);
            color: white;
            border-radius: 1rem;
        }}
        header h1 {{ font-size: 2.5rem; margin-bottom: 0.5rem; }}
        header p {{ opacity: 0.9; font-size: 1.1rem; }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .card {{
            background: var(--card);
            border-radius: 1rem;
            padding: 1.5rem;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }}
        .card h3 {{
            color: var(--muted);
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }}
        .card .value {{ font-size: 1.5rem; font-weight: 700; color: var(--intel); }}
        .card .label {{ font-size: 0.875rem; color: var(--muted); }}
        .card.graviton .value {{ color: var(--graviton); }}
        .card.amd .value {{ color: var(--amd); }}
        .chart-section {{
            background: var(--card);
            border-radius: 1rem;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }}
        .chart-section h2 {{ font-size: 1.25rem; margin-bottom: 0.25rem; }}
        .chart-section .description {{ color: var(--muted); margin-bottom: 1rem; font-size: 0.875rem; }}
        .chart-container {{ position: relative; height: 400px; }}
        .chart-container.tall {{ height: 500px; }}
        .chart-container.extra-tall {{ height: 800px; }}
        .grid-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.5rem; }}
        .insights {{
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            border-left: 4px solid #f59e0b;
            padding: 1rem;
            border-radius: 0 0.5rem 0.5rem 0;
            margin: 1rem 0;
            font-size: 0.9rem;
        }}
        .insights h4 {{ color: #92400e; margin-bottom: 0.5rem; }}
        .insights ul {{ margin-left: 1.5rem; color: #78350f; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.875rem; }}
        th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ background: #f1f5f9; font-weight: 600; cursor: pointer; }}
        th:hover {{ background: #e2e8f0; }}
        tr:hover {{ background: #f8fafc; }}
        .badge {{
            display: inline-block;
            padding: 0.2rem 0.5rem;
            border-radius: 9999px;
            font-size: 0.7rem;
            font-weight: 600;
        }}
        .badge-graviton {{ background: #d1fae5; color: #065f46; }}
        .badge-intel {{ background: #dbeafe; color: #1e40af; }}
        .badge-amd {{ background: #fee2e2; color: #991b1b; }}
        footer {{
            text-align: center;
            padding: 2rem;
            color: var(--muted);
            font-size: 0.875rem;
        }}
        .filter-bar {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }}
        .filter-bar select, .filter-bar input {{
            padding: 0.5rem;
            border: 1px solid #e2e8f0;
            border-radius: 0.5rem;
            font-size: 0.875rem;
        }}
        @media (max-width: 1200px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
        @media (max-width: 768px) {{
            .container {{ padding: 1rem; }}
            header h1 {{ font-size: 1.5rem; }}
            .chart-container {{ height: 300px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Geekbench 6 벤치마크</h1>
            <p>AWS EC2 인스턴스 {len(results)}종 CPU 성능 비교 분석 (5세대 ~ 8세대)</p>
            <p style="opacity: 0.7; margin-top: 0.5rem;">{datetime.now().strftime('%Y년 %m월')} | 서울 리전 (ap-northeast-2) | 테스트 환경: EKS + Karpenter</p>
        </header>

        <div class="summary-cards">
            <div class="card graviton">
                <h3>싱글코어 최고</h3>
                <div class="value">{top_single[0]['single_core']:,}</div>
                <div class="label">{top_single[0]['instance']}</div>
            </div>
            <div class="card">
                <h3>멀티코어 최고</h3>
                <div class="value">{top_multi[0]['multi_core']:,}</div>
                <div class="label">{top_multi[0]['instance']}</div>
            </div>
            <div class="card graviton">
                <h3>최고 가성비</h3>
                <div class="value">{top_value[0]['value']:,}</div>
                <div class="label">{top_value[0]['instance']} (점수/$)</div>
            </div>
            <div class="card">
                <h3>Graviton 평균</h3>
                <div class="value">{round(sum(r['multi_core'] for r in graviton)/len(graviton)):,}</div>
                <div class="label">멀티코어 ({len(graviton)}개)</div>
            </div>
            <div class="card">
                <h3>Intel 평균</h3>
                <div class="value">{round(sum(r['multi_core'] for r in intel)/len(intel)):,}</div>
                <div class="label">멀티코어 ({len(intel)}개)</div>
            </div>
        </div>

        <div class="insights">
            <h4>핵심 인사이트</h4>
            <ul>
                <li><strong>싱글코어 성능</strong>: {top_single[0]['instance']}가 {top_single[0]['single_core']:,}점으로 1위 (Intel {get_gen(top_single[0]['instance'])}세대)</li>
                <li><strong>멀티코어 성능</strong>: {top_multi[0]['instance']}가 {top_multi[0]['multi_core']:,}점으로 1위</li>
                <li><strong>가성비 최고</strong>: {top_value[0]['instance']}가 ${top_value[0]['price']}/hr 대비 {top_value[0]['value']:,}점/$로 가장 효율적</li>
                <li><strong>아키텍처 비교</strong>: Graviton 평균 멀티코어 {round(sum(r['multi_core'] for r in graviton)/len(graviton)):,} vs Intel {round(sum(r['multi_core'] for r in intel)/len(intel)):,}</li>
            </ul>
        </div>

        <div class="chart-section">
            <h2>멀티코어 성능 순위 Top 20</h2>
            <p class="description">Geekbench 6 멀티코어 점수 (높을수록 좋음)</p>
            <div class="chart-container tall">
                <canvas id="multiChart"></canvas>
            </div>
        </div>

        <div class="grid-2">
            <div class="chart-section">
                <h2>싱글코어 성능 순위 Top 15</h2>
                <p class="description">단일 스레드 성능 비교</p>
                <div class="chart-container">
                    <canvas id="singleChart"></canvas>
                </div>
            </div>
            <div class="chart-section">
                <h2>가성비 순위 Top 15</h2>
                <p class="description">멀티코어 점수 / 시간당 가격</p>
                <div class="chart-container">
                    <canvas id="valueChart"></canvas>
                </div>
            </div>
        </div>

        <div class="chart-section">
            <h2>아키텍처별 성능 비교</h2>
            <p class="description">Graviton vs Intel vs AMD 평균 점수</p>
            <div class="chart-container" style="height: 300px;">
                <canvas id="archChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>세대별 성능 추이</h2>
            <p class="description">같은 패밀리 내 세대별 멀티코어 점수 변화</p>
            <div class="chart-container">
                <canvas id="genChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>가격 대비 성능 분포</h2>
            <p class="description">X축: 시간당 가격, Y축: 멀티코어 점수, 크기: 가성비</p>
            <div class="chart-container tall">
                <canvas id="bubbleChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>전체 결과 테이블</h2>
            <div class="filter-bar">
                <input type="text" id="searchInput" placeholder="인스턴스 검색..." onkeyup="filterTable()">
                <select id="archFilter" onchange="filterTable()">
                    <option value="">모든 아키텍처</option>
                    <option value="Graviton">Graviton</option>
                    <option value="Intel">Intel</option>
                    <option value="AMD">AMD</option>
                </select>
                <select id="genFilter" onchange="filterTable()">
                    <option value="">모든 세대</option>
                    <option value="8">8세대</option>
                    <option value="7">7세대</option>
                    <option value="6">6세대</option>
                    <option value="5">5세대</option>
                </select>
            </div>
            <table id="resultsTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0)">순위</th>
                        <th onclick="sortTable(1)">인스턴스</th>
                        <th onclick="sortTable(2)">아키텍처</th>
                        <th onclick="sortTable(3)">세대</th>
                        <th onclick="sortTable(4)">싱글코어</th>
                        <th onclick="sortTable(5)">멀티코어</th>
                        <th onclick="sortTable(6)">가격 ($/hr)</th>
                        <th onclick="sortTable(7)">가성비</th>
                    </tr>
                </thead>
                <tbody>
'''

    for i, r in enumerate(top_multi, 1):
        badge_class = 'badge-graviton' if r['arch'] == 'Graviton' else 'badge-intel' if r['arch'] == 'Intel' else 'badge-amd'
        html += f'''                    <tr data-arch="{r['arch']}" data-gen="{r['gen']}">
                        <td>{i}</td>
                        <td><strong>{r['instance']}</strong></td>
                        <td><span class="badge {badge_class}">{r['arch']}</span></td>
                        <td>{r['gen']}세대</td>
                        <td>{r['single_core']:,}</td>
                        <td><strong>{r['multi_core']:,}</strong></td>
                        <td>${r['price']:.3f}</td>
                        <td>{r['value']:,}</td>
                    </tr>
'''

    html += '''                </tbody>
            </table>
        </div>

        <footer>
            <p>Generated: ''' + datetime.now().strftime('%Y-%m-%d %H:%M') + ''' | Region: ap-northeast-2 | Benchmark: Geekbench 6</p>
        </footer>
    </div>

    <script>
'''

    # Chart data
    top20_multi = top_multi[:20]
    top15_single = top_single[:15]
    top15_value = top_value[:15]

    html += f'''
        // Multi-core Top 20
        const multiData = {{
            labels: {[r['instance'] for r in top20_multi]},
            datasets: [{{
                data: {[r['multi_core'] for r in top20_multi]},
                backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top20_multi]},
            }}]
        }};

        new Chart(document.getElementById('multiChart'), {{
            type: 'bar',
            data: multiData,
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ beginAtZero: true, title: {{ display: true, text: 'Multi-Core Score' }} }}
                }}
            }}
        }});

        // Single-core Top 15
        new Chart(document.getElementById('singleChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top15_single]},
                datasets: [{{
                    data: {[r['single_core'] for r in top15_single]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top15_single]},
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ x: {{ beginAtZero: true }} }}
            }}
        }});

        // Value Top 15
        new Chart(document.getElementById('valueChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top15_value]},
                datasets: [{{
                    data: {[r['value'] for r in top15_value]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top15_value]},
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ x: {{ beginAtZero: true }} }}
            }}
        }});

        // Architecture comparison
        const gravAvgSingle = {round(sum(r['single_core'] for r in graviton)/len(graviton)) if graviton else 0};
        const gravAvgMulti = {round(sum(r['multi_core'] for r in graviton)/len(graviton)) if graviton else 0};
        const intelAvgSingle = {round(sum(r['single_core'] for r in intel)/len(intel)) if intel else 0};
        const intelAvgMulti = {round(sum(r['multi_core'] for r in intel)/len(intel)) if intel else 0};
        const amdAvgSingle = {round(sum(r['single_core'] for r in amd)/len(amd)) if amd else 0};
        const amdAvgMulti = {round(sum(r['multi_core'] for r in amd)/len(amd)) if amd else 0};

        new Chart(document.getElementById('archChart'), {{
            type: 'bar',
            data: {{
                labels: ['Graviton', 'Intel', 'AMD'],
                datasets: [
                    {{
                        label: 'Single-Core',
                        data: [gravAvgSingle, intelAvgSingle, amdAvgSingle],
                        backgroundColor: ['#6ee7b7', '#93c5fd', '#fca5a5']
                    }},
                    {{
                        label: 'Multi-Core',
                        data: [gravAvgMulti, intelAvgMulti, amdAvgMulti],
                        backgroundColor: ['#10b981', '#3b82f6', '#ef4444']
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top' }} }},
                scales: {{ y: {{ beginAtZero: true }} }}
            }}
        }});

        // Generation trend
        const genData = {{}};
        const genResults = {[{'instance': r['instance'], 'gen': r['gen'], 'multi': r['multi_core'], 'family': r['family'][0]} for r in results]};
        genResults.forEach(r => {{
            const key = r.family + r.gen;
            if (!genData[r.family]) genData[r.family] = {{}};
            if (!genData[r.family][r.gen]) genData[r.family][r.gen] = [];
            genData[r.family][r.gen].push(r.multi);
        }});

        const families = ['C', 'M', 'R'];
        const gens = [5, 6, 7, 8];
        const genAvgs = families.map(f => gens.map(g => {{
            const vals = genData[f]?.[g] || [];
            return vals.length ? Math.round(vals.reduce((a,b) => a+b, 0) / vals.length) : null;
        }}));

        new Chart(document.getElementById('genChart'), {{
            type: 'line',
            data: {{
                labels: ['5세대', '6세대', '7세대', '8세대'],
                datasets: [
                    {{ label: 'C (Compute)', data: genAvgs[0], borderColor: '#3b82f6', tension: 0.1, spanGaps: true }},
                    {{ label: 'M (General)', data: genAvgs[1], borderColor: '#10b981', tension: 0.1, spanGaps: true }},
                    {{ label: 'R (Memory)', data: genAvgs[2], borderColor: '#ef4444', tension: 0.1, spanGaps: true }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top' }} }},
                scales: {{ y: {{ beginAtZero: false }} }}
            }}
        }});

        // Bubble chart (Price vs Performance)
        const bubbleData = {[{'x': r['price'], 'y': r['multi_core'], 'r': min(r['value']/1000, 30), 'label': r['instance'], 'arch': r['arch']} for r in results]};

        new Chart(document.getElementById('bubbleChart'), {{
            type: 'bubble',
            data: {{
                datasets: [
                    {{
                        label: 'Graviton',
                        data: bubbleData.filter(d => d.arch === 'Graviton'),
                        backgroundColor: 'rgba(16, 185, 129, 0.6)'
                    }},
                    {{
                        label: 'Intel',
                        data: bubbleData.filter(d => d.arch === 'Intel'),
                        backgroundColor: 'rgba(59, 130, 246, 0.6)'
                    }},
                    {{
                        label: 'AMD',
                        data: bubbleData.filter(d => d.arch === 'AMD'),
                        backgroundColor: 'rgba(239, 68, 68, 0.6)'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ position: 'top' }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                const d = context.raw;
                                return d.label + ': $' + d.x.toFixed(3) + '/hr, ' + d.y + ' points';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{ title: {{ display: true, text: 'Price ($/hour)' }} }},
                    y: {{ title: {{ display: true, text: 'Multi-Core Score' }} }}
                }}
            }}
        }});

        // Table functions
        function filterTable() {{
            const search = document.getElementById('searchInput').value.toLowerCase();
            const arch = document.getElementById('archFilter').value;
            const gen = document.getElementById('genFilter').value;
            const rows = document.querySelectorAll('#resultsTable tbody tr');

            rows.forEach(row => {{
                const instance = row.cells[1].textContent.toLowerCase();
                const rowArch = row.dataset.arch;
                const rowGen = row.dataset.gen;

                const matchSearch = instance.includes(search);
                const matchArch = !arch || rowArch === arch;
                const matchGen = !gen || rowGen === gen;

                row.style.display = matchSearch && matchArch && matchGen ? '' : 'none';
            }});
        }}

        let sortDir = {{}};
        function sortTable(col) {{
            const table = document.getElementById('resultsTable');
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            sortDir[col] = !sortDir[col];

            rows.sort((a, b) => {{
                let aVal = a.cells[col].textContent;
                let bVal = b.cells[col].textContent;

                // Remove formatting
                aVal = aVal.replace(/[,$]/g, '');
                bVal = bVal.replace(/[,$]/g, '');

                const aNum = parseFloat(aVal);
                const bNum = parseFloat(bVal);

                if (!isNaN(aNum) && !isNaN(bNum)) {{
                    return sortDir[col] ? aNum - bNum : bNum - aNum;
                }}
                return sortDir[col] ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
            }});

            const tbody = table.querySelector('tbody');
            rows.forEach(row => tbody.appendChild(row));
        }}
    </script>
</body>
</html>'''

    with open(output_path, 'w') as f:
        f.write(html)

    print(f"Report generated: {output_path}")
    print(f"Total instances: {len(results)}")
    print(f"Top Multi-Core: {top_multi[0]['instance']} ({top_multi[0]['multi_core']:,})")
    print(f"Top Single-Core: {top_single[0]['instance']} ({top_single[0]['single_core']:,})")
    print(f"Best Value: {top_value[0]['instance']} ({top_value[0]['value']:,} points/$)")

if __name__ == '__main__':
    results = load_data('results/geekbench/scores.csv')
    generate_html(results, 'results/geekbench/report-charts.html')
