#!/usr/bin/env python3
"""
Redis Benchmark Report Generator v3
Comprehensive report with pricing, trends, and recommendations
"""

import json
from pathlib import Path

RESULTS_DIR = Path("/home/ec2-user/benchmark/results/redis")
OUTPUT_FILE = RESULTS_DIR / "report.html"

# EC2 Pricing (ap-northeast-2, On-Demand, USD/hr)
PRICING = {
    'c5.xlarge': 0.192, 'c5d.xlarge': 0.220, 'c5n.xlarge': 0.244, 'c5a.xlarge': 0.172,
    'c6i.xlarge': 0.192, 'c6id.xlarge': 0.231, 'c6in.xlarge': 0.256,
    'c6g.xlarge': 0.154, 'c6gd.xlarge': 0.176, 'c6gn.xlarge': 0.195,
    'c7i.xlarge': 0.202, 'c7i-flex.xlarge': 0.192,
    'c7g.xlarge': 0.163, 'c7gd.xlarge': 0.208,
    'c8i.xlarge': 0.212, 'c8i-flex.xlarge': 0.201,
    'c8g.xlarge': 0.180,
    'm5.xlarge': 0.236, 'm5d.xlarge': 0.278, 'm5zn.xlarge': 0.406,
    'm5a.xlarge': 0.212, 'm5ad.xlarge': 0.254,
    'm6i.xlarge': 0.236, 'm6id.xlarge': 0.292, 'm6in.xlarge': 0.337, 'm6idn.xlarge': 0.386,
    'm6g.xlarge': 0.188, 'm6gd.xlarge': 0.222,
    'm7i.xlarge': 0.248, 'm7i-flex.xlarge': 0.235,
    'm7g.xlarge': 0.201, 'm7gd.xlarge': 0.263,
    'm8i.xlarge': 0.260, 'm8g.xlarge': 0.221,
    'r5.xlarge': 0.304, 'r5d.xlarge': 0.346, 'r5b.xlarge': 0.356, 'r5n.xlarge': 0.356, 'r5dn.xlarge': 0.398,
    'r5a.xlarge': 0.272, 'r5ad.xlarge': 0.316,
    'r6i.xlarge': 0.304, 'r6id.xlarge': 0.363,
    'r6g.xlarge': 0.244, 'r6gd.xlarge': 0.277,
    'r7i.xlarge': 0.319,
    'r7g.xlarge': 0.258, 'r7gd.xlarge': 0.327,
    'r8i.xlarge': 0.335, 'r8i-flex.xlarge': 0.318,
    'r8g.xlarge': 0.284,
}

def load_data():
    with open(RESULTS_DIR / "report-data.json", 'r') as f:
        return json.load(f)

def get_arch(instance):
    if any(g in instance for g in ['g.', 'gd.', 'gn.']):
        return 'graviton'
    if 'a.' in instance or 'ad.' in instance:
        return 'amd'
    return 'intel'

def get_gen(instance):
    for g in ['8', '7', '6', '5']:
        if g in instance.split('.')[0]:
            return int(g)
    return 5

def get_family(instance):
    if instance.startswith('c'):
        return 'c'
    if instance.startswith('m'):
        return 'm'
    return 'r'

def generate_html(data):
    # Prepare instance list with all metrics
    instances = []
    for name, d in data.items():
        set_ops = d.get('standard', {}).get('SET', 0)
        get_ops = d.get('standard', {}).get('GET', 0)
        price = PRICING.get(name, 0.25)
        efficiency = int(set_ops / (price * 1000)) if price > 0 else 0
        instances.append({
            'name': name,
            'arch': get_arch(name),
            'gen': get_gen(name),
            'family': get_family(name),
            'price': price,
            'setOps': set_ops,
            'getOps': get_ops,
            'efficiency': efficiency,
            'category': d.get('category', 'Unknown'),
            'standard': d.get('standard', {}),
            'pipeline': d.get('pipeline', {}),
            'high_concurrency': d.get('high_concurrency', {})
        })

    # Sort by SET performance
    instances.sort(key=lambda x: x['setOps'], reverse=True)
    for i, inst in enumerate(instances):
        inst['rank'] = i + 1

    # Find best performers
    best_set = max(instances, key=lambda x: x['setOps'])
    best_efficiency = max(instances, key=lambda x: x['efficiency'])
    best_intel = max([i for i in instances if i['arch'] == 'intel'], key=lambda x: x['setOps'])
    best_graviton = max([i for i in instances if i['arch'] == 'graviton'], key=lambda x: x['setOps'])

    # Calculate generation averages
    gen_avg = {}
    for gen in [5, 6, 7, 8]:
        intel_list = [i['setOps'] for i in instances if i['gen'] == gen and i['arch'] in ['intel', 'amd']]
        grav_list = [i['setOps'] for i in instances if i['gen'] == gen and i['arch'] == 'graviton']
        gen_avg[gen] = {
            'intel': int(sum(intel_list)/len(intel_list)) if intel_list else 0,
            'graviton': int(sum(grav_list)/len(grav_list)) if grav_list else 0
        }

    # JavaScript data
    js_data = json.dumps(instances)

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Redis Benchmark Report - 51 EC2 Instance Types</title>
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
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans KR', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}
        .container {{ max-width: 1600px; margin: 0 auto; padding: 2rem; }}
        header {{
            text-align: center;
            margin-bottom: 2rem;
            padding: 2rem;
            background: linear-gradient(135deg, #dc2626 0%, #ef4444 50%, #f97316 100%);
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
        .grid-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.5rem; }}
        .grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.5rem; }}
        .legend-custom {{
            display: flex;
            gap: 1.5rem;
            justify-content: center;
            margin-top: 1rem;
            flex-wrap: wrap;
        }}
        .legend-item {{ display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; }}
        .legend-color {{ width: 14px; height: 14px; border-radius: 3px; }}
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
        .analysis-box {{
            background: #f1f5f9;
            border-radius: 0.5rem;
            padding: 1rem;
            margin-top: 1rem;
        }}
        .analysis-box h4 {{ margin-bottom: 0.5rem; color: var(--text); }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.875rem; }}
        th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ background: #f1f5f9; font-weight: 600; }}
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
        @media (max-width: 1200px) {{ .grid-2, .grid-3 {{ grid-template-columns: 1fr; }} }}
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
            <h1>Redis Benchmark Report</h1>
            <p>AWS EC2 인스턴스 51종 성능 비교 분석 (5세대 ~ 8세대)</p>
            <p style="opacity: 0.7; margin-top: 0.5rem;">2026년 1월 | 서울 리전 (ap-northeast-2) | 테스트: redis-benchmark × 5회</p>
        </header>

        <!-- 요약 카드 -->
        <div class="summary-cards">
            <div class="card graviton">
                <h3>SET 최고 성능</h3>
                <div class="value">{best_set['name']}</div>
                <div class="label">{best_set['setOps']:,.0f} ops/sec</div>
            </div>
            <div class="card">
                <h3>최고 가성비</h3>
                <div class="value">{best_efficiency['name']}</div>
                <div class="label">효율성 {best_efficiency['efficiency']}점</div>
            </div>
            <div class="card">
                <h3>Intel 최강</h3>
                <div class="value">{best_intel['name']}</div>
                <div class="label">{best_intel['setOps']:,.0f} ops/sec</div>
            </div>
            <div class="card graviton">
                <h3>Graviton 최강</h3>
                <div class="value">{best_graviton['name']}</div>
                <div class="label">{best_graviton['setOps']:,.0f} ops/sec</div>
            </div>
            <div class="card">
                <h3>8세대 성능</h3>
                <div class="value">저조</div>
                <div class="label">5-7세대 대비 낮음</div>
            </div>
        </div>

        <!-- 목차 -->
        <div class="chart-section" style="padding: 1rem 1.5rem;">
            <h2>목차</h2>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.5rem; margin-top: 0.75rem;">
                <a href="#methodology" style="color: var(--intel); text-decoration: none;">1. 테스트 방법론</a>
                <a href="#top20" style="color: var(--intel); text-decoration: none;">2. Top 20 성능</a>
                <a href="#generation" style="color: var(--intel); text-decoration: none;">3. 세대별 추이</a>
                <a href="#m-series-comparison" style="color: var(--intel); text-decoration: none;">3.5 M시리즈 비교</a>
                <a href="#price" style="color: var(--intel); text-decoration: none;">4. 가격/가성비 분석</a>
                <a href="#recommendation" style="color: var(--intel); text-decoration: none;">5. 선택 가이드</a>
                <a href="#full-results" style="color: var(--intel); text-decoration: none;">6. 전체 결과</a>
            </div>
        </div>

        <!-- 1. 테스트 방법론 -->
        <div class="chart-section" id="methodology">
            <h2>1. 테스트 방법론</h2>
            <p class="description">Redis 벤치마크 측정 방법 및 환경</p>
            <div class="grid-3" style="margin-top: 1rem;">
                <div class="analysis-box" style="margin-top: 0;">
                    <h4>인프라 구성</h4>
                    <table>
                        <tr><td>플랫폼</td><td><strong>Amazon EKS 1.34</strong></td></tr>
                        <tr><td>리전</td><td>ap-northeast-2 (서울)</td></tr>
                        <tr><td>노드</td><td>Karpenter 동적 프로비저닝</td></tr>
                        <tr><td>격리</td><td>Pod Anti-affinity</td></tr>
                    </table>
                </div>
                <div class="analysis-box" style="margin-top: 0;">
                    <h4>테스트 설정</h4>
                    <table>
                        <tr><td>도구</td><td><strong>redis-benchmark</strong></td></tr>
                        <tr><td>클라이언트</td><td>50개 동시 연결</td></tr>
                        <tr><td>요청 수</td><td>100,000 requests</td></tr>
                        <tr><td>반복</td><td>5회 (평균값)</td></tr>
                    </table>
                </div>
                <div class="analysis-box" style="margin-top: 0;">
                    <h4>Redis 설정</h4>
                    <table>
                        <tr><td>버전</td><td><strong>Redis 7.4.7</strong></td></tr>
                        <tr><td>OS</td><td>Amazon Linux 2023</td></tr>
                        <tr><td>네트워크</td><td>동일 AZ 내 Pod간 통신</td></tr>
                        <tr><td>vCPU</td><td>4 (xlarge)</td></tr>
                    </table>
                </div>
            </div>

            <!-- Operation 설명 -->
            <div class="analysis-box" style="margin-top: 1rem;">
                <h4>Redis Operation 설명</h4>
                <table>
                    <thead>
                        <tr><th style="width: 100px;">Operation</th><th>설명</th><th>사용 사례</th></tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><strong>SET</strong></td>
                            <td>키-값 쌍 저장. Redis의 가장 기본적인 쓰기 작업</td>
                            <td>세션 저장, 캐시 데이터 저장, 설정값 저장</td>
                        </tr>
                        <tr>
                            <td><strong>GET</strong></td>
                            <td>키로 값 조회. 가장 빈번한 읽기 작업</td>
                            <td>캐시 조회, 세션 읽기, 실시간 데이터 조회</td>
                        </tr>
                        <tr>
                            <td><strong>INCR</strong></td>
                            <td>정수값 원자적 증가. 락 없이 동시성 안전</td>
                            <td>조회수 카운터, Rate Limiting, 시퀀스 생성</td>
                        </tr>
                        <tr>
                            <td><strong>LPUSH</strong></td>
                            <td>리스트 왼쪽에 요소 추가. O(1) 복잡도</td>
                            <td>메시지 큐, 최근 항목 관리, 로그 수집</td>
                        </tr>
                        <tr>
                            <td><strong>HSET</strong></td>
                            <td>해시 필드 설정. 객체 형태 데이터 저장</td>
                            <td>사용자 프로필, 상품 정보, 설정 그룹</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 2. Top 20 성능 -->
        <div class="chart-section" id="top20">
            <h2>2. Top 20 SET 성능</h2>
            <p class="description">초록: Graviton, 파랑: Intel, 빨강: AMD | 높을수록 좋음</p>
            <div class="chart-container tall">
                <canvas id="top20SetChart"></canvas>
            </div>
            <div class="legend-custom">
                <div class="legend-item"><div class="legend-color" style="background: #10b981;"></div><span>Graviton (arm64)</span></div>
                <div class="legend-item"><div class="legend-color" style="background: #3b82f6;"></div><span>Intel (x86_64)</span></div>
                <div class="legend-item"><div class="legend-color" style="background: #ef4444;"></div><span>AMD (x86_64)</span></div>
            </div>
        </div>

        <!-- 3. 세대별 추이 -->
        <div class="chart-section" id="generation">
            <h2>3. 세대별 평균 SET 성능 추이</h2>
            <p class="description">Intel/AMD vs Graviton 세대별 변화</p>
            <div class="grid-2">
                <div class="chart-container">
                    <canvas id="genTrendChart"></canvas>
                </div>
                <div class="chart-container">
                    <canvas id="genBarChart"></canvas>
                </div>
            </div>
            <div class="insights">
                <h4>핵심 인사이트</h4>
                <ul>
                    <li><strong>5-6세대</strong>: Intel이 전반적으로 우세</li>
                    <li><strong>7세대</strong>: Graviton이 성능 역전 (m7gd 전체 1위)</li>
                    <li><strong>8세대</strong>: Redis에서 성능 저하 - 모든 8세대 인스턴스가 하위권</li>
                    <li>신세대가 항상 빠른 것은 아님 (워크로드 특성에 따라 다름)</li>
                </ul>
            </div>
        </div>

        <!-- 3.5 M시리즈 세대별 전체 Operation 비교 -->
        <div class="chart-section" id="m-series-comparison">
            <h2>3.5 M시리즈 세대별/아키텍처별 전체 Operation 비교</h2>
            <p class="description">m5, m6i, m6g, m7i, m7g, m8i, m8g - SET/GET/INCR/LPUSH/HSET 비교</p>
            <div class="chart-container tall">
                <canvas id="mSeriesChart"></canvas>
            </div>
            <div class="legend-custom">
                <div class="legend-item"><div class="legend-color" style="background: #2196F3;"></div><span>SET</span></div>
                <div class="legend-item"><div class="legend-color" style="background: #4CAF50;"></div><span>GET</span></div>
                <div class="legend-item"><div class="legend-color" style="background: #FF9800;"></div><span>INCR</span></div>
                <div class="legend-item"><div class="legend-color" style="background: #9C27B0;"></div><span>LPUSH</span></div>
                <div class="legend-item"><div class="legend-color" style="background: #F44336;"></div><span>HSET</span></div>
            </div>
            <div class="analysis-box">
                <h4>M시리즈 분석</h4>
                <ul style="margin-left: 1.5rem; margin-top: 0.5rem;">
                    <li><strong>m5 vs m6i</strong>: 6세대 Intel이 약간 우세</li>
                    <li><strong>m6i vs m6g</strong>: Graviton2가 Intel 6세대와 비슷하거나 우세</li>
                    <li><strong>m7i vs m7g</strong>: Graviton3가 Intel 7세대보다 확실히 빠름</li>
                    <li><strong>m8i vs m8g</strong>: 8세대 모두 성능 저하, Graviton4가 상대적으로 양호</li>
                </ul>
            </div>
        </div>

        <!-- 4. 가격/가성비 분석 -->
        <div class="chart-section" id="price">
            <h2>4. 가격 대비 성능 분석</h2>
            <p class="description">X축: 시간당 비용($), Y축: SET ops/sec | 우측 상단이 최적</p>
            <div class="chart-container tall">
                <canvas id="pricePerformanceChart"></canvas>
            </div>
        </div>

        <div class="chart-section">
            <h2>가성비 Top 15 (효율성 점수)</h2>
            <p class="description">효율성 = SET ops/sec / ($/hr × 1000) | 높을수록 좋음</p>
            <div class="chart-container">
                <canvas id="efficiencyChart"></canvas>
            </div>
            <div class="analysis-box">
                <h4>효율성 공식</h4>
                <p style="font-family: monospace; background: #e2e8f0; padding: 0.5rem; border-radius: 4px; margin-top: 0.5rem;">
                    효율성 점수 = (SET ops/sec) ÷ (시간당 비용 × 1000)
                </p>
                <p style="margin-top: 0.5rem; color: var(--muted);">
                    예: c5.xlarge = {best_intel['setOps']:,.0f} ÷ (${best_intel['price']:.3f} × 1000) = {best_intel['efficiency']}점
                </p>
            </div>
        </div>

        <!-- 5. 선택 가이드 -->
        <div class="chart-section" id="recommendation">
            <h2>5. 인스턴스 선택 가이드</h2>
            <p class="description">용도별 추천 인스턴스</p>

            <table style="margin-top: 1.5rem;">
                <thead>
                    <tr>
                        <th>용도</th>
                        <th>추천 인스턴스</th>
                        <th>SET ops/sec</th>
                        <th>GET ops/sec</th>
                        <th>$/hr</th>
                        <th>효율성</th>
                        <th>선택 이유</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>최고 성능</strong></td>
                        <td><span class="badge badge-graviton">{best_set['name']}</span></td>
                        <td>{best_set['setOps']:,.0f}</td>
                        <td>{best_set['getOps']:,.0f}</td>
                        <td>${best_set['price']:.3f}</td>
                        <td>{best_set['efficiency']}</td>
                        <td>전체 1위</td>
                    </tr>
                    <tr>
                        <td><strong>최고 가성비</strong></td>
                        <td><span class="badge badge-intel">{best_efficiency['name']}</span></td>
                        <td>{best_efficiency['setOps']:,.0f}</td>
                        <td>{best_efficiency['getOps']:,.0f}</td>
                        <td>${best_efficiency['price']:.3f}</td>
                        <td>{best_efficiency['efficiency']}</td>
                        <td>효율성 1위</td>
                    </tr>
                    <tr>
                        <td><strong>Intel 최강</strong></td>
                        <td><span class="badge badge-intel">{best_intel['name']}</span></td>
                        <td>{best_intel['setOps']:,.0f}</td>
                        <td>{best_intel['getOps']:,.0f}</td>
                        <td>${best_intel['price']:.3f}</td>
                        <td>{best_intel['efficiency']}</td>
                        <td>x86 최고 성능</td>
                    </tr>
                    <tr>
                        <td><strong>Graviton 선호</strong></td>
                        <td><span class="badge badge-graviton">{best_graviton['name']}</span></td>
                        <td>{best_graviton['setOps']:,.0f}</td>
                        <td>{best_graviton['getOps']:,.0f}</td>
                        <td>${best_graviton['price']:.3f}</td>
                        <td>{best_graviton['efficiency']}</td>
                        <td>arm64 최고 성능</td>
                    </tr>
                </tbody>
            </table>

            <div class="grid-2" style="margin-top: 1.5rem;">
                <div class="insights" style="margin: 0;">
                    <h4>피해야 할 인스턴스</h4>
                    <ul>
                        <li><strong>8세대 전체</strong>: Redis에서 성능 저조</li>
                        <li><strong>flex 인스턴스</strong>: 버스팅 이점 없음</li>
                        <li><strong>r8g, r8i</strong>: 메모리 용량 필요 없으면 비효율</li>
                    </ul>
                </div>
                <div style="background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%); border-radius: 1rem; padding: 1.5rem; text-align: center;">
                    <div style="font-size: 0.875rem; color: #1e40af; margin-bottom: 0.5rem;">범용 Redis 캐시 추천</div>
                    <div style="font-size: 2rem; font-weight: 700; color: #1e3a8a;">{best_efficiency['name']}</div>
                    <div style="display: flex; justify-content: center; gap: 1rem; margin-top: 0.75rem; font-size: 0.875rem; color: #1e40af;">
                        <span>{best_efficiency['setOps']:,.0f} ops/sec</span>
                        <span>${best_efficiency['price']:.3f}/hr</span>
                        <span>효율성 1위</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- 6. 전체 결과 -->
        <div class="chart-section" id="full-results">
            <h2>6. 전체 결과 (51개 인스턴스)</h2>
            <p class="description">열 헤더 클릭으로 정렬</p>

            <div style="margin-bottom: 1rem; display: flex; gap: 1rem; flex-wrap: wrap;">
                <input type="text" id="tableSearch" placeholder="인스턴스 검색..."
                    style="padding: 0.5rem 1rem; border: 1px solid #e2e8f0; border-radius: 0.5rem; width: 200px;">
                <select id="archFilter" style="padding: 0.5rem 1rem; border: 1px solid #e2e8f0; border-radius: 0.5rem;">
                    <option value="">모든 아키텍처</option>
                    <option value="graviton">Graviton</option>
                    <option value="intel">Intel</option>
                    <option value="amd">AMD</option>
                </select>
                <select id="genFilter" style="padding: 0.5rem 1rem; border: 1px solid #e2e8f0; border-radius: 0.5rem;">
                    <option value="">모든 세대</option>
                    <option value="8">8세대</option>
                    <option value="7">7세대</option>
                    <option value="6">6세대</option>
                    <option value="5">5세대</option>
                </select>
            </div>

            <div style="overflow-x: auto;">
                <table id="fullResultsTable">
                    <thead>
                        <tr>
                            <th data-sort="rank" style="cursor: pointer;">순위 ▼</th>
                            <th data-sort="name" style="cursor: pointer;">인스턴스</th>
                            <th data-sort="arch" style="cursor: pointer;">아키텍처</th>
                            <th data-sort="gen" style="cursor: pointer;">세대</th>
                            <th data-sort="setOps" style="cursor: pointer;">SET ops/sec</th>
                            <th data-sort="getOps" style="cursor: pointer;">GET ops/sec</th>
                            <th data-sort="price" style="cursor: pointer;">$/hr</th>
                            <th data-sort="efficiency" style="cursor: pointer;">효율성</th>
                        </tr>
                    </thead>
                    <tbody id="fullResultsBody"></tbody>
                </table>
            </div>
        </div>

        <footer>
            <p>벤치마크 자동화 시스템 | 데이터 수집: 2026년 1월 | 리전: ap-northeast-2 (서울)</p>
            <p>테스트 환경: Amazon EKS 1.34 + Karpenter | {len(instances)}개 인스턴스</p>
        </footer>
    </div>

    <script>
        const allInstances = {js_data};
        const colorMap = {{ graviton: '#10b981', intel: '#3b82f6', amd: '#ef4444' }};
        const archLabel = {{ graviton: 'Graviton', intel: 'Intel', amd: 'AMD' }};
        const archBadge = {{ graviton: 'badge-graviton', intel: 'badge-intel', amd: 'badge-amd' }};

        // Chart 1: Top 20 SET
        const top20 = allInstances.slice(0, 20);
        new Chart(document.getElementById('top20SetChart'), {{
            type: 'bar',
            data: {{
                labels: top20.map(i => i.name),
                datasets: [{{
                    label: 'SET ops/sec',
                    data: top20.map(i => i.setOps),
                    backgroundColor: top20.map(i => colorMap[i.arch]),
                    borderRadius: 4,
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ title: {{ display: true, text: 'SET ops/sec' }}, ticks: {{ callback: v => v.toLocaleString() }} }},
                    y: {{ ticks: {{ font: {{ size: 11 }} }} }}
                }}
            }}
        }});

        // Chart 2: Generation Trend Line
        const genData = {{
            labels: ['5세대', '6세대', '7세대', '8세대'],
            intel: [{gen_avg[5]['intel']}, {gen_avg[6]['intel']}, {gen_avg[7]['intel']}, {gen_avg[8]['intel']}],
            graviton: [null, {gen_avg[6]['graviton']}, {gen_avg[7]['graviton']}, {gen_avg[8]['graviton']}]
        }};

        new Chart(document.getElementById('genTrendChart'), {{
            type: 'line',
            data: {{
                labels: genData.labels,
                datasets: [
                    {{ label: 'Intel/AMD', data: genData.intel, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0.3 }},
                    {{ label: 'Graviton', data: genData.graviton, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)', fill: true, tension: 0.3 }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top' }}, title: {{ display: true, text: '세대별 평균 SET ops/sec 추이' }} }},
                scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'SET ops/sec' }} }} }}
            }}
        }});

        // Chart 3: Generation Bar
        new Chart(document.getElementById('genBarChart'), {{
            type: 'bar',
            data: {{
                labels: genData.labels,
                datasets: [
                    {{ label: 'Intel/AMD', data: genData.intel, backgroundColor: '#3b82f6', borderRadius: 6 }},
                    {{ label: 'Graviton', data: genData.graviton, backgroundColor: '#10b981', borderRadius: 6 }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top' }}, title: {{ display: true, text: '세대별 아키텍처 비교' }} }},
                scales: {{ y: {{ beginAtZero: true }} }}
            }}
        }});

        // Chart 3.5: M-Series Comparison (5 operations)
        const mSeriesLabels = ['m5', 'm6i', 'm6g', 'm7i', 'm7g', 'm8i', 'm8g'];
        const mSeriesData = {{}};
        mSeriesLabels.forEach(label => {{
            const inst = allInstances.find(i => i.name === label + '.xlarge');
            if (inst && inst.standard) {{
                mSeriesData[label] = {{
                    SET: inst.standard.SET || 0,
                    GET: inst.standard.GET || 0,
                    INCR: inst.standard.INCR || 0,
                    LPUSH: inst.standard.LPUSH || 0,
                    HSET: inst.standard.HSET || 0
                }};
            }} else {{
                mSeriesData[label] = {{ SET: 0, GET: 0, INCR: 0, LPUSH: 0, HSET: 0 }};
            }}
        }});

        new Chart(document.getElementById('mSeriesChart'), {{
            type: 'bar',
            data: {{
                labels: mSeriesLabels.map(l => l.toUpperCase()),
                datasets: [
                    {{ label: 'SET', data: mSeriesLabels.map(l => mSeriesData[l].SET), backgroundColor: '#2196F3', borderRadius: 4 }},
                    {{ label: 'GET', data: mSeriesLabels.map(l => mSeriesData[l].GET), backgroundColor: '#4CAF50', borderRadius: 4 }},
                    {{ label: 'INCR', data: mSeriesLabels.map(l => mSeriesData[l].INCR), backgroundColor: '#FF9800', borderRadius: 4 }},
                    {{ label: 'LPUSH', data: mSeriesLabels.map(l => mSeriesData[l].LPUSH), backgroundColor: '#9C27B0', borderRadius: 4 }},
                    {{ label: 'HSET', data: mSeriesLabels.map(l => mSeriesData[l].HSET), backgroundColor: '#F44336', borderRadius: 4 }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ position: 'top' }},
                    title: {{
                        display: true,
                        text: 'M시리즈 세대별 Redis Operations (ops/sec)',
                        font: {{ size: 14 }}
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        title: {{ display: true, text: 'Operations/sec' }},
                        ticks: {{ callback: v => v.toLocaleString() }}
                    }},
                    x: {{
                        title: {{ display: true, text: '인스턴스 (세대순 정렬: 5세대 → 8세대)' }}
                    }}
                }}
            }}
        }});

        // Chart 4: Price vs Performance Bubble
        const bubbleData = allInstances.map(i => ({{ x: i.price, y: i.setOps, r: 8, label: i.name, arch: i.arch }}));
        new Chart(document.getElementById('pricePerformanceChart'), {{
            type: 'bubble',
            data: {{
                datasets: [
                    {{ label: 'Graviton', data: bubbleData.filter(d => d.arch === 'graviton'), backgroundColor: 'rgba(16, 185, 129, 0.6)', borderColor: '#10b981' }},
                    {{ label: 'Intel', data: bubbleData.filter(d => d.arch === 'intel'), backgroundColor: 'rgba(59, 130, 246, 0.6)', borderColor: '#3b82f6' }},
                    {{ label: 'AMD', data: bubbleData.filter(d => d.arch === 'amd'), backgroundColor: 'rgba(239, 68, 68, 0.6)', borderColor: '#ef4444' }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    tooltip: {{ callbacks: {{ label: (ctx) => [`${{ctx.raw.label}}`, `$${{ctx.raw.x.toFixed(3)}}/hr`, `${{ctx.raw.y.toLocaleString()}} ops/sec`] }} }}
                }},
                scales: {{
                    x: {{ title: {{ display: true, text: '시간당 비용 ($)' }}, min: 0.1, max: 0.45 }},
                    y: {{ title: {{ display: true, text: 'SET ops/sec' }}, min: 30000 }}
                }}
            }}
        }});

        // Chart 5: Efficiency Top 15
        const efficiency = [...allInstances].sort((a, b) => b.efficiency - a.efficiency).slice(0, 15);
        new Chart(document.getElementById('efficiencyChart'), {{
            type: 'bar',
            data: {{
                labels: efficiency.map(i => i.name),
                datasets: [{{
                    label: '효율성 점수',
                    data: efficiency.map(i => i.efficiency),
                    backgroundColor: efficiency.map(i => colorMap[i.arch]),
                    borderRadius: 6,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: '효율성 점수' }} }} }}
            }}
        }});

        // Full Results Table
        function renderTable(data) {{
            const tbody = document.getElementById('fullResultsBody');
            tbody.innerHTML = data.map((inst) => `
                <tr>
                    <td>${{inst.rank}}</td>
                    <td><strong>${{inst.name}}</strong></td>
                    <td><span class="badge ${{archBadge[inst.arch]}}">${{archLabel[inst.arch]}}</span></td>
                    <td>${{inst.gen}}세대</td>
                    <td>${{inst.setOps.toLocaleString()}}</td>
                    <td>${{inst.getOps.toLocaleString()}}</td>
                    <td>$${{inst.price.toFixed(3)}}</td>
                    <td>${{inst.efficiency}}</td>
                </tr>
            `).join('');
        }}
        renderTable(allInstances);

        // Filter
        function filterTable() {{
            const search = document.getElementById('tableSearch').value.toLowerCase();
            const arch = document.getElementById('archFilter').value;
            const gen = document.getElementById('genFilter').value;
            let filtered = allInstances.filter(inst => {{
                if (search && !inst.name.toLowerCase().includes(search)) return false;
                if (arch && inst.arch !== arch) return false;
                if (gen && inst.gen !== parseInt(gen)) return false;
                return true;
            }});
            renderTable(filtered);
        }}
        document.getElementById('tableSearch').addEventListener('input', filterTable);
        document.getElementById('archFilter').addEventListener('change', filterTable);
        document.getElementById('genFilter').addEventListener('change', filterTable);

        // Sort
        let sortDirection = {{}};
        document.querySelectorAll('#fullResultsTable th[data-sort]').forEach(th => {{
            th.addEventListener('click', () => {{
                const field = th.dataset.sort;
                sortDirection[field] = !sortDirection[field];
                const dir = sortDirection[field] ? 1 : -1;
                const sorted = [...allInstances].sort((a, b) => {{
                    if (field === 'name') return a.name.localeCompare(b.name) * dir;
                    if (field === 'arch') return a.arch.localeCompare(b.arch) * dir;
                    return (a[field] - b[field]) * dir;
                }});
                sorted.forEach((inst, idx) => inst.rank = idx + 1);
                filterTable();
            }});
        }});
    </script>
</body>
</html>
'''
    return html

def main():
    print("Loading data...")
    data = load_data()
    print(f"Found {len(data)} instances")

    print("Generating HTML report...")
    html = generate_html(data)

    with open(OUTPUT_FILE, 'w') as f:
        f.write(html)
    print(f"Report saved to {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
