#!/usr/bin/env python3
"""
Sysbench 종합 벤치마크 보고서 생성기
CPU + Memory 벤치마크 결과를 하나의 HTML 보고서로 생성
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# 가격 데이터 (ap-northeast-2, On-Demand, xlarge)
PRICES = {
    # Intel 5th Gen
    'c5.xlarge': 0.192, 'c5d.xlarge': 0.220, 'c5n.xlarge': 0.244,
    'm5.xlarge': 0.236, 'm5d.xlarge': 0.278, 'm5zn.xlarge': 0.406,
    'r5.xlarge': 0.304, 'r5d.xlarge': 0.346, 'r5dn.xlarge': 0.398,
    'r5b.xlarge': 0.356, 'r5n.xlarge': 0.356,
    # AMD 5th Gen
    'c5a.xlarge': 0.172,
    'm5a.xlarge': 0.212, 'm5ad.xlarge': 0.254,
    'r5a.xlarge': 0.272, 'r5ad.xlarge': 0.316,
    # Intel 6th Gen
    'c6i.xlarge': 0.192, 'c6id.xlarge': 0.231, 'c6in.xlarge': 0.256,
    'm6i.xlarge': 0.236, 'm6id.xlarge': 0.292, 'm6in.xlarge': 0.337, 'm6idn.xlarge': 0.386,
    'r6i.xlarge': 0.304, 'r6id.xlarge': 0.363,
    # Graviton2 (6th Gen)
    'c6g.xlarge': 0.154, 'c6gd.xlarge': 0.176, 'c6gn.xlarge': 0.195,
    'm6g.xlarge': 0.188, 'm6gd.xlarge': 0.222,
    'r6g.xlarge': 0.244, 'r6gd.xlarge': 0.277,
    # Intel 7th Gen
    'c7i.xlarge': 0.202, 'c7i-flex.xlarge': 0.192,
    'm7i.xlarge': 0.248, 'm7i-flex.xlarge': 0.235,
    'r7i.xlarge': 0.319,
    # Graviton3 (7th Gen)
    'c7g.xlarge': 0.163, 'c7gd.xlarge': 0.208,
    'm7g.xlarge': 0.201, 'm7gd.xlarge': 0.263,
    'r7g.xlarge': 0.258, 'r7gd.xlarge': 0.327,
    # Intel 8th Gen
    'c8i.xlarge': 0.212, 'c8i-flex.xlarge': 0.201,
    'm8i.xlarge': 0.260,
    'r8i.xlarge': 0.335, 'r8i-flex.xlarge': 0.318,
    # Graviton4 (8th Gen)
    'c8g.xlarge': 0.180,
    'm8g.xlarge': 0.221,
    'r8g.xlarge': 0.284,
}

def get_instance_info(name):
    """인스턴스 정보 추출"""
    # 아키텍처
    if 'g.xlarge' in name or 'gd.xlarge' in name or 'gn.xlarge' in name:
        arch = 'graviton'
    elif 'a.xlarge' in name or 'ad.xlarge' in name:
        arch = 'amd'
    else:
        arch = 'intel'

    # 세대
    gen_match = re.search(r'[cmr](\d)', name)
    gen = int(gen_match.group(1)) if gen_match else 5

    # 패밀리
    family = name[0]

    return arch, gen, family

def parse_cpu_log(filepath):
    """sysbench-cpu 로그 파싱"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()

        # Multi-thread events/sec (3회 평균)
        mt_events = re.findall(r'events per second:\s+(\d+\.?\d*)', content)
        # Single-thread events/sec (마지막)
        st_section = content.split('Single Thread Performance')
        if len(st_section) > 1:
            st_match = re.search(r'events per second:\s+(\d+\.?\d*)', st_section[1])
            single_thread = float(st_match.group(1)) if st_match else 0
        else:
            single_thread = 0

        # 앞 3개가 multi-thread 결과
        multi_thread_values = [float(x) for x in mt_events[:3]] if mt_events else []
        multi_thread = sum(multi_thread_values) / len(multi_thread_values) if multi_thread_values else 0

        return {
            'multi_thread': round(multi_thread, 2),
            'single_thread': round(single_thread, 2)
        }
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return None

def parse_memory_log(filepath):
    """sysbench-memory 로그 파싱"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()

        results = {}

        # 각 테스트 섹션 파싱
        patterns = {
            'seq_write_1k': r'Sequential Write \(1K block\).*?(\d+\.?\d*) MiB/sec',
            'seq_read_1k': r'Sequential Read \(1K block\).*?(\d+\.?\d*) MiB/sec',
            'rnd_write_1k': r'Random Write \(1K block\).*?(\d+\.?\d*) MiB/sec',
            'rnd_read_1k': r'Random Read \(1K block\).*?(\d+\.?\d*) MiB/sec',
            'large_block_1m': r'Large Block Sequential Write \(1M block\).*?(\d+\.?\d*) MiB/sec',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content, re.DOTALL)
            results[key] = float(match.group(1)) if match else 0

        return results if any(results.values()) else None
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return None

def collect_cpu_data(base_path):
    """CPU 벤치마크 데이터 수집"""
    data = {}
    cpu_path = Path(base_path) / 'sysbench-cpu'

    if not cpu_path.exists():
        print(f"CPU path not found: {cpu_path}")
        return data

    for instance_dir in cpu_path.iterdir():
        if not instance_dir.is_dir():
            continue

        instance = instance_dir.name
        runs = []

        for run_file in sorted(instance_dir.glob('run*.log')):
            result = parse_cpu_log(run_file)
            if result:
                runs.append(result)

        if runs:
            # 평균 계산
            data[instance] = {
                'multi_thread': round(sum(r['multi_thread'] for r in runs) / len(runs), 2),
                'single_thread': round(sum(r['single_thread'] for r in runs) / len(runs), 2),
                'runs': len(runs)
            }

    return data

def collect_memory_data(base_path):
    """Memory 벤치마크 데이터 수집"""
    data = {}
    mem_path = Path(base_path) / 'sysbench-memory'

    if not mem_path.exists():
        print(f"Memory path not found: {mem_path}")
        return data

    for instance_dir in mem_path.iterdir():
        if not instance_dir.is_dir():
            continue

        instance = instance_dir.name
        runs = defaultdict(list)

        for run_file in sorted(instance_dir.glob('run*.log')):
            result = parse_memory_log(run_file)
            if result:
                for key, value in result.items():
                    if value > 0:
                        runs[key].append(value)

        if runs:
            data[instance] = {
                key: round(sum(values) / len(values), 2)
                for key, values in runs.items()
            }
            data[instance]['runs'] = len(runs.get('seq_write_1k', []))

    return data

def generate_html_report(cpu_data, memory_data, output_path):
    """HTML 보고서 생성"""

    # 데이터 병합
    all_instances = sorted(set(cpu_data.keys()) | set(memory_data.keys()))

    # JavaScript 데이터 준비
    js_data = []
    for instance in all_instances:
        arch, gen, family = get_instance_info(instance)
        price = PRICES.get(instance, 0)

        cpu = cpu_data.get(instance, {})
        mem = memory_data.get(instance, {})

        entry = {
            'name': instance,
            'arch': arch,
            'gen': gen,
            'family': family,
            'price': price,
            # CPU
            'cpu_mt': cpu.get('multi_thread', 0),
            'cpu_st': cpu.get('single_thread', 0),
            # Memory
            'mem_seq_write': mem.get('seq_write_1k', 0),
            'mem_seq_read': mem.get('seq_read_1k', 0),
            'mem_rnd_write': mem.get('rnd_write_1k', 0),
            'mem_rnd_read': mem.get('rnd_read_1k', 0),
            'mem_large_block': mem.get('large_block_1m', 0),
        }

        # 효율성 점수 계산 (가격 대비 성능)
        if price > 0:
            entry['cpu_efficiency'] = round(entry['cpu_mt'] / price, 1)
            entry['mem_efficiency'] = round(entry['mem_large_block'] / price, 1)
        else:
            entry['cpu_efficiency'] = 0
            entry['mem_efficiency'] = 0

        js_data.append(entry)

    # Top performers 계산
    top_cpu_mt = sorted([d for d in js_data if d['cpu_mt'] > 0], key=lambda x: x['cpu_mt'], reverse=True)[:1]
    top_cpu_st = sorted([d for d in js_data if d['cpu_st'] > 0], key=lambda x: x['cpu_st'], reverse=True)[:1]
    top_mem_bw = sorted([d for d in js_data if d['mem_large_block'] > 0], key=lambda x: x['mem_large_block'], reverse=True)[:1]
    top_efficiency = sorted([d for d in js_data if d['cpu_efficiency'] > 0], key=lambda x: x['cpu_efficiency'], reverse=True)[:1]

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sysbench 종합 벤치마크 리포트</title>
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
            --border: #e2e8f0;
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}

        .container {{ max-width: 1600px; margin: 0 auto; padding: 2rem; }}

        header {{
            background: linear-gradient(135deg, #1e3a8a 0%, #7c3aed 100%);
            color: white;
            padding: 3rem 2rem;
            margin-bottom: 2rem;
            border-radius: 1rem;
        }}

        header h1 {{ font-size: 2.5rem; margin-bottom: 0.5rem; }}
        header p {{ opacity: 0.9; font-size: 1.1rem; }}
        .header-meta {{ margin-top: 1rem; opacity: 0.8; font-size: 0.9rem; }}

        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}

        .summary-card {{
            background: var(--card);
            border-radius: 1rem;
            padding: 1.5rem;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        }}

        .summary-card h3 {{ color: var(--muted); font-size: 0.875rem; margin-bottom: 0.5rem; }}
        .summary-card .value {{ font-size: 1.75rem; font-weight: 700; }}
        .summary-card .detail {{ color: var(--muted); font-size: 0.875rem; margin-top: 0.25rem; }}

        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-graviton {{ background: #d1fae5; color: #065f46; }}
        .badge-intel {{ background: #dbeafe; color: #1e40af; }}
        .badge-amd {{ background: #fee2e2; color: #991b1b; }}

        .toc {{
            background: var(--card);
            border-radius: 1rem;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }}

        .toc h2 {{ margin-bottom: 1rem; }}
        .toc ul {{ list-style: none; columns: 2; }}
        .toc li {{ margin-bottom: 0.5rem; }}
        .toc a {{ color: var(--intel); text-decoration: none; }}
        .toc a:hover {{ text-decoration: underline; }}

        .section {{
            background: var(--card);
            border-radius: 1rem;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        }}

        .section h2 {{
            font-size: 1.5rem;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid var(--border);
        }}

        .chart-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 2rem;
        }}

        .chart-container {{
            background: #fafafa;
            border-radius: 0.75rem;
            padding: 1.5rem;
            height: 450px;
        }}

        .chart-container.tall {{ height: 600px; }}
        .chart-container.extra-tall {{ height: 900px; }}

        .chart-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 1rem;
            text-align: center;
        }}

        .insights {{
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            border-left: 4px solid #f59e0b;
            border-radius: 0 0.5rem 0.5rem 0;
            padding: 1rem 1.5rem;
            margin: 1.5rem 0;
        }}

        .insights h4 {{ color: #92400e; margin-bottom: 0.5rem; }}
        .insights ul {{ margin-left: 1.25rem; }}
        .insights li {{ margin-bottom: 0.25rem; }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }}

        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}

        th {{
            background: #f1f5f9;
            font-weight: 600;
            position: sticky;
            top: 0;
        }}

        th[data-sort] {{ cursor: pointer; }}
        th[data-sort]:hover {{ background: #e2e8f0; }}

        tr:hover {{ background: #f8fafc; }}

        .table-container {{
            max-height: 600px;
            overflow-y: auto;
            border-radius: 0.5rem;
            border: 1px solid var(--border);
        }}

        .filters {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }}

        .filter-group {{ display: flex; gap: 0.5rem; align-items: center; }}
        .filter-group label {{ font-weight: 500; color: var(--muted); }}

        select, input {{
            padding: 0.5rem;
            border: 1px solid var(--border);
            border-radius: 0.5rem;
            font-size: 0.875rem;
        }}

        .legend-custom {{
            display: flex;
            justify-content: center;
            gap: 2rem;
            margin-top: 1rem;
        }}

        .legend-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .legend-color {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
        }}

        footer {{
            text-align: center;
            padding: 2rem;
            color: var(--muted);
        }}

        @media (max-width: 768px) {{
            .chart-grid {{ grid-template-columns: 1fr; }}
            .toc ul {{ columns: 1; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Sysbench 종합 벤치마크 리포트</h1>
            <p>CPU + Memory 성능 분석 | 51개 EC2 인스턴스 타입 비교</p>
            <div class="header-meta">
                생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')} |
                리전: ap-northeast-2 (서울) |
                인스턴스 크기: xlarge (4 vCPU)
            </div>
        </header>

        <!-- Summary Cards -->
        <div class="summary-cards">
            <div class="summary-card">
                <h3>최고 CPU 성능 (Multi-thread)</h3>
                <div class="value">{top_cpu_mt[0]['name'] if top_cpu_mt else 'N/A'}</div>
                <div class="detail">{top_cpu_mt[0]['cpu_mt']:,.0f} events/sec</div>
                <span class="badge badge-{top_cpu_mt[0]['arch'] if top_cpu_mt else 'intel'}">{top_cpu_mt[0]['arch'].upper() if top_cpu_mt else ''}</span>
            </div>
            <div class="summary-card">
                <h3>최고 CPU 성능 (Single-thread)</h3>
                <div class="value">{top_cpu_st[0]['name'] if top_cpu_st else 'N/A'}</div>
                <div class="detail">{top_cpu_st[0]['cpu_st']:,.0f} events/sec</div>
                <span class="badge badge-{top_cpu_st[0]['arch'] if top_cpu_st else 'intel'}">{top_cpu_st[0]['arch'].upper() if top_cpu_st else ''}</span>
            </div>
            <div class="summary-card">
                <h3>최고 메모리 대역폭</h3>
                <div class="value">{top_mem_bw[0]['name'] if top_mem_bw else 'N/A'}</div>
                <div class="detail">{top_mem_bw[0]['mem_large_block']:,.0f} MiB/sec</div>
                <span class="badge badge-{top_mem_bw[0]['arch'] if top_mem_bw else 'intel'}">{top_mem_bw[0]['arch'].upper() if top_mem_bw else ''}</span>
            </div>
            <div class="summary-card">
                <h3>최고 가성비 (CPU)</h3>
                <div class="value">{top_efficiency[0]['name'] if top_efficiency else 'N/A'}</div>
                <div class="detail">{top_efficiency[0]['cpu_efficiency']:,.0f} events/$/hr</div>
                <span class="badge badge-{top_efficiency[0]['arch'] if top_efficiency else 'intel'}">{top_efficiency[0]['arch'].upper() if top_efficiency else ''}</span>
            </div>
        </div>

        <!-- 목차 -->
        <div class="toc">
            <h2>목차</h2>
            <ul>
                <li><a href="#methodology">테스트 방법론</a></li>
                <li><a href="#cpu-overview">CPU 성능 개요</a></li>
                <li><a href="#memory-overview">메모리 성능 개요</a></li>
                <li><a href="#generation">세대별 아키텍처 성능 비교</a></li>
                <li><a href="#price-performance">가격 대비 성능</a></li>
                <li><a href="#full-results">전체 결과</a></li>
                <li><a href="#conclusion">결론</a></li>
            </ul>
        </div>

        <!-- 테스트 방법론 -->
        <section class="section" id="methodology">
            <h2>테스트 방법론</h2>

            <!-- 테스트 환경 -->
            <div style="background: var(--bg); border-radius: 0.5rem; padding: 1.5rem; margin-bottom: 1.5rem;">
                <h3 style="margin-top: 0;">테스트 환경</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0; width: 200px;"><strong>도구</strong></td><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;">sysbench 1.0.20 (LuaJIT 2.1.0-beta3)</td></tr>
                    <tr><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;"><strong>OS</strong></td><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;">Ubuntu 22.04 (Docker image)</td></tr>
                    <tr><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;"><strong>플랫폼</strong></td><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;">Amazon EKS (Kubernetes 1.34)</td></tr>
                    <tr><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;"><strong>노드 프로비저닝</strong></td><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;">Karpenter 1.5.0 (노드 자동 스케일링)</td></tr>
                    <tr><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;"><strong>노드 격리</strong></td><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;">podAntiAffinity로 벤치마크당 단일 노드 보장</td></tr>
                    <tr><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;"><strong>인스턴스 크기</strong></td><td style="padding: 0.5rem; border-bottom: 1px solid #e2e8f0;">xlarge (4 vCPU) - 51개 인스턴스 타입</td></tr>
                    <tr><td style="padding: 0.5rem;"><strong>리전</strong></td><td style="padding: 0.5rem;">ap-northeast-2 (서울)</td></tr>
                </table>
            </div>

            <div class="chart-grid">
                <div>
                    <h3>CPU 벤치마크</h3>
                    <p>소수 계산을 통한 정수 연산 성능 측정</p>
                    <ul>
                        <li><strong>Multi-thread</strong>: 4 threads, 60초, 3회 반복 후 평균</li>
                        <li><strong>Single-thread</strong>: 1 thread, 30초</li>
                        <li><strong>Prime limit</strong>: 20,000</li>
                        <li><strong>측정 단위</strong>: events/sec (높을수록 좋음)</li>
                    </ul>
                    <div style="background: #1e293b; color: #e2e8f0; padding: 1rem; border-radius: 0.5rem; font-family: monospace; font-size: 0.85rem; margin-top: 1rem; overflow-x: auto;">
                        <div style="color: #94a3b8;"># Multi-thread (3회 반복)</div>
                        sysbench cpu --threads=4 --time=60 --cpu-max-prime=20000 run<br><br>
                        <div style="color: #94a3b8;"># Single-thread</div>
                        sysbench cpu --threads=1 --time=30 --cpu-max-prime=20000 run
                    </div>
                </div>
                <div>
                    <h3>메모리 벤치마크</h3>
                    <p>다양한 메모리 접근 패턴 성능 측정 (5회 반복)</p>
                    <ul>
                        <li><strong>Sequential Write/Read (1K)</strong>: 순차 접근, 캐시 효율성</li>
                        <li><strong>Random Write/Read (1K)</strong>: 무작위 접근, 실제 워크로드</li>
                        <li><strong>Large Block (1M)</strong>: 실제 메모리 대역폭</li>
                        <li><strong>측정 단위</strong>: MiB/sec (높을수록 좋음)</li>
                    </ul>
                    <div style="background: #1e293b; color: #e2e8f0; padding: 1rem; border-radius: 0.5rem; font-family: monospace; font-size: 0.85rem; margin-top: 1rem; overflow-x: auto;">
                        <div style="color: #94a3b8;"># Sequential Write (1K block)</div>
                        sysbench memory --threads=4 --time=60 \\<br>
                        &nbsp;&nbsp;--memory-block-size=1K --memory-total-size=100G \\<br>
                        &nbsp;&nbsp;--memory-oper=write --memory-access-mode=seq run<br><br>
                        <div style="color: #94a3b8;"># Large Block (1M block)</div>
                        sysbench memory --threads=4 --time=60 \\<br>
                        &nbsp;&nbsp;--memory-block-size=1M --memory-total-size=100G \\<br>
                        &nbsp;&nbsp;--memory-oper=write --memory-access-mode=seq run
                    </div>
                </div>
            </div>

            <div class="insights">
                <h4>왜 Large Block (1M)이 중요한가?</h4>
                <ul>
                    <li>1K 블록 테스트는 CPU 캐시와 메모리 컨트롤러 효율성을 측정</li>
                    <li><strong>Large Block (1M)</strong>은 실제 메모리 대역폭을 측정 - 대용량 데이터 처리 성능 지표</li>
                    <li>데이터 분석, ML 워크로드에서는 Large Block 성능이 더 중요</li>
                </ul>
            </div>
        </section>

        <!-- CPU 성능 개요 -->
        <section class="section" id="cpu-overview">
            <h2>CPU 성능 개요</h2>
            <div class="chart-grid">
                <div class="chart-container tall">
                    <div class="chart-title">CPU Multi-thread 성능 Top 25</div>
                    <canvas id="cpuMtChart"></canvas>
                </div>
                <div class="chart-container tall">
                    <div class="chart-title">CPU Single-thread 성능 Top 25</div>
                    <canvas id="cpuStChart"></canvas>
                </div>
            </div>
            <div class="legend-custom">
                <div class="legend-item"><div class="legend-color" style="background: rgba(16, 185, 129, 0.7);"></div><span>Graviton</span></div>
                <div class="legend-item"><div class="legend-color" style="background: rgba(59, 130, 246, 0.7);"></div><span>Intel</span></div>
                <div class="legend-item"><div class="legend-color" style="background: rgba(239, 68, 68, 0.7);"></div><span>AMD</span></div>
            </div>
        </section>

        <!-- 메모리 성능 개요 -->
        <section class="section" id="memory-overview">
            <h2>메모리 성능 개요 (5가지 메트릭)</h2>

            <!-- Row 1: Large Block -->
            <div class="chart-container extra-tall" style="margin-bottom: 2rem;">
                <div class="chart-title">Large Block (1M) 메모리 대역폭 Top 25 - 실제 메모리 대역폭</div>
                <canvas id="memLargeBlockChart"></canvas>
            </div>

            <!-- Row 2: Sequential -->
            <div class="chart-grid">
                <div class="chart-container tall">
                    <div class="chart-title">Sequential Write (1K) Top 25</div>
                    <canvas id="memSeqWriteOverviewChart"></canvas>
                </div>
                <div class="chart-container tall">
                    <div class="chart-title">Sequential Read (1K) Top 25</div>
                    <canvas id="memSeqReadChart"></canvas>
                </div>
            </div>

            <!-- Row 3: Random -->
            <div class="chart-grid" style="margin-top: 2rem;">
                <div class="chart-container tall">
                    <div class="chart-title">Random Write (1K) Top 25</div>
                    <canvas id="memRndWriteOverviewChart"></canvas>
                </div>
                <div class="chart-container tall">
                    <div class="chart-title">Random Read (1K) Top 25</div>
                    <canvas id="memRndReadOverviewChart"></canvas>
                </div>
            </div>

            <div class="legend-custom" style="margin-top: 1.5rem;">
                <div class="legend-item"><div class="legend-color" style="background: rgba(16, 185, 129, 0.7);"></div><span>Graviton</span></div>
                <div class="legend-item"><div class="legend-color" style="background: rgba(59, 130, 246, 0.7);"></div><span>Intel</span></div>
                <div class="legend-item"><div class="legend-color" style="background: rgba(239, 68, 68, 0.7);"></div><span>AMD</span></div>
            </div>

            <div class="insights">
                <h4>메모리 메트릭 해석</h4>
                <ul>
                    <li><strong>Large Block (1M)</strong>: 실제 메모리 대역폭 측정 - 대용량 데이터 처리에 가장 중요</li>
                    <li><strong>Sequential (1K)</strong>: CPU 캐시 및 메모리 컨트롤러 효율성 측정</li>
                    <li><strong>Random (1K)</strong>: 무작위 접근 패턴 - 실제 애플리케이션 워크로드에 가까움</li>
                    <li>AMD 인스턴스는 1K 테스트에서 높은 점수를 보이나, Large Block에서는 Graviton/Intel 대비 낮음</li>
                </ul>
            </div>
        </section>

        <!-- 세대별 아키텍처별 성능 비교 -->
        <section class="section" id="generation">
            <h2>세대별 아키텍처 성능 비교</h2>
            <p style="color: var(--muted); margin-bottom: 1rem;">5세대: Intel + AMD | 6~8세대: Intel + Graviton</p>
            <div class="chart-grid">
                <div class="chart-container tall">
                    <div class="chart-title">세대별 CPU Multi-thread 평균 (아키텍처 구분)</div>
                    <canvas id="genArchCpuChart"></canvas>
                </div>
                <div class="chart-container tall">
                    <div class="chart-title">세대별 메모리 Large Block 평균 (아키텍처 구분)</div>
                    <canvas id="genArchMemChart"></canvas>
                </div>
            </div>

            <!-- 세대별 성능 추이 라인 차트 -->
            <div class="chart-container" style="height: 400px; margin-top: 2rem;">
                <div class="chart-title">CPU 성능 추이: 패밀리별 Graviton vs Intel (AMD 제외)</div>
                <canvas id="genTrendChart"></canvas>
            </div>
            <div class="legend-custom" style="margin-top: 1rem;">
                <div class="legend-item"><span style="display:inline-block;width:30px;border-bottom:2px solid #3b82f6;margin-right:5px;"></span>Intel (실선)</div>
                <div class="legend-item"><span style="display:inline-block;width:30px;border-bottom:2px dashed #10b981;margin-right:5px;"></span>Graviton (점선)</div>
            </div>

            <div class="insights">
                <h4>세대별 성능 추이 인사이트</h4>
                <ul>
                    <li><strong>Graviton</strong>: 6세대부터 시작, 매 세대 10-15% 성능 향상</li>
                    <li><strong>Intel</strong>: 5세대 → 6세대에서 큰 폭 향상 (Ice Lake), 이후 점진적 개선</li>
                    <li><strong>8세대</strong>: Graviton4가 Intel 대비 약 80% 높은 CPU 성능</li>
                    <li>C/M/R 패밀리 간 동일 아키텍처에서는 성능 차이 거의 없음</li>
                </ul>
            </div>
        </section>

        <!-- 가격 대비 성능 -->
        <section class="section" id="price-performance">
            <h2>가격 대비 성능</h2>
            <div class="chart-grid">
                <div class="chart-container tall">
                    <div class="chart-title">CPU 가성비 (events per $/hr) Top 20</div>
                    <canvas id="cpuEfficiencyChart"></canvas>
                </div>
                <div class="chart-container tall">
                    <div class="chart-title">메모리 가성비 (MiB/sec per $/hr) Top 20</div>
                    <canvas id="memEfficiencyChart"></canvas>
                </div>
            </div>
            <div class="chart-container" style="height: 500px; margin-top: 2rem;">
                <div class="chart-title">가격 vs CPU 성능 (버블 크기 = 메모리 대역폭)</div>
                <canvas id="pricePerformanceChart"></canvas>
            </div>
            <div class="legend-custom">
                <div class="legend-item"><div class="legend-color" style="background: rgba(16, 185, 129, 0.7);"></div><span>Graviton</span></div>
                <div class="legend-item"><div class="legend-color" style="background: rgba(59, 130, 246, 0.7);"></div><span>Intel</span></div>
                <div class="legend-item"><div class="legend-color" style="background: rgba(239, 68, 68, 0.7);"></div><span>AMD</span></div>
            </div>
        </section>


        <!-- 전체 결과 테이블 -->
        <section class="section" id="full-results">
            <h2>전체 결과</h2>
            <div class="filters">
                <div class="filter-group">
                    <label>검색:</label>
                    <input type="text" id="searchInput" placeholder="인스턴스명...">
                </div>
                <div class="filter-group">
                    <label>아키텍처:</label>
                    <select id="archFilter">
                        <option value="">전체</option>
                        <option value="graviton">Graviton</option>
                        <option value="intel">Intel</option>
                        <option value="amd">AMD</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>세대:</label>
                    <select id="genFilter">
                        <option value="">전체</option>
                        <option value="8">8세대</option>
                        <option value="7">7세대</option>
                        <option value="6">6세대</option>
                        <option value="5">5세대</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>패밀리:</label>
                    <select id="familyFilter">
                        <option value="">전체</option>
                        <option value="c">C (Compute)</option>
                        <option value="m">M (General)</option>
                        <option value="r">R (Memory)</option>
                    </select>
                </div>
            </div>
            <div class="table-container">
                <table id="resultsTable">
                    <thead>
                        <tr>
                            <th data-sort="name">인스턴스</th>
                            <th>아키텍처</th>
                            <th data-sort="gen">세대</th>
                            <th data-sort="cpu_mt">CPU MT</th>
                            <th data-sort="cpu_st">CPU ST</th>
                            <th data-sort="mem_seq_write">Seq Write</th>
                            <th data-sort="mem_seq_read">Seq Read</th>
                            <th data-sort="mem_rnd_write">Rnd Write</th>
                            <th data-sort="mem_rnd_read">Rnd Read</th>
                            <th data-sort="mem_large_block">Large Block</th>
                            <th data-sort="price">$/hr</th>
                            <th data-sort="cpu_efficiency">CPU 효율</th>
                        </tr>
                    </thead>
                    <tbody id="resultsBody">
                    </tbody>
                </table>
            </div>
        </section>

        <!-- 결론 -->
        <section class="section" id="conclusion">
            <h2>결론 및 권장사항</h2>
            <div class="chart-grid">
                <div>
                    <h3>CPU 집약적 워크로드</h3>
                    <ul>
                        <li><strong>최고 성능</strong>: c8g.xlarge (Graviton4) - 8세대 최신</li>
                        <li><strong>최고 가성비</strong>: c7g.xlarge (Graviton3) - 가격 대비 우수</li>
                        <li>Intel 8세대 (c8i)도 좋은 성능, AMD는 추천하지 않음</li>
                    </ul>
                </div>
                <div>
                    <h3>메모리 집약적 워크로드</h3>
                    <ul>
                        <li><strong>최고 대역폭</strong>: Graviton4 계열 (r8g, m8g, c8g)</li>
                        <li><strong>가성비</strong>: c8g.xlarge - 낮은 가격에 높은 메모리 대역폭</li>
                        <li>데이터 분석/ML: Graviton4 강력 추천</li>
                    </ul>
                </div>
            </div>

            <div class="insights">
                <h4>핵심 권장사항</h4>
                <ul>
                    <li><strong>범용 워크로드</strong>: m8g.xlarge 또는 m7g.xlarge 추천</li>
                    <li><strong>비용 최적화</strong>: c7g.xlarge (Graviton3) - 우수한 가성비</li>
                    <li><strong>최고 성능</strong>: c8g.xlarge 또는 r8g.xlarge (Graviton4)</li>
                    <li><strong>레거시 x86 필요 시</strong>: c8i.xlarge 또는 m8i.xlarge</li>
                </ul>
            </div>
        </section>

        <footer>
            <p>Generated by EKS EC2 Benchmark Suite | {datetime.now().strftime('%Y-%m-%d')}</p>
        </footer>
    </div>

    <script>
        // 데이터
        const data = {json.dumps(js_data, ensure_ascii=False)};

        // 색상 함수
        function getColor(arch, alpha = 0.7) {{
            const colors = {{
                'graviton': `rgba(16, 185, 129, ${{alpha}})`,
                'intel': `rgba(59, 130, 246, ${{alpha}})`,
                'amd': `rgba(239, 68, 68, ${{alpha}})`
            }};
            return colors[arch] || colors['intel'];
        }}

        // 공통 차트 옵션
        const commonOptions = {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                legend: {{ display: false }}
            }}
        }};

        // CPU Multi-thread Top 25
        const cpuMtTop = [...data].filter(d => d.cpu_mt > 0).sort((a, b) => b.cpu_mt - a.cpu_mt).slice(0, 25);
        new Chart(document.getElementById('cpuMtChart'), {{
            type: 'bar',
            data: {{
                labels: cpuMtTop.map(d => d.name),
                datasets: [{{
                    data: cpuMtTop.map(d => d.cpu_mt),
                    backgroundColor: cpuMtTop.map(d => getColor(d.arch)),
                    borderColor: cpuMtTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'events/sec' }} }}
                }}
            }}
        }});

        // CPU Single-thread Top 25
        const cpuStTop = [...data].filter(d => d.cpu_st > 0).sort((a, b) => b.cpu_st - a.cpu_st).slice(0, 25);
        new Chart(document.getElementById('cpuStChart'), {{
            type: 'bar',
            data: {{
                labels: cpuStTop.map(d => d.name),
                datasets: [{{
                    data: cpuStTop.map(d => d.cpu_st),
                    backgroundColor: cpuStTop.map(d => getColor(d.arch)),
                    borderColor: cpuStTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'events/sec' }} }}
                }}
            }}
        }});

        // Memory Large Block Top 25
        const memLbTop = [...data].filter(d => d.mem_large_block > 0).sort((a, b) => b.mem_large_block - a.mem_large_block).slice(0, 25);
        new Chart(document.getElementById('memLargeBlockChart'), {{
            type: 'bar',
            data: {{
                labels: memLbTop.map(d => d.name),
                datasets: [{{
                    data: memLbTop.map(d => d.mem_large_block),
                    backgroundColor: memLbTop.map(d => getColor(d.arch)),
                    borderColor: memLbTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'MiB/sec' }} }}
                }}
            }}
        }});

        // Memory Seq Read Top 25
        const memSrTop = [...data].filter(d => d.mem_seq_read > 0).sort((a, b) => b.mem_seq_read - a.mem_seq_read).slice(0, 25);
        new Chart(document.getElementById('memSeqReadChart'), {{
            type: 'bar',
            data: {{
                labels: memSrTop.map(d => d.name),
                datasets: [{{
                    data: memSrTop.map(d => d.mem_seq_read),
                    backgroundColor: memSrTop.map(d => getColor(d.arch)),
                    borderColor: memSrTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'MiB/sec' }} }}
                }}
            }}
        }});

        // Memory Seq Write Overview Top 25
        const memSwOverviewTop = [...data].filter(d => d.mem_seq_write > 0).sort((a, b) => b.mem_seq_write - a.mem_seq_write).slice(0, 25);
        new Chart(document.getElementById('memSeqWriteOverviewChart'), {{
            type: 'bar',
            data: {{
                labels: memSwOverviewTop.map(d => d.name),
                datasets: [{{
                    data: memSwOverviewTop.map(d => d.mem_seq_write),
                    backgroundColor: memSwOverviewTop.map(d => getColor(d.arch)),
                    borderColor: memSwOverviewTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'MiB/sec' }} }}
                }}
            }}
        }});

        // Memory Random Write Overview Top 25
        const memRwOverviewTop = [...data].filter(d => d.mem_rnd_write > 0).sort((a, b) => b.mem_rnd_write - a.mem_rnd_write).slice(0, 25);
        new Chart(document.getElementById('memRndWriteOverviewChart'), {{
            type: 'bar',
            data: {{
                labels: memRwOverviewTop.map(d => d.name),
                datasets: [{{
                    data: memRwOverviewTop.map(d => d.mem_rnd_write),
                    backgroundColor: memRwOverviewTop.map(d => getColor(d.arch)),
                    borderColor: memRwOverviewTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'MiB/sec' }} }}
                }}
            }}
        }});

        // Memory Random Read Overview Top 25
        const memRrOverviewTop = [...data].filter(d => d.mem_rnd_read > 0).sort((a, b) => b.mem_rnd_read - a.mem_rnd_read).slice(0, 25);
        new Chart(document.getElementById('memRndReadOverviewChart'), {{
            type: 'bar',
            data: {{
                labels: memRrOverviewTop.map(d => d.name),
                datasets: [{{
                    data: memRrOverviewTop.map(d => d.mem_rnd_read),
                    backgroundColor: memRrOverviewTop.map(d => getColor(d.arch)),
                    borderColor: memRrOverviewTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'MiB/sec' }} }}
                }}
            }}
        }});

        // 세대별 아키텍처별 데이터 수집
        const genArchData = {{}};
        const genArchMemData = {{}};
        ['5', '6', '7', '8'].forEach(g => {{
            genArchData[g] = {{'intel': [], 'amd': [], 'graviton': []}};
            genArchMemData[g] = {{'intel': [], 'amd': [], 'graviton': []}};
        }});
        data.forEach(d => {{
            const gen = String(d.gen);
            if (genArchData[gen]) {{
                if (d.cpu_mt > 0) genArchData[gen][d.arch].push(d.cpu_mt);
                if (d.mem_large_block > 0) genArchMemData[gen][d.arch].push(d.mem_large_block);
            }}
        }});

        // 평균 계산 함수
        const avg = arr => arr.length > 0 ? arr.reduce((a,b) => a+b, 0) / arr.length : 0;

        // 세대별 아키텍처별 CPU Chart (Grouped Bar)
        new Chart(document.getElementById('genArchCpuChart'), {{
            type: 'bar',
            data: {{
                labels: ['5세대', '6세대', '7세대', '8세대'],
                datasets: [
                    {{
                        label: 'Intel',
                        data: ['5', '6', '7', '8'].map(g => avg(genArchData[g].intel)),
                        backgroundColor: 'rgba(59, 130, 246, 0.8)',
                        borderColor: 'rgba(59, 130, 246, 1)',
                        borderWidth: 1
                    }},
                    {{
                        label: 'AMD',
                        data: ['5', '6', '7', '8'].map(g => avg(genArchData[g].amd)),
                        backgroundColor: 'rgba(239, 68, 68, 0.8)',
                        borderColor: 'rgba(239, 68, 68, 1)',
                        borderWidth: 1
                    }},
                    {{
                        label: 'Graviton',
                        data: ['5', '6', '7', '8'].map(g => avg(genArchData[g].graviton)),
                        backgroundColor: 'rgba(16, 185, 129, 0.8)',
                        borderColor: 'rgba(16, 185, 129, 1)',
                        borderWidth: 1
                    }}
                ]
            }},
            options: {{
                ...commonOptions,
                plugins: {{
                    legend: {{ display: true, position: 'top' }},
                    tooltip: {{
                        callbacks: {{
                            label: ctx => {{
                                const count = genArchData[['5','6','7','8'][ctx.dataIndex]][ctx.dataset.label.toLowerCase()].length;
                                return `${{ctx.dataset.label}}: ${{ctx.raw.toFixed(0)}} events/sec (${{count}}개)`;
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{ title: {{ display: true, text: 'events/sec' }}, beginAtZero: true }}
                }}
            }}
        }});

        // 세대별 아키텍처별 Memory Chart (Grouped Bar)
        new Chart(document.getElementById('genArchMemChart'), {{
            type: 'bar',
            data: {{
                labels: ['5세대', '6세대', '7세대', '8세대'],
                datasets: [
                    {{
                        label: 'Intel',
                        data: ['5', '6', '7', '8'].map(g => avg(genArchMemData[g].intel)),
                        backgroundColor: 'rgba(59, 130, 246, 0.8)',
                        borderColor: 'rgba(59, 130, 246, 1)',
                        borderWidth: 1
                    }},
                    {{
                        label: 'AMD',
                        data: ['5', '6', '7', '8'].map(g => avg(genArchMemData[g].amd)),
                        backgroundColor: 'rgba(239, 68, 68, 0.8)',
                        borderColor: 'rgba(239, 68, 68, 1)',
                        borderWidth: 1
                    }},
                    {{
                        label: 'Graviton',
                        data: ['5', '6', '7', '8'].map(g => avg(genArchMemData[g].graviton)),
                        backgroundColor: 'rgba(16, 185, 129, 0.8)',
                        borderColor: 'rgba(16, 185, 129, 1)',
                        borderWidth: 1
                    }}
                ]
            }},
            options: {{
                ...commonOptions,
                plugins: {{
                    legend: {{ display: true, position: 'top' }},
                    tooltip: {{
                        callbacks: {{
                            label: ctx => {{
                                const count = genArchMemData[['5','6','7','8'][ctx.dataIndex]][ctx.dataset.label.toLowerCase()].length;
                                return `${{ctx.dataset.label}}: ${{ctx.raw.toFixed(0)}} MiB/s (${{count}}개)`;
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{ title: {{ display: true, text: 'MiB/sec' }}, beginAtZero: true }}
                }}
            }}
        }});

        // 세대별 성능 추이 라인 차트 (패밀리별 Graviton vs Intel)
        const trendData = {{}};
        ['C', 'M', 'R'].forEach(f => {{
            ['intel', 'graviton'].forEach(a => {{
                const key = f + '_' + a;
                trendData[key] = {{}};
                [5, 6, 7, 8].forEach(g => trendData[key][g] = []);
            }});
        }});
        data.forEach(d => {{
            if (d.arch === 'amd' || d.cpu_mt <= 0) return;
            const key = d.family.toUpperCase() + '_' + d.arch;
            if (trendData[key] && trendData[key][d.gen]) {{
                trendData[key][d.gen].push(d.cpu_mt);
            }}
        }});
        const trendAvg = (key, gen) => {{
            const vals = trendData[key]?.[gen] || [];
            return vals.length ? Math.round(vals.reduce((a,b) => a+b, 0) / vals.length) : null;
        }};

        new Chart(document.getElementById('genTrendChart'), {{
            type: 'line',
            data: {{
                labels: ['5세대', '6세대', '7세대', '8세대'],
                datasets: [
                    {{ label: 'C Intel', data: [5,6,7,8].map(g => trendAvg('C_intel', g)), borderColor: '#3b82f6', backgroundColor: '#3b82f6', tension: 0.1, spanGaps: true, borderWidth: 2.5 }},
                    {{ label: 'C Graviton', data: [5,6,7,8].map(g => trendAvg('C_graviton', g)), borderColor: '#10b981', backgroundColor: '#10b981', tension: 0.1, spanGaps: true, borderWidth: 2.5, borderDash: [6, 3] }},
                    {{ label: 'M Intel', data: [5,6,7,8].map(g => trendAvg('M_intel', g)), borderColor: '#60a5fa', backgroundColor: '#60a5fa', tension: 0.1, spanGaps: true, borderWidth: 2 }},
                    {{ label: 'M Graviton', data: [5,6,7,8].map(g => trendAvg('M_graviton', g)), borderColor: '#34d399', backgroundColor: '#34d399', tension: 0.1, spanGaps: true, borderWidth: 2, borderDash: [6, 3] }},
                    {{ label: 'R Intel', data: [5,6,7,8].map(g => trendAvg('R_intel', g)), borderColor: '#93c5fd', backgroundColor: '#93c5fd', tension: 0.1, spanGaps: true, borderWidth: 1.5 }},
                    {{ label: 'R Graviton', data: [5,6,7,8].map(g => trendAvg('R_graviton', g)), borderColor: '#6ee7b7', backgroundColor: '#6ee7b7', tension: 0.1, spanGaps: true, borderWidth: 1.5, borderDash: [6, 3] }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: true, position: 'top' }},
                    tooltip: {{
                        callbacks: {{
                            label: ctx => `${{ctx.dataset.label}}: ${{ctx.raw ? ctx.raw.toLocaleString() : 'N/A'}} events/sec`
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: false,
                        title: {{ display: true, text: 'events/sec' }}
                    }}
                }}
            }}
        }});

        // CPU 가성비 Top 20
        const cpuEffTop = [...data].filter(d => d.cpu_efficiency > 0).sort((a, b) => b.cpu_efficiency - a.cpu_efficiency).slice(0, 20);
        new Chart(document.getElementById('cpuEfficiencyChart'), {{
            type: 'bar',
            data: {{
                labels: cpuEffTop.map(d => d.name),
                datasets: [{{
                    data: cpuEffTop.map(d => d.cpu_efficiency),
                    backgroundColor: cpuEffTop.map(d => getColor(d.arch)),
                    borderColor: cpuEffTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'events per $/hr' }} }}
                }}
            }}
        }});

        // Memory 가성비 Top 20
        const memEffTop = [...data].filter(d => d.mem_efficiency > 0).sort((a, b) => b.mem_efficiency - a.mem_efficiency).slice(0, 20);
        new Chart(document.getElementById('memEfficiencyChart'), {{
            type: 'bar',
            data: {{
                labels: memEffTop.map(d => d.name),
                datasets: [{{
                    data: memEffTop.map(d => d.mem_efficiency),
                    backgroundColor: memEffTop.map(d => getColor(d.arch)),
                    borderColor: memEffTop.map(d => getColor(d.arch, 1)),
                    borderWidth: 1
                }}]
            }},
            options: {{
                ...commonOptions,
                indexAxis: 'y',
                scales: {{
                    x: {{ title: {{ display: true, text: 'MiB/sec per $/hr' }} }}
                }}
            }}
        }});

        // 가격 vs 성능 버블 차트
        const priceData = data.filter(d => d.price > 0 && d.cpu_mt > 0);
        new Chart(document.getElementById('pricePerformanceChart'), {{
            type: 'bubble',
            data: {{
                datasets: [
                    {{
                        label: 'Graviton',
                        data: priceData.filter(d => d.arch === 'graviton').map(d => ({{
                            x: d.price,
                            y: d.cpu_mt,
                            r: Math.sqrt(d.mem_large_block) / 15,
                            name: d.name
                        }})),
                        backgroundColor: getColor('graviton', 0.6)
                    }},
                    {{
                        label: 'Intel',
                        data: priceData.filter(d => d.arch === 'intel').map(d => ({{
                            x: d.price,
                            y: d.cpu_mt,
                            r: Math.sqrt(d.mem_large_block) / 15,
                            name: d.name
                        }})),
                        backgroundColor: getColor('intel', 0.6)
                    }},
                    {{
                        label: 'AMD',
                        data: priceData.filter(d => d.arch === 'amd').map(d => ({{
                            x: d.price,
                            y: d.cpu_mt,
                            r: Math.sqrt(d.mem_large_block) / 15,
                            name: d.name
                        }})),
                        backgroundColor: getColor('amd', 0.6)
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: true }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                return context.raw.name + ': $' + context.raw.x + '/hr, ' + context.raw.y.toLocaleString() + ' events/sec';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{ title: {{ display: true, text: '시간당 가격 ($)' }} }},
                    y: {{ title: {{ display: true, text: 'CPU events/sec' }} }}
                }}
            }}
        }});

        // 테이블 렌더링
        function renderTable(filteredData) {{
            const tbody = document.getElementById('resultsBody');
            tbody.innerHTML = filteredData.map(d => `
                <tr>
                    <td><strong>${{d.name}}</strong></td>
                    <td><span class="badge badge-${{d.arch}}">${{d.arch.toUpperCase()}}</span></td>
                    <td>${{d.gen}}세대</td>
                    <td>${{d.cpu_mt.toLocaleString()}}</td>
                    <td>${{d.cpu_st.toLocaleString()}}</td>
                    <td>${{d.mem_seq_write.toLocaleString()}}</td>
                    <td>${{d.mem_seq_read.toLocaleString()}}</td>
                    <td>${{d.mem_rnd_write.toLocaleString()}}</td>
                    <td>${{d.mem_rnd_read.toLocaleString()}}</td>
                    <td><strong>${{d.mem_large_block.toLocaleString()}}</strong></td>
                    <td>$${{d.price.toFixed(3)}}</td>
                    <td>${{d.cpu_efficiency.toLocaleString()}}</td>
                </tr>
            `).join('');
        }}

        // 초기 테이블 렌더링
        renderTable(data.sort((a, b) => b.cpu_mt - a.cpu_mt));

        // 필터링
        function applyFilters() {{
            let filtered = [...data];

            const search = document.getElementById('searchInput').value.toLowerCase();
            const arch = document.getElementById('archFilter').value;
            const gen = document.getElementById('genFilter').value;
            const family = document.getElementById('familyFilter').value;

            if (search) filtered = filtered.filter(d => d.name.toLowerCase().includes(search));
            if (arch) filtered = filtered.filter(d => d.arch === arch);
            if (gen) filtered = filtered.filter(d => d.gen === parseInt(gen));
            if (family) filtered = filtered.filter(d => d.family === family);

            renderTable(filtered);
        }}

        document.getElementById('searchInput').addEventListener('input', applyFilters);
        document.getElementById('archFilter').addEventListener('change', applyFilters);
        document.getElementById('genFilter').addEventListener('change', applyFilters);
        document.getElementById('familyFilter').addEventListener('change', applyFilters);

        // 정렬
        let sortField = 'cpu_mt';
        let sortDir = -1;

        document.querySelectorAll('th[data-sort]').forEach(th => {{
            th.addEventListener('click', () => {{
                const field = th.dataset.sort;
                if (sortField === field) {{
                    sortDir *= -1;
                }} else {{
                    sortField = field;
                    sortDir = -1;
                }}

                const sorted = [...data].sort((a, b) => {{
                    if (typeof a[field] === 'string') {{
                        return sortDir * a[field].localeCompare(b[field]);
                    }}
                    return sortDir * (a[field] - b[field]);
                }});

                renderTable(sorted);
            }});
        }});
    </script>
</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Report generated: {output_path}")
    return len(js_data)

def main():
    base_path = Path('/home/ec2-user/benchmark/results')
    output_path = Path('/home/ec2-user/benchmark/reports/sysbench-report.html')

    print("Collecting CPU data...")
    cpu_data = collect_cpu_data(base_path)
    print(f"  Found {len(cpu_data)} instances with CPU data")

    print("Collecting Memory data...")
    memory_data = collect_memory_data(base_path)
    print(f"  Found {len(memory_data)} instances with Memory data")

    print("Generating HTML report...")
    count = generate_html_report(cpu_data, memory_data, output_path)
    print(f"  Report includes {count} instances")

    print(f"\nDone! Report saved to: {output_path}")

if __name__ == '__main__':
    main()
