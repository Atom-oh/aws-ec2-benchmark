#!/usr/bin/env python3
"""Sysbench CPU 벤치마크 결과 리포트 생성"""

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

def parse_sysbench_log(filepath):
    """sysbench 로그에서 성능 메트릭 추출"""
    scores = {'multi': [], 'single': [], 'latency': []}
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()

        # Multi-thread events per second (3회 반복 평균)
        # "events per second:" 패턴 추출
        matches = re.findall(r'events per second:\s*([\d.]+)', content)
        if matches:
            # 마지막 결과는 싱글스레드
            if len(matches) >= 4:
                # 앞의 3개는 멀티스레드 (warm-up 제외)
                scores['multi'] = [float(m) for m in matches[:3]]
                scores['single'] = [float(matches[-1])]
            else:
                scores['multi'] = [float(m) for m in matches]

        # Latency (95th percentile)
        lat_matches = re.findall(r'95th percentile:\s*([\d.]+)', content)
        if lat_matches:
            scores['latency'] = [float(m) for m in lat_matches]

    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return scores

def load_data(results_dir):
    """모든 결과 파일에서 데이터 로드"""
    data = defaultdict(lambda: {'multi': [], 'single': [], 'latency': []})

    for instance_dir in glob.glob(f"{results_dir}/*"):
        if not os.path.isdir(instance_dir):
            continue
        instance = os.path.basename(instance_dir)

        for log_file in glob.glob(f"{instance_dir}/run*.log"):
            scores = parse_sysbench_log(log_file)
            if scores['multi']:
                data[instance]['multi'].extend(scores['multi'])
            if scores['single']:
                data[instance]['single'].extend(scores['single'])
            if scores['latency']:
                data[instance]['latency'].extend(scores['latency'])

    results = []
    for inst, score_data in data.items():
        if not score_data['multi']:
            continue

        multi_avg = sum(score_data['multi']) / len(score_data['multi']) if score_data['multi'] else 0
        single_avg = sum(score_data['single']) / len(score_data['single']) if score_data['single'] else 0
        latency_avg = sum(score_data['latency']) / len(score_data['latency']) if score_data['latency'] else 0

        if multi_avg > 0:
            results.append({
                'instance': inst,
                'multi_thread': round(multi_avg, 2),
                'single_thread': round(single_avg, 2),
                'latency_95': round(latency_avg, 2),
                'runs': len(score_data['multi']) // 3 if score_data['multi'] else 0,
                'arch': get_arch(inst),
                'gen': get_gen(inst),
                'family': get_family(inst),
                'price': PRICES.get(inst, 0.2)
            })

    for r in results:
        r['value'] = round(r['multi_thread'] / r['price']) if r['price'] > 0 else 0

    return sorted(results, key=lambda x: x['multi_thread'], reverse=True)

def generate_html(results, output_path):
    """HTML 리포트 생성"""
    top_multi = sorted(results, key=lambda x: x['multi_thread'], reverse=True)
    top_single = sorted(results, key=lambda x: x['single_thread'], reverse=True)
    top_value = sorted(results, key=lambda x: x['value'], reverse=True)
    top_latency = sorted(results, key=lambda x: x['latency_95'] if x['latency_95'] > 0 else float('inf'))

    graviton = [r for r in results if r['arch'] == 'Graviton']
    intel = [r for r in results if r['arch'] == 'Intel']
    amd = [r for r in results if r['arch'] == 'AMD']

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sysbench CPU 벤치마크 리포트</title>
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
            background: linear-gradient(135deg, #0ea5e9 0%, #06b6d4 50%, #14b8a6 100%);
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
            <h1>Sysbench CPU 벤치마크</h1>
            <p>AWS EC2 인스턴스 {len(results)}종 Prime Number 계산 성능 비교 (5세대 ~ 8세대)</p>
            <p style="opacity: 0.7; margin-top: 0.5rem;">{datetime.now().strftime('%Y년 %m월')} | 서울 리전 (ap-northeast-2) | 4 vCPU xlarge</p>
        </header>

        <div class="summary-cards">
            <div class="card">
                <h3>멀티스레드 최고</h3>
                <div class="value">{top_multi[0]['multi_thread']:,.0f}</div>
                <div class="label">{top_multi[0]['instance']} events/s</div>
            </div>
            <div class="card graviton">
                <h3>싱글스레드 최고</h3>
                <div class="value">{top_single[0]['single_thread']:,.0f}</div>
                <div class="label">{top_single[0]['instance']} events/s</div>
            </div>
            <div class="card graviton">
                <h3>최저 지연시간</h3>
                <div class="value">{top_latency[0]['latency_95']:.2f}ms</div>
                <div class="label">{top_latency[0]['instance']} (95th)</div>
            </div>
            <div class="card">
                <h3>최고 가성비</h3>
                <div class="value">{top_value[0]['value']:,}</div>
                <div class="label">{top_value[0]['instance']} (events/$)</div>
            </div>
            <div class="card">
                <h3>Graviton 평균</h3>
                <div class="value">{round(sum(r['multi_thread'] for r in graviton)/len(graviton)) if graviton else 0:,}</div>
                <div class="label">events/s ({len(graviton)}개)</div>
            </div>
        </div>

        <div class="insights">
            <h4>핵심 인사이트</h4>
            <ul>
                <li><strong>멀티스레드 성능</strong>: {top_multi[0]['instance']}가 {top_multi[0]['multi_thread']:,.0f} events/s로 1위 ({top_multi[0]['arch']} {top_multi[0]['gen']}세대)</li>
                <li><strong>싱글스레드 성능</strong>: {top_single[0]['instance']}가 {top_single[0]['single_thread']:,.0f} events/s로 최고</li>
                <li><strong>가성비</strong>: {top_value[0]['instance']}가 ${top_value[0]['price']}/hr 대비 가장 효율적</li>
                <li><strong>아키텍처 비교</strong>: Graviton 평균 {round(sum(r['multi_thread'] for r in graviton)/len(graviton)) if graviton else 0:,} vs Intel {round(sum(r['multi_thread'] for r in intel)/len(intel)) if intel else 0:,} events/s</li>
            </ul>
        </div>

        <div class="chart-section">
            <h2>멀티스레드 성능 순위 Top 20</h2>
            <p class="description">4 vCPU Prime Number 계산 (events/sec, 높을수록 좋음)</p>
            <div class="chart-container tall">
                <canvas id="multiChart"></canvas>
            </div>
        </div>

        <div class="grid-2">
            <div class="chart-section">
                <h2>싱글스레드 성능 Top 15</h2>
                <p class="description">단일 스레드 Prime Number 계산</p>
                <div class="chart-container">
                    <canvas id="singleChart"></canvas>
                </div>
            </div>
            <div class="chart-section">
                <h2>가성비 순위 Top 15</h2>
                <p class="description">events/s / 시간당 가격</p>
                <div class="chart-container">
                    <canvas id="valueChart"></canvas>
                </div>
            </div>
        </div>

        <div class="chart-section">
            <h2>아키텍처별 성능 비교</h2>
            <p class="description">Graviton vs Intel vs AMD 평균 성능</p>
            <div class="chart-container" style="height: 300px;">
                <canvas id="archChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>세대별 성능 추이 (Graviton vs Intel)</h2>
            <p class="description">C/M 패밀리별 Graviton과 Intel의 세대별 멀티스레드 성능 변화 (AMD 제외)</p>
            <div class="chart-container">
                <canvas id="genChart"></canvas>
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
                        <th onclick="sortTable(4)">멀티스레드</th>
                        <th onclick="sortTable(5)">싱글스레드</th>
                        <th onclick="sortTable(6)">95th 지연(ms)</th>
                        <th onclick="sortTable(7)">가격 ($/hr)</th>
                        <th onclick="sortTable(8)">가성비</th>
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
                        <td><strong>{r['multi_thread']:,.0f}</strong></td>
                        <td>{r['single_thread']:,.0f}</td>
                        <td>{r['latency_95']:.2f}</td>
                        <td>${r['price']:.3f}</td>
                        <td>{r['value']:,}</td>
                    </tr>
'''

    html += '''                </tbody>
            </table>
        </div>

        <footer>
            <p>Generated: ''' + datetime.now().strftime('%Y-%m-%d %H:%M') + ''' | Benchmark: Sysbench CPU (prime=20000)</p>
        </footer>
    </div>

    <script>
'''

    top20_multi = top_multi[:20]
    top15_single = top_single[:15]
    top15_value = top_value[:15]

    html += f'''
        // Multi-thread Top 20
        new Chart(document.getElementById('multiChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top20_multi]},
                datasets: [{{
                    data: {[r['multi_thread'] for r in top20_multi]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top20_multi]},
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: 'Events per Second' }} }} }}
            }}
        }});

        // Single-thread Top 15
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
                        label: 'Multi Thread',
                        data: [{round(sum(r['multi_thread'] for r in graviton)/len(graviton)) if graviton else 0}, {round(sum(r['multi_thread'] for r in intel)/len(intel)) if intel else 0}, {round(sum(r['multi_thread'] for r in amd)/len(amd)) if amd else 0}],
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

        // Generation trend - Graviton vs Intel per family (excluding AMD)
        const genData = {{}};
        const genResults = {[{'instance': r['instance'], 'gen': r['gen'], 'multi': r['multi_thread'], 'family': r['family'][0], 'arch': r['arch']} for r in results]};
        genResults.forEach(r => {{
            if (r.arch === 'AMD') return; // AMD 제외
            const key = r.family + '_' + r.arch;
            if (!genData[key]) genData[key] = {{}};
            if (!genData[key][r.gen]) genData[key][r.gen] = [];
            genData[key][r.gen].push(r.multi);
        }});

        const categories = ['C_Intel', 'C_Graviton', 'M_Intel', 'M_Graviton'];
        const gens = [5, 6, 7, 8];
        const genAvgs = categories.map(cat => gens.map(g => {{
            const vals = genData[cat]?.[g] || [];
            return vals.length ? Math.round(vals.reduce((a,b) => a+b, 0) / vals.length) : null;
        }}));

        new Chart(document.getElementById('genChart'), {{
            type: 'line',
            data: {{
                labels: ['5세대', '6세대', '7세대', '8세대'],
                datasets: [
                    {{ label: 'C Intel', data: genAvgs[0], borderColor: '#3b82f6', backgroundColor: '#3b82f6', tension: 0.1, spanGaps: true, borderWidth: 2 }},
                    {{ label: 'C Graviton', data: genAvgs[1], borderColor: '#10b981', backgroundColor: '#10b981', tension: 0.1, spanGaps: true, borderWidth: 2 }},
                    {{ label: 'M Intel', data: genAvgs[2], borderColor: '#60a5fa', backgroundColor: '#60a5fa', tension: 0.1, spanGaps: true, borderDash: [5, 5], borderWidth: 2 }},
                    {{ label: 'M Graviton', data: genAvgs[3], borderColor: '#34d399', backgroundColor: '#34d399', tension: 0.1, spanGaps: true, borderDash: [5, 5], borderWidth: 2 }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ position: 'top' }},
                    title: {{ display: true, text: 'Graviton은 6세대부터 시작, Intel 5세대는 i 없음' }}
                }},
                scales: {{ y: {{ beginAtZero: false, title: {{ display: true, text: 'Events per Second' }} }} }}
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
    print(f"Top Multi-thread: {top_multi[0]['instance']} ({top_multi[0]['multi_thread']:,.0f} events/s)")
    print(f"Top Single-thread: {top_single[0]['instance']} ({top_single[0]['single_thread']:,.0f} events/s)")

if __name__ == '__main__':
    results = load_data('results/sysbench-cpu')
    generate_html(results, 'results/sysbench-cpu/report-charts.html')
