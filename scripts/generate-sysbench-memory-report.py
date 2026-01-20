#!/usr/bin/env python3
"""Sysbench Memory 벤치마크 결과 리포트 생성"""

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

def parse_sysbench_memory_log(filepath):
    """sysbench memory 로그에서 성능 메트릭 추출"""
    scores = {
        'seq_write': 0,
        'seq_read': 0,
        'rnd_write': 0,
        'rnd_read': 0,
        'large_block': 0
    }

    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()

        # MiB/sec 추출 - 순서대로 5개 테스트
        # 패턴: "102400.00 MiB transferred (6657.70 MiB/sec)"
        matches = re.findall(r'MiB transferred \(([\d.]+) MiB/sec\)', content)

        if len(matches) >= 5:
            scores['seq_write'] = float(matches[0])
            scores['seq_read'] = float(matches[1])
            scores['rnd_write'] = float(matches[2])
            scores['rnd_read'] = float(matches[3])
            scores['large_block'] = float(matches[4])
        elif len(matches) > 0:
            # 일부만 있는 경우
            for i, key in enumerate(['seq_write', 'seq_read', 'rnd_write', 'rnd_read', 'large_block']):
                if i < len(matches):
                    scores[key] = float(matches[i])

    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return scores

def load_data(results_dir):
    """모든 결과 파일에서 데이터 로드"""
    data = defaultdict(lambda: {
        'seq_write': [], 'seq_read': [], 'rnd_write': [], 'rnd_read': [], 'large_block': []
    })

    for instance_dir in glob.glob(f"{results_dir}/*"):
        if not os.path.isdir(instance_dir):
            continue
        instance = os.path.basename(instance_dir)

        for log_file in glob.glob(f"{instance_dir}/run*.log"):
            scores = parse_sysbench_memory_log(log_file)
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

        # 총 대역폭 (Read + Write 평균)
        total_bw = (avg['seq_write'] + avg['seq_read'] + avg['rnd_write'] + avg['rnd_read']) / 4

        if total_bw > 0:
            results.append({
                'instance': inst,
                'seq_write': round(avg['seq_write'], 1),
                'seq_read': round(avg['seq_read'], 1),
                'rnd_write': round(avg['rnd_write'], 1),
                'rnd_read': round(avg['rnd_read'], 1),
                'large_block': round(avg['large_block'], 1),
                'total_bw': round(total_bw, 1),
                'runs': len(score_data['seq_write']),
                'arch': get_arch(inst),
                'gen': get_gen(inst),
                'family': get_family(inst),
                'price': PRICES.get(inst, 0.2)
            })

    for r in results:
        r['value'] = round(r['total_bw'] / r['price']) if r['price'] > 0 else 0

    return sorted(results, key=lambda x: x['total_bw'], reverse=True)

def generate_html(results, output_path):
    """HTML 리포트 생성"""
    top_bw = sorted(results, key=lambda x: x['total_bw'], reverse=True)
    top_seq_read = sorted(results, key=lambda x: x['seq_read'], reverse=True)
    top_seq_write = sorted(results, key=lambda x: x['seq_write'], reverse=True)
    top_value = sorted(results, key=lambda x: x['value'], reverse=True)

    graviton = [r for r in results if r['arch'] == 'Graviton']
    intel = [r for r in results if r['arch'] == 'Intel']
    amd = [r for r in results if r['arch'] == 'AMD']

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sysbench Memory 벤치마크 리포트</title>
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
            background: linear-gradient(135deg, #ec4899 0%, #f472b6 50%, #fb7185 100%);
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
            <h1>Sysbench Memory 벤치마크</h1>
            <p>AWS EC2 인스턴스 {len(results)}종 메모리 대역폭 비교 (5세대 ~ 8세대)</p>
            <p style="opacity: 0.7; margin-top: 0.5rem;">{datetime.now().strftime('%Y년 %m월')} | 서울 리전 (ap-northeast-2) | 4 vCPU xlarge</p>
        </header>

        <div class="summary-cards">
            <div class="card">
                <h3>평균 대역폭 최고</h3>
                <div class="value">{top_bw[0]['total_bw']:,.0f}</div>
                <div class="label">{top_bw[0]['instance']} MiB/s</div>
            </div>
            <div class="card graviton">
                <h3>Seq Read 최고</h3>
                <div class="value">{top_seq_read[0]['seq_read']:,.0f}</div>
                <div class="label">{top_seq_read[0]['instance']} MiB/s</div>
            </div>
            <div class="card">
                <h3>Seq Write 최고</h3>
                <div class="value">{top_seq_write[0]['seq_write']:,.0f}</div>
                <div class="label">{top_seq_write[0]['instance']} MiB/s</div>
            </div>
            <div class="card graviton">
                <h3>최고 가성비</h3>
                <div class="value">{top_value[0]['value']:,}</div>
                <div class="label">{top_value[0]['instance']}</div>
            </div>
            <div class="card">
                <h3>Graviton 평균</h3>
                <div class="value">{round(sum(r['total_bw'] for r in graviton)/len(graviton)) if graviton else 0:,}</div>
                <div class="label">MiB/s ({len(graviton)}개)</div>
            </div>
            <div class="card">
                <h3>Intel 평균</h3>
                <div class="value">{round(sum(r['total_bw'] for r in intel)/len(intel)) if intel else 0:,}</div>
                <div class="label">MiB/s ({len(intel)}개)</div>
            </div>
        </div>

        <div class="insights">
            <h4>핵심 인사이트</h4>
            <ul>
                <li><strong>최고 대역폭</strong>: {top_bw[0]['instance']}가 평균 {top_bw[0]['total_bw']:,.0f} MiB/s로 1위 ({top_bw[0]['arch']} {top_bw[0]['gen']}세대)</li>
                <li><strong>Sequential Read</strong>: {top_seq_read[0]['instance']}가 {top_seq_read[0]['seq_read']:,.0f} MiB/s로 최고</li>
                <li><strong>가성비</strong>: {top_value[0]['instance']}가 ${top_value[0]['price']}/hr 대비 가장 효율적</li>
                <li><strong>아키텍처 비교</strong>: Graviton 평균 {round(sum(r['total_bw'] for r in graviton)/len(graviton)) if graviton else 0:,} vs Intel {round(sum(r['total_bw'] for r in intel)/len(intel)) if intel else 0:,} MiB/s</li>
            </ul>
        </div>

        <div class="chart-section">
            <h2>평균 메모리 대역폭 순위 Top 20</h2>
            <p class="description">(Seq Read + Seq Write + Rnd Read + Rnd Write) / 4 (MiB/sec)</p>
            <div class="chart-container tall">
                <canvas id="totalBwChart"></canvas>
            </div>
        </div>

        <div class="grid-2">
            <div class="chart-section">
                <h2>Sequential Read 성능 Top 15</h2>
                <p class="description">순차 읽기 대역폭 (MiB/sec)</p>
                <div class="chart-container">
                    <canvas id="seqReadChart"></canvas>
                </div>
            </div>
            <div class="chart-section">
                <h2>Sequential Write 성능 Top 15</h2>
                <p class="description">순차 쓰기 대역폭 (MiB/sec)</p>
                <div class="chart-container">
                    <canvas id="seqWriteChart"></canvas>
                </div>
            </div>
        </div>

        <div class="chart-section">
            <h2>아키텍처별 메모리 성능 비교</h2>
            <p class="description">Graviton vs Intel vs AMD 평균 대역폭</p>
            <div class="chart-container" style="height: 350px;">
                <canvas id="archChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>세대별 성능 추이</h2>
            <p class="description">같은 패밀리 내 세대별 평균 대역폭 변화</p>
            <div class="chart-container">
                <canvas id="genChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>테스트별 상세 비교 (Top 10)</h2>
            <p class="description">Sequential vs Random, Read vs Write</p>
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
                        <th onclick="sortTable(4)">Seq Write</th>
                        <th onclick="sortTable(5)">Seq Read</th>
                        <th onclick="sortTable(6)">Rnd Write</th>
                        <th onclick="sortTable(7)">Rnd Read</th>
                        <th onclick="sortTable(8)">평균 BW</th>
                        <th onclick="sortTable(9)">$/hr</th>
                    </tr>
                </thead>
                <tbody>
'''

    for i, r in enumerate(top_bw, 1):
        badge_class = 'badge-graviton' if r['arch'] == 'Graviton' else 'badge-intel' if r['arch'] == 'Intel' else 'badge-amd'
        html += f'''                    <tr data-arch="{r['arch']}" data-gen="{r['gen']}">
                        <td>{i}</td>
                        <td><strong>{r['instance']}</strong></td>
                        <td><span class="badge {badge_class}">{r['arch'][:3]}</span></td>
                        <td>{r['gen']}</td>
                        <td>{r['seq_write']:,.0f}</td>
                        <td>{r['seq_read']:,.0f}</td>
                        <td>{r['rnd_write']:,.0f}</td>
                        <td>{r['rnd_read']:,.0f}</td>
                        <td><strong>{r['total_bw']:,.0f}</strong></td>
                        <td>${r['price']:.3f}</td>
                    </tr>
'''

    html += '''                </tbody>
            </table>
        </div>

        <footer>
            <p>Generated: ''' + datetime.now().strftime('%Y-%m-%d %H:%M') + ''' | Benchmark: Sysbench Memory (1K block)</p>
        </footer>
    </div>

    <script>
'''

    top20_bw = top_bw[:20]
    top15_seq_read = top_seq_read[:15]
    top15_seq_write = top_seq_write[:15]
    top10_detail = top_bw[:10]

    html += f'''
        // Total BW Top 20
        new Chart(document.getElementById('totalBwChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top20_bw]},
                datasets: [{{
                    data: {[r['total_bw'] for r in top20_bw]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top20_bw]},
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: 'MiB/sec' }} }} }}
            }}
        }});

        // Seq Read Top 15
        new Chart(document.getElementById('seqReadChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top15_seq_read]},
                datasets: [{{
                    data: {[r['seq_read'] for r in top15_seq_read]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top15_seq_read]},
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

        // Seq Write Top 15
        new Chart(document.getElementById('seqWriteChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top15_seq_write]},
                datasets: [{{
                    data: {[r['seq_write'] for r in top15_seq_write]},
                    backgroundColor: {['#10b981' if r['arch'] == 'Graviton' else '#3b82f6' if r['arch'] == 'Intel' else '#ef4444' for r in top15_seq_write]},
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
                        label: 'Seq Write',
                        data: [{round(sum(r['seq_write'] for r in graviton)/len(graviton)) if graviton else 0}, {round(sum(r['seq_write'] for r in intel)/len(intel)) if intel else 0}, {round(sum(r['seq_write'] for r in amd)/len(amd)) if amd else 0}],
                        backgroundColor: '#3b82f6'
                    }},
                    {{
                        label: 'Seq Read',
                        data: [{round(sum(r['seq_read'] for r in graviton)/len(graviton)) if graviton else 0}, {round(sum(r['seq_read'] for r in intel)/len(intel)) if intel else 0}, {round(sum(r['seq_read'] for r in amd)/len(amd)) if amd else 0}],
                        backgroundColor: '#10b981'
                    }},
                    {{
                        label: 'Rnd Write',
                        data: [{round(sum(r['rnd_write'] for r in graviton)/len(graviton)) if graviton else 0}, {round(sum(r['rnd_write'] for r in intel)/len(intel)) if intel else 0}, {round(sum(r['rnd_write'] for r in amd)/len(amd)) if amd else 0}],
                        backgroundColor: '#f59e0b'
                    }},
                    {{
                        label: 'Rnd Read',
                        data: [{round(sum(r['rnd_read'] for r in graviton)/len(graviton)) if graviton else 0}, {round(sum(r['rnd_read'] for r in intel)/len(intel)) if intel else 0}, {round(sum(r['rnd_read'] for r in amd)/len(amd)) if amd else 0}],
                        backgroundColor: '#ef4444'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top' }} }},
                scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'MiB/sec' }} }} }}
            }}
        }});

        // Generation trend
        const genData = {{}};
        const genResults = {[{'instance': r['instance'], 'gen': r['gen'], 'bw': r['total_bw'], 'family': r['family'][0]} for r in results]};
        genResults.forEach(r => {{
            if (!genData[r.family]) genData[r.family] = {{}};
            if (!genData[r.family][r.gen]) genData[r.family][r.gen] = [];
            genData[r.family][r.gen].push(r.bw);
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

        // Detail comparison Top 10
        new Chart(document.getElementById('detailChart'), {{
            type: 'bar',
            data: {{
                labels: {[r['instance'] for r in top10_detail]},
                datasets: [
                    {{ label: 'Seq Write', data: {[r['seq_write'] for r in top10_detail]}, backgroundColor: '#3b82f6' }},
                    {{ label: 'Seq Read', data: {[r['seq_read'] for r in top10_detail]}, backgroundColor: '#10b981' }},
                    {{ label: 'Rnd Write', data: {[r['rnd_write'] for r in top10_detail]}, backgroundColor: '#f59e0b' }},
                    {{ label: 'Rnd Read', data: {[r['rnd_read'] for r in top10_detail]}, backgroundColor: '#ef4444' }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top' }} }},
                scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'MiB/sec' }} }} }}
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
    print(f"Top Bandwidth: {top_bw[0]['instance']} ({top_bw[0]['total_bw']:,.0f} MiB/s)")
    print(f"Top Seq Read: {top_seq_read[0]['instance']} ({top_seq_read[0]['seq_read']:,.0f} MiB/s)")

if __name__ == '__main__':
    results = load_data('results/sysbench-memory')
    generate_html(results, 'results/sysbench-memory/report-charts.html')
