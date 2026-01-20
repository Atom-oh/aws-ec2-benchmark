#!/usr/bin/env python3
"""Passmark PerformanceTest Linux 벤치마크 결과 리포트 생성"""

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

def parse_passmark_log(filepath):
    """Passmark 로그에서 점수 추출"""
    scores = {}
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()

        # Main CPU score
        match = re.search(r'SUMM_CPU:\s*([\d.]+)', content)
        if match:
            scores['cpu_mark'] = float(match.group(1))

        # Individual tests
        patterns = {
            'integer': r'CPU_INTEGER_MATH:\s*([\d.]+)',
            'float': r'CPU_FLOATINGPOINT_MATH:\s*([\d.]+)',
            'prime': r'CPU_PRIME:\s*([\d.]+)',
            'sorting': r'CPU_SORTING:\s*([\d.]+)',
            'encryption': r'CPU_ENCRYPTION:\s*([\d.]+)',
            'compression': r'CPU_COMPRESSION:\s*([\d.]+)',
            'single_thread': r'CPU_SINGLETHREAD:\s*([\d.]+)',
            'physics': r'CPU_PHYSICS:\s*([\d.]+)',
            'sse': r'CPU_MATRIX_MULT_SSE:\s*([\d.]+)'
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                scores[key] = float(match.group(1))

    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return scores

def load_data(results_dir):
    """모든 결과 파일에서 데이터 로드"""
    data = defaultdict(list)

    for instance_dir in glob.glob(f"{results_dir}/*"):
        if not os.path.isdir(instance_dir):
            continue
        instance = os.path.basename(instance_dir)

        for log_file in glob.glob(f"{instance_dir}/run*.log"):
            scores = parse_passmark_log(log_file)
            if scores.get('cpu_mark', 0) > 0:
                data[instance].append(scores)

    results = []
    for inst, score_list in data.items():
        if not score_list:
            continue

        # 평균 계산
        avg = {}
        for key in score_list[0].keys():
            values = [s.get(key, 0) for s in score_list if s.get(key, 0) > 0]
            if values:
                avg[key] = sum(values) / len(values)

        if avg.get('cpu_mark', 0) > 0:
            results.append({
                'instance': inst,
                'cpu_mark': round(avg.get('cpu_mark', 0)),
                'single_thread': round(avg.get('single_thread', 0)),
                'integer': round(avg.get('integer', 0)),
                'float': round(avg.get('float', 0)),
                'encryption': round(avg.get('encryption', 0)),
                'compression': round(avg.get('compression', 0)),
                'runs': len(score_list),
                'arch': get_arch(inst),
                'gen': get_gen(inst),
                'family': get_family(inst),
                'price': PRICES.get(inst, 0.2)
            })

    # 가성비 계산
    for r in results:
        r['value'] = round(r['cpu_mark'] / r['price']) if r['price'] > 0 else 0

    return sorted(results, key=lambda x: x['cpu_mark'], reverse=True)

def generate_html(results, output_path):
    """HTML 리포트 생성"""
    top_cpu = sorted(results, key=lambda x: x['cpu_mark'], reverse=True)
    top_single = sorted(results, key=lambda x: x['single_thread'], reverse=True)
    top_value = sorted(results, key=lambda x: x['value'], reverse=True)

    graviton = [r for r in results if r['arch'] == 'Graviton']
    intel = [r for r in results if r['arch'] == 'Intel']
    amd = [r for r in results if r['arch'] == 'AMD']

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Passmark CPU 벤치마크 리포트</title>
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
            background: linear-gradient(135deg, #f97316 0%, #fb923c 50%, #fbbf24 100%);
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
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Passmark CPU 벤치마크</h1>
            <p>AWS EC2 인스턴스 {len(results)}종 CPU Mark 성능 비교 (5세대 ~ 8세대)</p>
            <p style="opacity: 0.7; margin-top: 0.5rem;">{datetime.now().strftime('%Y년 %m월')} | 서울 리전 (ap-northeast-2)</p>
        </header>

        <div class="summary-cards">
            <div class="card">
                <h3>CPU Mark 최고</h3>
                <div class="value">{top_cpu[0]['cpu_mark']:,}</div>
                <div class="label">{top_cpu[0]['instance']}</div>
            </div>
            <div class="card graviton">
                <h3>싱글스레드 최고</h3>
                <div class="value">{top_single[0]['single_thread']:,}</div>
                <div class="label">{top_single[0]['instance']}</div>
            </div>
            <div class="card graviton">
                <h3>최고 가성비</h3>
                <div class="value">{top_value[0]['value']:,}</div>
                <div class="label">{top_value[0]['instance']} (점수/$)</div>
            </div>
            <div class="card">
                <h3>Graviton 평균</h3>
                <div class="value">{round(sum(r['cpu_mark'] for r in graviton)/len(graviton)) if graviton else 0:,}</div>
                <div class="label">CPU Mark ({len(graviton)}개)</div>
            </div>
            <div class="card">
                <h3>Intel 평균</h3>
                <div class="value">{round(sum(r['cpu_mark'] for r in intel)/len(intel)) if intel else 0:,}</div>
                <div class="label">CPU Mark ({len(intel)}개)</div>
            </div>
        </div>

        <div class="insights">
            <h4>핵심 인사이트</h4>
            <ul>
                <li><strong>종합 성능</strong>: {top_cpu[0]['instance']}가 CPU Mark {top_cpu[0]['cpu_mark']:,}점으로 1위</li>
                <li><strong>싱글스레드</strong>: {top_single[0]['instance']}가 {top_single[0]['single_thread']:,}점으로 최고</li>
                <li><strong>가성비</strong>: {top_value[0]['instance']}가 ${top_value[0]['price']}/hr 대비 {top_value[0]['value']:,}점/$</li>
                <li><strong>아키텍처 비교</strong>: Graviton 평균 {round(sum(r['cpu_mark'] for r in graviton)/len(graviton)) if graviton else 0:,} vs Intel {round(sum(r['cpu_mark'] for r in intel)/len(intel)) if intel else 0:,}</li>
            </ul>
        </div>

        <div class="chart-section">
            <h2>CPU Mark 순위 Top 20</h2>
            <p class="description">Passmark 종합 CPU 점수 (높을수록 좋음)</p>
            <div class="chart-container tall">
                <canvas id="cpuMarkChart"></canvas>
            </div>
        </div>

        <div class="grid-2">
            <div class="chart-section">
                <h2>싱글스레드 성능 Top 15</h2>
                <p class="description">단일 스레드 처리 성능</p>
                <div class="chart-container">
                    <canvas id="singleChart"></canvas>
                </div>
            </div>
            <div class="chart-section">
                <h2>가성비 순위 Top 15</h2>
                <p class="description">CPU Mark / 시간당 가격</p>
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
            <p class="description">같은 패밀리 내 세대별 CPU Mark 변화</p>
            <div class="chart-container">
                <canvas id="genChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>세부 테스트 비교 (Top 10)</h2>
            <p class="description">Integer, Float, Encryption, Compression 성능</p>
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
                        <th onclick="sortTable(0)">순위</th>
                        <th onclick="sortTable(1)">인스턴스</th>
                        <th onclick="sortTable(2)">아키텍처</th>
                        <th onclick="sortTable(3)">세대</th>
                        <th onclick="sortTable(4)">CPU Mark</th>
                        <th onclick="sortTable(5)">싱글스레드</th>
                        <th onclick="sortTable(6)">가격 ($/hr)</th>
                        <th onclick="sortTable(7)">가성비</th>
                    </tr>
                </thead>
                <tbody>
'''

    for i, r in enumerate(top_cpu, 1):
        badge_class = 'badge-graviton' if r['arch'] == 'Graviton' else 'badge-intel' if r['arch'] == 'Intel' else 'badge-amd'
        html += f'''                    <tr data-arch="{r['arch']}" data-gen="{r['gen']}">
                        <td>{i}</td>
                        <td><strong>{r['instance']}</strong></td>
                        <td><span class="badge {badge_class}">{r['arch']}</span></td>
                        <td>{r['gen']}세대</td>
                        <td><strong>{r['cpu_mark']:,}</strong></td>
                        <td>{r['single_thread']:,}</td>
                        <td>${r['price']:.3f}</td>
                        <td>{r['value']:,}</td>
                    </tr>
'''

    html += '''                </tbody>
            </table>
        </div>

        <footer>
            <p>Generated: ''' + datetime.now().strftime('%Y-%m-%d %H:%M') + ''' | Benchmark: Passmark PerformanceTest Linux</p>
        </footer>
    </div>

    <script>
'''

    top20_cpu = top_cpu[:20]
    top15_single = top_single[:15]
    top15_value = top_value[:15]
    top10_detail = top_cpu[:10]

    html += f'''
        // CPU Mark Top 20
        new Chart(document.getElementById('cpuMarkChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top20_cpu]},
                datasets: [{{
                    data: {[r['cpu_mark'] for r in top20_cpu]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top20_cpu]},
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: 'CPU Mark' }} }} }}
            }}
        }});

        // Single Thread Top 15
        new Chart(document.getElementById('singleChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top15_single]},
                datasets: [{{
                    data: {[r['single_thread'] for r in top15_single]},
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
        new Chart(document.getElementById('archChart'), {{
            type: 'bar',
            data: {{
                labels: ['Graviton', 'Intel', 'AMD'],
                datasets: [
                    {{
                        label: 'Single Thread',
                        data: [{round(sum(r['single_thread'] for r in graviton)/len(graviton)) if graviton else 0}, {round(sum(r['single_thread'] for r in intel)/len(intel)) if intel else 0}, {round(sum(r['single_thread'] for r in amd)/len(amd)) if amd else 0}],
                        backgroundColor: ['#6ee7b7', '#93c5fd', '#fca5a5']
                    }},
                    {{
                        label: 'CPU Mark',
                        data: [{round(sum(r['cpu_mark'] for r in graviton)/len(graviton)) if graviton else 0}, {round(sum(r['cpu_mark'] for r in intel)/len(intel)) if intel else 0}, {round(sum(r['cpu_mark'] for r in amd)/len(amd)) if amd else 0}],
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
        const genResults = {[{'instance': r['instance'], 'gen': r['gen'], 'cpu_mark': r['cpu_mark'], 'family': r['family'][0]} for r in results]};
        genResults.forEach(r => {{
            if (!genData[r.family]) genData[r.family] = {{}};
            if (!genData[r.family][r.gen]) genData[r.family][r.gen] = [];
            genData[r.family][r.gen].push(r.cpu_mark);
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

        // Detail comparison
        new Chart(document.getElementById('detailChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top10_detail]},
                datasets: [
                    {{ label: 'Integer (M ops/s)', data: {[round(r['integer']/1000) for r in top10_detail]}, backgroundColor: '#3b82f6' }},
                    {{ label: 'Float (M ops/s)', data: {[round(r['float']/1000) for r in top10_detail]}, backgroundColor: '#10b981' }},
                    {{ label: 'Encryption (MB/s)', data: {[round(r['encryption']/100) for r in top10_detail]}, backgroundColor: '#f59e0b' }},
                    {{ label: 'Compression (KB/s)', data: {[round(r['compression']/1000) for r in top10_detail]}, backgroundColor: '#ef4444' }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
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
    print(f"Top CPU Mark: {top_cpu[0]['instance']} ({top_cpu[0]['cpu_mark']:,})")
    print(f"Top Single Thread: {top_single[0]['instance']} ({top_single[0]['single_thread']:,})")

if __name__ == '__main__':
    results = load_data('results/passmark')
    generate_html(results, 'results/passmark/report-charts.html')
