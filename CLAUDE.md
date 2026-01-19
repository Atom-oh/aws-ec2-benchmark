# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EKS EC2 Node Benchmark - 다양한 EC2 인스턴스 타입(5세대~8세대, 51개)의 성능을 비교하는 Kubernetes 기반 벤치마크 프로젝트. Karpenter를 사용하여 노드를 동적 프로비저닝.

## 현재 상태 (2026-01-19)

### 변경사항
- **인스턴스 크기 **: 4 vCPU (xlarge) 
- **Anti-affinity 적용**: 모든 템플릿에 `podAntiAffinity` 추가 - 노드 격리 보장
- **JVM Heap 60%**: Elasticsearch, SpringBoot에서 가용 메모리의 60%를 힙으로 설정


### 벤치마크 상태 (60% heap, 5회 반복)
| 벤치마크 | 완료 | 반복 | 템플릿 | 결과 위치 |
|----------|------|------|--------|-----------|
| sysbench CPU | 51/51 | 1회 | `benchmarks/system/sysbench-cpu.yaml` | `results/sysbench/` |
| Redis | 51/51 | 5회 | `benchmarks/redis/redis-*.yaml` | `results/redis/<instance>/run<N>.log` |
| Nginx (wrk) | 51/51 | 5회 | `benchmarks/nginx/nginx-*.yaml` | `results/nginx/<instance>/run<N>.log` |
| ES Coldstart | 진행중 | 5회 | `benchmarks/elasticsearch/elasticsearch-coldstart.yaml` | `results/elasticsearch/<instance>/run<N>.log` |
| SpringBoot Coldstart | 진행중 | 5회 | `benchmarks/springboot/springboot-coldstart.yaml` | `results/springboot/<instance>/cold_start<N>.log` |
| SpringBoot wrk | 진행중 | 5회 | `benchmarks/springboot/springboot-benchmark.yaml` | `results/springboot/<instance>/wrk<N>.log` |
| iperf3 Network | 51/51 | 1회 | `benchmarks/system/iperf3-network.yaml` | `results/iperf3/<instance>.log` |

### 알려진 결과 문제
- **Nginx r8i.xlarge**: run3, run5에서 성능 저하 (80k vs 250k req/sec). 재테스트 필요.
  - 원인: 특정 노드에서 간헐적 성능 저하 (noisy neighbor 또는 CPU throttling 추정)

## 핵심 설계 원칙

### JVM Heap 60% 설정
인스턴스 타입별 메모리 차이(C=8GB, M=16GB, R=32GB)를 반영하기 위해 가용 메모리의 60%를 JVM 힙으로 설정:

**Elasticsearch:**
```bash
TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
HEAP_MB=$((TOTAL_MEM_KB * 60 / 100 / 1024))
ES_JAVA_OPTS="-Xms${HEAP_MB}m -Xmx${HEAP_MB}m"
```

**SpringBoot:**
```yaml
env:
  - name: JAVA_OPTS
    value: "-XX:InitialRAMPercentage=50.0 -XX:MaxRAMPercentage=60.0 -XX:+UseG1GC"
```

### 노드 격리 (Anti-Affinity)
모든 벤치마크 Pod는 `benchmark` 레이블이 있는 다른 Pod와 같은 노드에 스케줄링되지 않음:
```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
            - key: benchmark
              operator: Exists
        topologyKey: "kubernetes.io/hostname"
```

### SpringBoot wrk Zone Affinity
SpringBoot wrk 벤치마크는 서버와 같은 Zone에 배치 + 다른 벤치마크와 노드 분리:
```yaml
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app: springboot-server
            instance-type: "${INSTANCE_TYPE}"
        topologyKey: "topology.kubernetes.io/zone"
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
            - key: benchmark
              operator: Exists
        topologyKey: "kubernetes.io/hostname"
```
- **podAffinity**: wrk 클라이언트가 SpringBoot 서버와 같은 Zone에 스케줄링
- **podAntiAffinity**: 다른 벤치마크 Pod와 같은 노드에 스케줄링 방지

## 벤치마크 실행 방법

### 51개 인스턴스 병렬 실행
모든 인스턴스를 동시에 실행하여 벤치마크 시간 단축:

```bash
# 51개 전체 병렬 실행 예시
for instance in $INTEL_INSTANCES; do
    safe_name=$(echo "$instance" | tr '.' '-')
    sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
        -e "s/INSTANCE_TYPE/${instance}/g" \
        -e "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: amd64|g" \
        benchmarks/elasticsearch/elasticsearch-coldstart.yaml | kubectl apply -f -
done
```

### 1분 주기 모니터링
벤치마크 실행 중 문제 감지를 위해 1분마다 상태 확인:

```bash
while true; do
    echo "[$(date '+%H:%M:%S')] Pod Status:"
    kubectl get pods -n benchmark --no-headers | grep -E "Running|Pending|Error" | head -10

    echo "[$(date '+%H:%M:%S')] Job Status:"
    kubectl get jobs -n benchmark --no-headers | grep -v "1/1" | head -10

    sleep 60
done
```

### 결과 저장 구조
로그는 인스턴스별 폴더에 저장:
```
results/elasticsearch/<instance>/run1.log ~ run5.log
results/springboot/<instance>/cold_start1.log ~ cold_start5.log
results/springboot/<instance>/wrk1.log ~ wrk5.log
```

### 단일 인스턴스 Job 생성
```bash
# Intel (amd64)
INSTANCE="c8i.xlarge"
SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    benchmarks/system/sysbench-cpu.yaml | kubectl apply -f -

# Graviton (arm64)
INSTANCE="c8g.xlarge"
SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    benchmarks/system/sysbench-cpu.yaml | kubectl apply -f -

# Elasticsearch/Spring Boot (ARCH 변수 필요)
INSTANCE="c8i.xlarge"
SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
    -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
    -e "s/ARCH/amd64/g" \
    benchmarks/elasticsearch/elasticsearch-coldstart.yaml | kubectl apply -f -
```

### 로그 수집
```bash
# 단일 Pod
POD=$(kubectl get pods -n benchmark -l job-name=sysbench-cpu-c8i-xlarge --no-headers -o custom-columns=":metadata.name" | head -1)
kubectl logs -n benchmark $POD > results/sysbench/c8i.xlarge.log
```

## Key Files

```
/home/ec2-user/benchmark/
├── CLAUDE.md                           # 이 파일
├── config/
│   └── instances-4vcpu.txt             # xlarge 인스턴스 목록 (51개)
├── benchmarks/
│   ├── system/
│   │   ├── sysbench-cpu.yaml           # CPU 벤치마크
│   │   ├── sysbench-memory.yaml        # 메모리 벤치마크
│   │   ├── stress-ng.yaml              # 종합 벤치마크
│   │   ├── fio-disk.yaml               # 디스크 I/O
│   │   ├── iperf3-network.yaml         # 네트워크
│   │   ├── geekbench.yaml              # Geekbench 6
│   │   └── passmark.yaml               # Passmark
│   ├── redis/
│   │   ├── redis-server.yaml           # Redis 서버
│   │   ├── redis-benchmark.yaml        # redis-benchmark (Graviton)
│   │   └── memtier-benchmark.yaml      # memtier (Intel/AMD)
│   ├── nginx/
│   │   ├── nginx-server.yaml           # Nginx 서버
│   │   ├── nginx-benchmark.yaml        # wrk
│   │   └── wrk2-benchmark.yaml         # wrk2 (CO 보정)
│   ├── springboot/
│   │   ├── springboot-server.yaml      # Spring Boot 서버 (Deployment)
│   │   ├── springboot-benchmark.yaml   # wrk HTTP throughput 벤치마크
│   │   └── springboot-coldstart.yaml   # 앱 전체 Cold Start 시간 측정
│   └── elasticsearch/
│       └── elasticsearch-coldstart.yaml # ES Cold Start
├── karpenter/
│   └── nodepool-4vcpu.yaml             # Karpenter NodePool (xlarge)
└── results/                            # 결과 저장 (새로 수집)
```

## 인스턴스 목록 (xlarge, 4 vCPU)

### 서울 리전 (ap-northeast-2) 사용 가능 51개
```
Intel 5th: c5, c5a, c5d, c5n, m5, m5a, m5ad, m5d, m5zn, r5, r5a, r5ad, r5b, r5d, r5dn, r5n
Intel 6th: c6i, c6id, c6in, m6i, m6id, m6idn, m6in, r6i, r6id
Intel 7th: c7i, c7i-flex, m7i, m7i-flex, r7i
Intel 8th: c8i, c8i-flex, m8i, r8i, r8i-flex
Graviton2: c6g, c6gd, c6gn, m6g, m6gd, r6g, r6gd
Graviton3: c7g, c7gd, m7g, m7gd, r7g, r7gd
Graviton4: c8g, m8g, r8g
```

## 메트릭 정의

| 메트릭 | 단위 | 방향 |
|--------|------|------|
| Multi-thread events/sec | events/sec | ⬆️ higher is better |
| Single-thread events/sec | events/sec | ⬆️ higher is better |
| Redis SET ops/sec | ops/sec | ⬆️ higher is better |
| Nginx Requests/sec | req/sec | ⬆️ higher is better |
| Latency | ms | ⬇️ lower is better |
| Cold Start | ms | ⬇️ lower is better |

## 배포 전 체크리스트

### 1. Anti-affinity 설정 확인
```bash
# 모든 템플릿에 podAntiAffinity가 있고 operator: Exists인지 확인
for f in benchmarks/*/*.yaml; do
  echo "=== $(basename $f) ==="
  grep -A8 "podAntiAffinity:" "$f" | head -10 || echo "NO ANTI-AFFINITY!"
done
```

### 2. 인스턴스 목록 51개 확인
```bash
# config 파일 확인
grep -v "^#" config/instances-4vcpu.txt | grep -v "^$" | wc -l
# 예상: 51
```

### 3. NodePool 인스턴스 51개 확인
```bash
# NodePool YAML 확인
grep -E "^\s+- [cmr][5-8]" karpenter/nodepool-4vcpu.yaml | wc -l
# 예상: 51
```

### 4. Docker Hub → ECR 변경 확인
```bash
# Docker Hub 직접 사용하는 이미지가 없는지 확인
grep -rn "image:" benchmarks/ | grep -v "ecr\|public.ecr" | grep -v "#"
# 예상: 출력 없음 (모두 ECR 사용)
```

### 5. Multi-arch 이미지 확인 (arm64 & amd64)
```bash
# 이전 결과에서 Graviton 실행 성공 여부로 확인
ls results-backup-2xlarge/all/ | grep -E "c[678]g|m[678]g|r[678]g"
# Graviton 로그가 있으면 multi-arch 지원 확인됨
```

### 6. NodePool CPU Limit 확인
```bash
# 병렬 실행을 위한 충분한 limit 확인
grep -A1 "limits:" karpenter/nodepool-4vcpu.yaml | grep cpu
# 예상: cpu: 160 (40개 노드 동시 실행)
```

## 중요: 결과 수집 타이밍

### Pod 로그 수집 시점 (매우 중요!)
**Job 완료 후 즉시 로그를 수집해야 함.** `ttlSecondsAfterFinished` 설정에 따라 완료된 Pod가 자동 삭제되므로 로그 손실 위험이 있음.

```yaml
# 템플릿의 TTL 설정 (현재 2시간)
spec:
  ttlSecondsAfterFinished: 7200  # 2시간 후 자동 삭제
```

### 권장 수집 방법
```bash
# Job 완료 대기 및 즉시 수집 (30초 주기 모니터링)
while true; do
    succeeded=$(kubectl get jobs -n benchmark -l benchmark=passmark --no-headers | grep "1/1" | wc -l)
    total=$(kubectl get jobs -n benchmark -l benchmark=passmark --no-headers | wc -l)

    echo "[$(date '+%H:%M:%S')] Progress: $succeeded/$total completed"

    if [ "$succeeded" -eq "$total" ] && [ "$total" -gt 0 ]; then
        echo "All jobs completed! Collecting logs..."
        # 즉시 로그 수집 실행
        break
    fi
    sleep 30
done

# 로그 수집
for instance in $ALL_INSTANCES; do
    safe_name=$(echo "$instance" | tr '.' '-')
    job_name="passmark-${safe_name}"
    pod_name=$(kubectl get pods -n benchmark -l job-name=$job_name --no-headers -o custom-columns=":metadata.name" | head -1)

    if [ -n "$pod_name" ]; then
        mkdir -p "results/passmark/$instance"
        kubectl logs -n benchmark "$pod_name" > "results/passmark/$instance/run1.log"
    fi
done
```

### 주의사항
- **절대 Job 완료 후 방치하지 말 것** - TTL 만료 시 Pod 삭제되어 로그 손실
- 긴 벤치마크(Geekbench 등)는 별도 터미널에서 모니터링 스크립트 실행 권장
- 백그라운드 에이전트로 수집 자동화 가능: `run_in_background: true`

## YAML 템플릿 Placeholder 규칙 (매우 중요!)

각 템플릿에서 사용하는 placeholder와 sed 치환 패턴:

### Placeholder 정의
| Placeholder | 설명 | 예시 값 |
|------------|------|--------|
| `INSTANCE_SAFE` | 인스턴스 타입 (. → -) | `c8i-xlarge` |
| `${INSTANCE_TYPE}` | 인스턴스 타입 원본 | `c8i.xlarge` |
| `JOB_NAME` | Job 이름 전체 | `redis-benchmark-c8i-xlarge` |
| `ARCH` | 아키텍처 | `amd64` 또는 `arm64` |

### 올바른 sed 치환 (chained pipes 사용!)
```bash
# 여러 sed를 pipe로 연결해야 안정적으로 동작
instance="c8i.xlarge"
safe_name=$(echo "$instance" | tr '.' '-')

cat template.yaml | \
    sed "s/JOB_NAME/redis-benchmark-${safe_name}/g" | \
    sed "s/INSTANCE_SAFE/${safe_name}/g" | \
    sed "s/\${INSTANCE_TYPE}/${instance}/g" | \
    kubectl apply -f -
```

### 잘못된 sed 치환 (사용 금지!)
```bash
# 이 방식은 bash 환경에 따라 변수 확장이 실패할 수 있음
sed -e "s/JOB_NAME/job-${safe_name}/g" \
    -e "s/INSTANCE_SAFE/${safe_name}/g" \
    -e "s|\${INSTANCE_TYPE}|${instance}|g" \
    template.yaml | kubectl apply -f -
```

### 템플릿별 필요한 Placeholder
| 템플릿 | JOB_NAME | INSTANCE_SAFE | ${INSTANCE_TYPE} | ARCH |
|--------|----------|---------------|------------------|------|
| redis-server.yaml | ❌ | ✅ | ✅ | ❌ |
| redis-benchmark.yaml | ✅ | ✅ | ✅ | ❌ |
| springboot-server.yaml | ❌ | ✅ | ✅ | ❌ |
| springboot-benchmark.yaml | ❌ | ✅ | ✅ | ❌ |
| elasticsearch-coldstart.yaml | ❌ | ✅ | ✅ | ✅ |

## 결과 저장 구조

### 다중 실행 벤치마크 (5회 반복)
```
results/nginx/<instance>/run1.log ~ run5.log
results/redis/<instance>/run1.log ~ run5.log
results/elasticsearch/<instance>/run1.log ~ run5.log
results/springboot/<instance>/cold_start1.log ~ cold_start5.log
results/springboot/<instance>/wrk1.log ~ wrk5.log
```

### 단일 실행 벤치마크
```
results/sysbench/<instance>.log
results/iperf3/<instance>.log
```

## 알려진 이슈

1. **memtier_benchmark**: x86 전용 → Graviton에서 redis-benchmark 사용
2. **Docker Hub Rate Limit**: ECR pull-through cache 사용
3. **Pod 로그 손실**: TTL 이전에 수집 필요 (위 섹션 참조)
4. **Geekbench --no-upload**: Pro 버전 전용 옵션, Free 버전에서는 결과가 자동 업로드됨
5. **Passmark arm64**: Graviton용 별도 바이너리 필요 (`pt_linux_arm64`)
6. **Nginx r8i 결과 이상**: run3, run5에서 성능 저하 - 재테스트 필요
7. **sed 변수 확장 문제**: 여러 -e 옵션 대신 chained pipes 사용 권장

## HTML 보고서 형식 (표준)

Redis와 Nginx 보고서를 표준으로 사용. 새 벤치마크 보고서 생성 시 이 형식을 따를 것.

### 파일 위치
```
results/<benchmark>/report-charts.html
```

### 필수 구조

#### 1. HTML 헤더
```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{벤치마크명} 벤치마크 리포트</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>/* CSS 변수 및 스타일 */</style>
</head>
```

#### 2. CSS 변수 (색상 표준)
```css
:root {
    --graviton: #10b981;  /* 초록 - Graviton/ARM */
    --intel: #3b82f6;     /* 파랑 - Intel */
    --amd: #ef4444;       /* 빨강 - AMD */
    --bg: #f8fafc;
    --card: #ffffff;
    --text: #1e293b;
    --muted: #64748b;
}
```

#### 3. 페이지 구성 (순서대로)
1. **Header**: 그라데이션 배경, 제목, 부제목, 날짜/리전 정보
2. **Summary Cards** (4-5개): 최고 성능, 최고 가성비, 핵심 인사이트
3. **목차**: 섹션 링크
4. **테스트 방법론**: 왜 이 벤치마크가 중요한지, 수집 메트릭
5. **테스트 환경**: 인프라 구성, 인스턴스 구성, 설정 상세
6. **성능 분석 차트들**: Chart.js 사용
7. **전체 결과 테이블**: 필터/정렬 기능 포함
8. **결론**: 핵심 시사점, 추천 인스턴스
9. **Footer**: 날짜, 리전 정보

#### 4. 필수 차트 유형
- **Top 20 Bar Chart** (horizontal): 주요 메트릭 순위
- **세대별 비교 Bar Chart**: Intel vs Graviton
- **패밀리별 비교**: C/M/R 패밀리
- **가격 대비 성능 Bubble Chart**: X=가격, Y=성능
- **가성비 Top 15**: 효율성 점수 순위

#### 5. 스타일 클래스
```css
.container { max-width: 1600px; }
.card { border-radius: 1rem; box-shadow: ... }
.chart-section { background: var(--card); border-radius: 1rem; }
.chart-container { height: 400px; }  /* .tall: 500px, .extra-tall: 800px */
.badge-graviton { background: #d1fae5; color: #065f46; }
.badge-intel { background: #dbeafe; color: #1e40af; }
.badge-amd { background: #fee2e2; color: #991b1b; }
.insights { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border-left: 4px solid #f59e0b; }
```

#### 6. 인사이트 박스
```html
<div class="insights">
    <h4>핵심 인사이트</h4>
    <ul>
        <li><strong>Graviton4가 최고 성능</strong> - Intel 대비 X% 빠름</li>
        <li>...</li>
    </ul>
</div>
```

#### 7. 결과 테이블 기능
- 검색 필터 (인스턴스명)
- 아키텍처 필터 (Graviton/Intel/AMD)
- 세대 필터 (5/6/7/8세대)
- 패밀리 필터 (C/M/R)
- 열 헤더 클릭 정렬

### 참고 보고서
- `results/nginx/report-charts.html` - 가장 완성도 높음
- `results/redis/report-charts.html` - Redis 특화
- `results/stress-ng/report-charts.html` - 최신 생성
