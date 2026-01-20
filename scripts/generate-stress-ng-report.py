#!/usr/bin/env python3
"""Stress-ng 종합 벤치마크 결과 리포트 생성"""

import os
import re
import glob
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

def parse_stress_ng_log(filepath):
    """stress-ng 로그에서 성능 메트릭 추출"""
    scores = {
        'matrix': 0,
        'cpu_float': 0,
        'cpu_int': 0,
        'memcpy': 0,
        'cache': 0,
        'switch': 0,
        'branch': 0
    }

    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()

        # 패턴: "stress-ng: info:  [304] matrix           753382     60.00    237.87      0.14     12556.36        3165.34"
        # bogo ops/s (real time) 추출

        # Matrix
        match = re.search(r'matrix\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)', content)
        if match:
            scores['matrix'] = float(match.group(2))

        # CPU (첫 번째는 float, 두 번째는 integer)
        cpu_matches = re.findall(r'\] cpu\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)', content)
        if len(cpu_matches) >= 2:
            scores['cpu_float'] = float(cpu_matches[0][1])
            scores['cpu_int'] = float(cpu_matches[1][1])
        elif len(cpu_matches) == 1:
            scores['cpu_float'] = float(cpu_matches[0][1])

        # Memcpy
        match = re.search(r'memcpy\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)', content)
        if match:
            scores['memcpy'] = float(match.group(2))

        # Cache
        match = re.search(r'cache\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)', content)
        if match:
            scores['cache'] = float(match.group(2))

        # Switch (context switch)
        match = re.search(r'switch\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)', content)
        if match:
            scores['switch'] = float(match.group(2))

        # Branch
        match = re.search(r'branch\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)', content)
        if match:
            scores['branch'] = float(match.group(2))

    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return scores

def load_data(results_dir):
    """모든 결과 파일에서 데이터 로드"""
    data = defaultdict(lambda: {
        'matrix': [], 'cpu_float': [], 'cpu_int': [], 'memcpy': [], 'cache': [], 'switch': [], 'branch': []
    })

    for instance_dir in glob.glob(f"{results_dir}/*"):
        if not os.path.isdir(instance_dir):
            continue
        instance = os.path.basename(instance_dir)

        for log_file in glob.glob(f"{instance_dir}/run*.log"):
            scores = parse_stress_ng_log(log_file)
            for key, val in scores.items():
                if val > 0:
                    data[instance][key].append(val)

    results = []
    for inst, score_data in data.items():
        if not any(score_data.values()):
            continue

        # 평균 계산
        avg = {}
        for key, values in score_data.items():
            avg[key] = sum(values) / len(values) if values else 0

        # 종합 점수 (CPU 관련 테스트 가중 평균)
        total_score = (
            avg['matrix'] * 0.2 +
            avg['cpu_float'] * 0.2 +
            avg['cpu_int'] * 0.2 +
            avg['memcpy'] * 0.15 +
            avg['switch'] * 0.15 +
            avg['branch'] * 0.1
        )

        if total_score > 0:
            results.append({
                'instance': inst,
                'matrix': round(avg['matrix'], 1),
                'cpu_float': round(avg['cpu_float'], 1),
                'cpu_int': round(avg['cpu_int'], 1),
                'memcpy': round(avg['memcpy'], 1),
                'cache': round(avg['cache'], 2),
                'switch': round(avg['switch'], 1),
                'branch': round(avg['branch'], 1),
                'total_score': round(total_score, 1),
                'runs': len(score_data['matrix']) if score_data['matrix'] else 1,
                'arch': get_arch(inst),
                'gen': get_gen(inst),
                'family': get_family(inst),
                'price': PRICES.get(inst, 0.2)
            })

    for r in results:
        r['value'] = round(r['total_score'] / r['price']) if r['price'] > 0 else 0

    return sorted(results, key=lambda x: x['total_score'], reverse=True)

def generate_html(results, output_path):
    """HTML 리포트 생성"""
    top_total = sorted(results, key=lambda x: x['total_score'], reverse=True)
    top_matrix = sorted(results, key=lambda x: x['matrix'], reverse=True)
    top_cpu_int = sorted(results, key=lambda x: x['cpu_int'], reverse=True)
    top_value = sorted(results, key=lambda x: x['value'], reverse=True)

    graviton = [r for r in results if r['arch'] == 'Graviton']
    intel = [r for r in results if r['arch'] == 'Intel']
    amd = [r for r in results if r['arch'] == 'AMD']

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stress-ng 종합 벤치마크 리포트</title>
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
            background: linear-gradient(135deg, #059669 0%, #10b981 50%, #34d399 100%);
            color: white;
            border-radius: 1rem;
        }}
        header h1 {{ font-size: 2.5rem; margin-bottom: 0.5rem; }}
        header p {{ opacity: 0.9; font-size: 1.1rem; }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
        .card .value {{ font-size: 1.4rem; font-weight: 700; color: var(--intel); }}
        .card .label {{ font-size: 0.875rem; color: var(--muted); }}
        .card.graviton .value {{ color: var(--graviton); }}
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
        table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.8rem; }}
        th, td {{ padding: 0.4rem 0.5rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
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
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Stress-ng 종합 벤치마크</h1>
            <p>AWS EC2 인스턴스 {len(results)}종 CPU/메모리/컨텍스트 스위칭 성능 비교 (5세대 ~ 8세대)</p>
            <p style="opacity: 0.7; margin-top: 0.5rem;">{datetime.now().strftime('%Y년 %m월')} | 서울 리전 (ap-northeast-2) | 4 vCPU xlarge</p>
        </header>

        <div class="summary-cards">
            <div class="card">
                <h3>종합 점수 최고</h3>
                <div class="value">{top_total[0]['total_score']:,.0f}</div>
                <div class="label">{top_total[0]['instance']}</div>
            </div>
            <div class="card graviton">
                <h3>Matrix 최고</h3>
                <div class="value">{top_matrix[0]['matrix']:,.0f}</div>
                <div class="label">{top_matrix[0]['instance']} ops/s</div>
            </div>
            <div class="card">
                <h3>CPU Int 최고</h3>
                <div class="value">{top_cpu_int[0]['cpu_int']:,.0f}</div>
                <div class="label">{top_cpu_int[0]['instance']} ops/s</div>
            </div>
            <div class="card graviton">
                <h3>최고 가성비</h3>
                <div class="value">{top_value[0]['value']:,}</div>
                <div class="label">{top_value[0]['instance']}</div>
            </div>
            <div class="card">
                <h3>Graviton 평균</h3>
                <div class="value">{round(sum(r['total_score'] for r in graviton)/len(graviton)) if graviton else 0:,}</div>
                <div class="label">종합 점수 ({len(graviton)}개)</div>
            </div>
            <div class="card">
                <h3>Intel 평균</h3>
                <div class="value">{round(sum(r['total_score'] for r in intel)/len(intel)) if intel else 0:,}</div>
                <div class="label">종합 점수 ({len(intel)}개)</div>
            </div>
        </div>

        <div class="insights">
            <h4>핵심 인사이트</h4>
            <ul>
                <li><strong>종합 성능</strong>: {top_total[0]['instance']}가 종합 점수 {top_total[0]['total_score']:,.0f}으로 1위 ({top_total[0]['arch']} {top_total[0]['gen']}세대)</li>
                <li><strong>Matrix 연산</strong>: {top_matrix[0]['instance']}가 {top_matrix[0]['matrix']:,.0f} bogo ops/s로 최고</li>
                <li><strong>Integer 연산</strong>: {top_cpu_int[0]['instance']}가 {top_cpu_int[0]['cpu_int']:,.0f} bogo ops/s로 최고</li>
                <li><strong>아키텍처 비교</strong>: Graviton 평균 {round(sum(r['total_score'] for r in graviton)/len(graviton)) if graviton else 0:,} vs Intel {round(sum(r['total_score'] for r in intel)/len(intel)) if intel else 0:,}</li>
            </ul>
        </div>

        <div class="chart-section">
            <h2>종합 점수 순위 Top 20</h2>
            <p class="description">Matrix, CPU, Memory, Context Switch 가중 평균</p>
            <div class="chart-container tall">
                <canvas id="totalChart"></canvas>
            </div>
        </div>

        <div class="grid-2">
            <div class="chart-section">
                <h2>Matrix 연산 성능 Top 15</h2>
                <p class="description">행렬 곱셈 (bogo ops/s)</p>
                <div class="chart-container">
                    <canvas id="matrixChart"></canvas>
                </div>
            </div>
            <div class="chart-section">
                <h2>CPU Integer 성능 Top 15</h2>
                <p class="description">정수 연산 (bogo ops/s)</p>
                <div class="chart-container">
                    <canvas id="cpuIntChart"></canvas>
                </div>
            </div>
        </div>

        <div class="chart-section">
            <h2>아키텍처별 성능 비교</h2>
            <p class="description">Graviton vs Intel vs AMD 테스트별 평균</p>
            <div class="chart-container" style="height: 350px;">
                <canvas id="archChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>세대별 성능 추이</h2>
            <p class="description">같은 패밀리 내 세대별 종합 점수 변화</p>
            <div class="chart-container">
                <canvas id="genChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>테스트별 상세 비교 (Top 10)</h2>
            <p class="description">Matrix, CPU Float/Int, Memcpy, Switch, Branch</p>
            <div class="chart-container tall">
                <canvas id="detailChart"></canvas>
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
                        <th onclick="sortTable(0)">#</th>
                        <th onclick="sortTable(1)">인스턴스</th>
                        <th onclick="sortTable(2)">Arch</th>
                        <th onclick="sortTable(3)">Gen</th>
                        <th onclick="sortTable(4)">Matrix</th>
                        <th onclick="sortTable(5)">CPU Float</th>
                        <th onclick="sortTable(6)">CPU Int</th>
                        <th onclick="sortTable(7)">Memcpy</th>
                        <th onclick="sortTable(8)">Switch</th>
                        <th onclick="sortTable(9)">종합</th>
                    </tr>
                </thead>
                <tbody>
'''

    for i, r in enumerate(top_total, 1):
        badge_class = 'badge-graviton' if r['arch'] == 'Graviton' else 'badge-intel' if r['arch'] == 'Intel' else 'badge-amd'
        html += f'''                    <tr data-arch="{r['arch']}" data-gen="{r['gen']}">
                        <td>{i}</td>
                        <td><strong>{r['instance']}</strong></td>
                        <td><span class="badge {badge_class}">{r['arch'][:3]}</span></td>
                        <td>{r['gen']}</td>
                        <td>{r['matrix']:,.0f}</td>
                        <td>{r['cpu_float']:,.0f}</td>
                        <td>{r['cpu_int']:,.0f}</td>
                        <td>{r['memcpy']:,.0f}</td>
                        <td>{r['switch']:,.0f}</td>
                        <td><strong>{r['total_score']:,.0f}</strong></td>
                    </tr>
'''

    html += '''                </tbody>
            </table>
        </div>

        <footer>
            <p>Generated: ''' + datetime.now().strftime('%Y-%m-%d %H:%M') + ''' | Benchmark: stress-ng (matrix, cpu, memcpy, cache, switch, branch)</p>
        </footer>
    </div>

    <script>
'''

    top20_total = top_total[:20]
    top15_matrix = top_matrix[:15]
    top15_cpu_int = top_cpu_int[:15]
    top10_detail = top_total[:10]

    html += f'''
        // Total Score Top 20
        new Chart(document.getElementById('totalChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top20_total]},
                datasets: [{{
                    data: {[r['total_score'] for r in top20_total]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top20_total]},
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: 'Weighted Score' }} }} }}
            }}
        }});

        // Matrix Top 15
        new Chart(document.getElementById('matrixChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top15_matrix]},
                datasets: [{{
                    data: {[r['matrix'] for r in top15_matrix]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top15_matrix]},
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

        // CPU Int Top 15
        new Chart(document.getElementById('cpuIntChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top15_cpu_int]},
                datasets: [{{
                    data: {[r['cpu_int'] for r in top15_cpu_int]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top15_cpu_int]},
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

        // Architecture comparison (normalized to show relative performance)
        const gravMatrix = {round(sum(r['matrix'] for r in graviton)/len(graviton)/1000) if graviton else 0};
        const intelMatrix = {round(sum(r['matrix'] for r in intel)/len(intel)/1000) if intel else 0};
        const amdMatrix = {round(sum(r['matrix'] for r in amd)/len(amd)/1000) if amd else 0};
        const gravCpuInt = {round(sum(r['cpu_int'] for r in graviton)/len(graviton)/1000) if graviton else 0};
        const intelCpuInt = {round(sum(r['cpu_int'] for r in intel)/len(intel)/1000) if intel else 0};
        const amdCpuInt = {round(sum(r['cpu_int'] for r in amd)/len(amd)/1000) if amd else 0};
        const gravSwitch = {round(sum(r['switch'] for r in graviton)/len(graviton)/10000) if graviton else 0};
        const intelSwitch = {round(sum(r['switch'] for r in intel)/len(intel)/10000) if intel else 0};
        const amdSwitch = {round(sum(r['switch'] for r in amd)/len(amd)/10000) if amd else 0};

        new Chart(document.getElementById('archChart'), {{
            type: 'bar',
            data: {{
                labels: ['Graviton', 'Intel', 'AMD'],
                datasets: [
                    {{ label: 'Matrix (K ops/s)', data: [gravMatrix, intelMatrix, amdMatrix], backgroundColor: '#3b82f6' }},
                    {{ label: 'CPU Int (K ops/s)', data: [gravCpuInt, intelCpuInt, amdCpuInt], backgroundColor: '#10b981' }},
                    {{ label: 'Switch (10K ops/s)', data: [gravSwitch, intelSwitch, amdSwitch], backgroundColor: '#f59e0b' }}
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
        const genResults = {[{'instance': r['instance'], 'gen': r['gen'], 'score': r['total_score'], 'family': r['family'][0]} for r in results]};
        genResults.forEach(r => {{
            if (!genData[r.family]) genData[r.family] = {{}};
            if (!genData[r.family][r.gen]) genData[r.family][r.gen] = [];
            genData[r.family][r.gen].push(r.score);
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
                scales: {{ y: {{ beginAtZero: false }} }}
            }}
        }});

        // Detail comparison (normalized for visibility)
        new Chart(document.getElementById('detailChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top10_detail]},
                datasets: [
                    {{ label: 'Matrix (K)', data: {[round(r['matrix']/1000) for r in top10_detail]}, backgroundColor: '#3b82f6' }},
                    {{ label: 'CPU Float (K)', data: {[round(r['cpu_float']/1000) for r in top10_detail]}, backgroundColor: '#10b981' }},
                    {{ label: 'CPU Int (K)', data: {[round(r['cpu_int']/1000) for r in top10_detail]}, backgroundColor: '#f59e0b' }},
                    {{ label: 'Switch (10K)', data: {[round(r['switch']/10000) for r in top10_detail]}, backgroundColor: '#ef4444' }},
                    {{ label: 'Branch (K)', data: {[round(r['branch']/1000) for r in top10_detail]}, backgroundColor: '#8b5cf6' }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top' }} }},
                scales: {{ y: {{ beginAtZero: true }} }}
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
                const matchSearch = instance.includes(search);
                const matchArch = !arch || row.dataset.arch === arch;
                const matchGen = !gen || row.dataset.gen === gen;
                row.style.display = matchSearch && matchArch && matchGen ? '' : 'none';
            }});
        }}

        let sortDir = {{}};
        function sortTable(col) {{
            const table = document.getElementById('resultsTable');
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            sortDir[col] = !sortDir[col];

            rows.sort((a, b) => {{
                let aVal = a.cells[col].textContent.replace(/[,$]/g, '');
                let bVal = b.cells[col].textContent.replace(/[,$]/g, '');
                const aNum = parseFloat(aVal), bNum = parseFloat(bVal);
                if (!isNaN(aNum) && !isNaN(bNum)) return sortDir[col] ? aNum - bNum : bNum - aNum;
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
    print(f"Top Total Score: {top_total[0]['instance']} ({top_total[0]['total_score']:,.0f})")
    print(f"Top Matrix: {top_matrix[0]['instance']} ({top_matrix[0]['matrix']:,.0f} bogo ops/s)")

if __name__ == '__main__':
    results = load_data('results/stress-ng')
    generate_html(results, 'results/stress-ng/report-charts.html')
