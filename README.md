# EC2 Instance Benchmark Suite

EKS 클러스터에서 Karpenter를 사용하여 51개 EC2 인스턴스 타입(5~8세대)의 성능을 비교하는 벤치마크 스위트입니다.

> **상세 문서**: [BENCHMARK-GUIDE.md](./BENCHMARK-GUIDE.md) - 벤치마크 방법, 결과 형식, Docker 이미지 정보

## 테스트 환경

- **EKS 클러스터**: demo-hirehub-eks (ap-northeast-2)
- **인스턴스 크기**: xlarge (4 vCPU)
- **Karpenter NodePool**: benchmark-4vcpu-* (dedicated taints)
- **노드 격리**: podAntiAffinity로 벤치마크 Pod 격리
- **반복 횟수**: 5회 (통계적 유효성)

## Quick Start

```bash
# 1. EKS 클러스터 접근
aws eks update-kubeconfig --name demo-hirehub-eks --region ap-northeast-2

# 2. Karpenter NodePool 적용
kubectl apply -f karpenter/nodepool-4vcpu.yaml

# 3. benchmark namespace 생성
kubectl create namespace benchmark

# 4. 벤치마크 실행 (51개 병렬)
./scripts/run-benchmarks-parallel.sh coldstart
```

---

## 벤치마크 종류 및 실행 방법

### 1. Spring Boot Benchmark (Coldstart + wrk)

SpringBoot 벤치마크는 **Coldstart**(JVM 시작)와 **wrk**(HTTP 처리량) 두 가지로 구성됩니다.
두 테스트는 독립적이므로 **병렬 실행 가능**합니다.

#### 결과 저장 구조
```
results/springboot/<instance>/
├── coldstart1.log ~ coldstart5.log   # JVM Cold Start 5회
└── wrk1.log ~ wrk5.log               # HTTP 벤치마크 5회
```

#### 1-1. Coldstart (완전 병렬 - 255개 동시 실행)

51개 인스턴스 × 5회 = **255개 Job을 동시에 실행** 가능

```bash
# 인스턴스 목록
INTEL="c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge c6i.xlarge c6id.xlarge c6in.xlarge c7i.xlarge c7i-flex.xlarge c8i.xlarge c8i-flex.xlarge m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge m6i.xlarge m6id.xlarge m6idn.xlarge m6in.xlarge m7i.xlarge m7i-flex.xlarge m8i.xlarge r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge r6i.xlarge r6id.xlarge r7i.xlarge r8i.xlarge r8i-flex.xlarge"
GRAVITON="c6g.xlarge c6gd.xlarge c6gn.xlarge c7g.xlarge c7gd.xlarge c8g.xlarge m6g.xlarge m6gd.xlarge m7g.xlarge m7gd.xlarge m8g.xlarge r6g.xlarge r6gd.xlarge r7g.xlarge r7gd.xlarge r8g.xlarge"

# 모든 인스턴스 × 5회 동시 배포
for RUN in 1 2 3 4 5; do
    for instance in $INTEL; do
        safe_name=$(echo "$instance" | tr '.' '-')
        cat benchmarks/springboot/springboot-coldstart.yaml | \
            sed "s/INSTANCE_SAFE/${safe_name}/g" | \
            sed "s/INSTANCE_TYPE/${instance}/g" | \
            sed "s/RUN_NUMBER/${RUN}/g" | \
            sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: amd64|g" | \
            kubectl apply -f -
    done
    for instance in $GRAVITON; do
        safe_name=$(echo "$instance" | tr '.' '-')
        cat benchmarks/springboot/springboot-coldstart.yaml | \
            sed "s/INSTANCE_SAFE/${safe_name}/g" | \
            sed "s/INSTANCE_TYPE/${instance}/g" | \
            sed "s/RUN_NUMBER/${RUN}/g" | \
            sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: arm64|g" | \
            kubectl apply -f -
    done
done
```

#### 1-2. wrk HTTP 벤치마크 (인스턴스 간 병렬, 인스턴스 내 순차)

- 각 인스턴스별로 run1 → run2 → ... → run5 **순차 실행**
- 서로 다른 인스턴스는 **동시 실행**

```bash
# Step 1: SpringBoot 서버 51개 배포
for instance in $INTEL; do
    safe_name=$(echo "$instance" | tr '.' '-')
    cat benchmarks/springboot/springboot-server.yaml | \
        sed "s/INSTANCE_SAFE/${safe_name}/g" | \
        sed "s/INSTANCE_TYPE/${instance}/g" | \
        sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: amd64|g" | \
        kubectl apply -f -
done
# (Graviton도 동일하게 arm64로 배포)

# Step 2: 인스턴스별 5회 순차 실행 (백그라운드로 병렬화)
for instance in $INTEL $GRAVITON; do
    (
        safe_name=$(echo "$instance" | tr '.' '-')
        arch=$([[ "$instance" =~ g\. ]] && echo "arm64" || echo "amd64")
        mkdir -p "results/springboot/$instance"

        for RUN in 1 2 3 4 5; do
            job_name="springboot-wrk-${safe_name}-run${RUN}"
            cat benchmarks/springboot/springboot-benchmark.yaml | \
                sed "s/INSTANCE_SAFE/${safe_name}/g" | \
                sed "s/INSTANCE_TYPE/${instance}/g" | \
                sed "s/RUN_NUMBER/${RUN}/g" | \
                sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g" | \
                kubectl apply -f -

            kubectl wait --for=condition=complete job/$job_name -n benchmark --timeout=300s
            pod=$(kubectl get pods -n benchmark -l job-name=$job_name -o name | head -1)
            kubectl logs -n benchmark $pod > "results/springboot/$instance/wrk${RUN}.log"
            kubectl delete job $job_name -n benchmark
        done
    ) &
done
wait

# Step 3: 서버 정리
kubectl delete deployment -n benchmark -l app=springboot-server
```

#### 병렬화 요약

| 테스트 | 병렬화 수준 | 동시 실행 수 |
|--------|-------------|--------------|
| Coldstart | 완전 병렬 | 255개 (51 × 5) |
| wrk | 인스턴스 간 병렬 | 51개 (각 인스턴스 내 5회 순차) |

### 2. Redis Benchmark

memtier_benchmark(Intel/AMD) 또는 redis-benchmark(Graviton)를 사용한 Redis 성능 측정.

**서버 배포 + 벤치마크 실행**
```bash
# 1. Redis 서버 51개 배포
./scripts/deploy-redis-servers.sh

# 2. 벤치마크 5회 실행
for RUN in 1 2 3 4 5; do
  ./scripts/run-redis-5runs.sh $RUN
  sleep 120
done

# 3. 로그 수집 및 서버 정리
./scripts/collect-redis-and-cleanup.sh
```

**결과 파싱**
```bash
./scripts/parse-redis-results.sh
# 출력: results/redis-summary.csv
```

### 3. Nginx Benchmark (wrk)

HTTP 요청 처리 성능을 wrk로 측정 (2t/100c, 4t/200c, 8t/400c 설정).

**실행**
```bash
# 1. Nginx 서버 배포
./scripts/deploy-nginx-servers.sh

# 2. wrk 벤치마크 실행
./scripts/run-nginx-benchmark-v2.sh

# 3. 결과 수집
./scripts/parse-results.sh nginx
```

### 4. Elasticsearch Cold Start

ES 8.11.0 시작 시간 측정 (HTTP Ready, Cluster Ready, Index 성능).

**실행**
```bash
# 51개 Job 배포 (5회 반복)
for RUN in 1 2 3 4 5; do
  ./scripts/run-elasticsearch-5runs.sh $RUN
  sleep 300  # ES 시작에 시간 소요
done

# 로그 수집
./scripts/collect-es-logs.sh
```

### 5. Sysbench CPU

Prime calculation 기반 CPU 성능 측정 (Multi-thread 4t/60s, Single-thread 1t/30s).

```bash
INSTANCE="c8i.xlarge"
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    benchmarks/system/sysbench-cpu.yaml | kubectl apply -f -
```

---

## 핵심 스크립트

| 스크립트 | 용도 |
|----------|------|
| `run-benchmarks-parallel.sh` | 51개 인스턴스 병렬 벤치마크 실행 |
| `run-redis-5runs.sh [RUN]` | Redis 벤치마크 단일 run 실행 |
| `run-springboot-coldstart.sh` | Spring Boot 서버 배포 및 cold start 측정 |
| `run-elasticsearch-5runs.sh [RUN]` | ES coldstart 단일 run 실행 |
| `parse-results.sh [type]` | 로그 파싱 및 CSV 생성 |
| `cleanup.sh` | 모든 벤치마크 리소스 정리 |
| `monitor.sh` | 실시간 Job/Pod 상태 모니터링 |

---

## 51개 인스턴스 병렬 실행 패턴

모든 벤치마크는 동일한 패턴으로 51개 인스턴스를 병렬 실행합니다:

```bash
#!/bin/bash
# 병렬 실행 패턴

INTEL="c8i.xlarge c8i-flex.xlarge c7i.xlarge ..."  # 35개
GRAVITON="c8g.xlarge c7g.xlarge c6g.xlarge ..."    # 16개

# Job 배포
for INSTANCE in $INTEL; do
  SAFE=$(echo $INSTANCE | tr '.' '-')
  sed -e "s/INSTANCE_SAFE/${SAFE}/g" \
      -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
      -e "s/ARCH/amd64/g" \
      template.yaml | kubectl apply -f -
done

for INSTANCE in $GRAVITON; do
  SAFE=$(echo $INSTANCE | tr '.' '-')
  sed -e "s/INSTANCE_SAFE/${SAFE}/g" \
      -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
      -e "s/ARCH/arm64/g" \
      template.yaml | kubectl apply -f -
done

# 완료 대기 및 로그 수집
while true; do
  COMPLETED=$(kubectl get jobs -n benchmark -l benchmark=XXX | grep "1/1" | wc -l)
  if [ "$COMPLETED" -ge 51 ]; then break; fi
  sleep 30
done
```

---

## 노드 격리 (Anti-Affinity)

모든 벤치마크 Pod에 다음 설정이 필수 적용되어 있습니다:

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

이를 통해 **한 노드에 하나의 벤치마크 Pod만** 실행되어 정확한 성능 측정을 보장합니다.

---

## 테스트 대상 인스턴스 타입 (51개)

### Intel/AMD (x86_64) - 35개
| Generation | Compute (c) | General (m) | Memory-Opt (r) |
|------------|-------------|-------------|----------------|
| 8th | c8i, c8i-flex | m8i | r8i, r8i-flex |
| 7th | c7i, c7i-flex | m7i, m7i-flex | r7i |
| 6th | c6i, c6id, c6in | m6i, m6id, m6in, m6idn | r6i, r6id |
| 5th | c5, c5a, c5d, c5n | m5, m5a, m5ad, m5d, m5zn | r5, r5a, r5ad, r5b, r5d, r5dn, r5n |

### Graviton (arm64) - 16개
| Generation | Compute (c) | General (m) | Memory-Opt (r) |
|------------|-------------|-------------|----------------|
| Graviton 4 (8g) | c8g | m8g | r8g |
| Graviton 3 (7g) | c7g, c7gd | m7g, m7gd | r7g, r7gd |
| Graviton 2 (6g) | c6g, c6gd, c6gn | m6g, m6gd | r6g, r6gd |

---

## 결과 파싱 및 리포트 생성

### CSV 생성
```bash
# 전체 벤치마크 결과 파싱
./scripts/parse-results.sh all

# 개별 파싱
./scripts/parse-results.sh redis
./scripts/parse-results.sh nginx
./scripts/parse-results.sh elasticsearch
```

### 출력 파일
- `results/redis-summary.csv` - SET/GET ops/sec, latency p50
- `results/nginx-summary.csv` - Requests/sec by thread count
- `results/elasticsearch-summary.csv` - Cold start time, index time
- `results/springboot/startup-times-full.csv` - JVM startup times

---

## 디렉토리 구조

```
/home/ec2-user/benchmark/
├── README.md                    # 이 파일
├── CLAUDE.md                    # Claude Code 작업 가이드
├── BENCHMARK-GUIDE.md           # 상세 벤치마크 가이드
├── config/
│   └── instances-4vcpu.txt      # xlarge 인스턴스 목록 (51개)
├── benchmarks/
│   ├── system/                  # sysbench, geekbench, passmark
│   ├── redis/                   # redis-server, benchmark
│   ├── nginx/                   # nginx-server, wrk
│   ├── springboot/              # springboot-server, coldstart
│   └── elasticsearch/           # elasticsearch-coldstart
├── scripts/
│   ├── run-benchmarks-parallel.sh   # 병렬 실행
│   ├── run-redis-5runs.sh           # Redis 5회 실행
│   ├── run-springboot-coldstart.sh  # Spring Boot cold start
│   ├── run-elasticsearch-5runs.sh   # ES 5회 실행
│   ├── parse-results.sh             # 결과 파싱
│   ├── cleanup.sh                   # 리소스 정리
│   └── monitor.sh                   # 상태 모니터링
├── karpenter/
│   └── nodepool-4vcpu.yaml      # Karpenter NodePool
├── results/                     # 결과 저장
│   ├── redis/
│   ├── nginx/
│   ├── springboot/
│   └── elasticsearch/
└── reports/                     # HTML 리포트
```

---

## 메트릭 정의

| 메트릭 | 단위 | 방향 |
|--------|------|------|
| Multi-thread events/sec | events/sec | higher is better |
| Single-thread events/sec | events/sec | higher is better |
| Redis SET/GET ops/sec | ops/sec | higher is better |
| Nginx Requests/sec | req/sec | higher is better |
| Latency p50/p99 | ms | lower is better |
| Cold Start | ms | lower is better |

---

## 주의사항

1. **Docker Hub Rate Limit**: ECR Public 이미지 사용
2. **ARM 이미지 호환성**: memtier_benchmark는 x86 only → Graviton에서 redis-benchmark 사용
3. **노드 스케일링**: Karpenter가 인스턴스 프로비저닝에 1-2분 소요
4. **로그 수집**: Job TTL (10분) 이전에 로그 수집 필요
5. **JVM Heap**: Spring Boot coldstart에서 `-XX:MaxRAMPercentage=60.0` 사용

---

## 배포 전 체크리스트

```bash
# 1. Anti-affinity 설정 확인
for f in benchmarks/*/*.yaml; do
  echo "=== $(basename $f) ==="
  grep -A8 "podAntiAffinity:" "$f" | head -10 || echo "NO ANTI-AFFINITY!"
done

# 2. 인스턴스 목록 51개 확인
grep -v "^#" config/instances-4vcpu.txt | grep -v "^$" | wc -l

# 3. NodePool CPU Limit 확인
grep -A1 "limits:" karpenter/nodepool-4vcpu.yaml | grep cpu

# 4. ECR 이미지 확인 (Docker Hub 직접 사용 없음)
grep -rn "image:" benchmarks/ | grep -v "ecr\|public.ecr" | grep -v "#"
```

---

## 리소스 정리

```bash
# 전체 정리 (namespace 삭제)
./scripts/cleanup.sh

# 특정 벤치마크만 정리
kubectl delete jobs -n benchmark -l benchmark=redis-benchmark
kubectl delete deployment -n benchmark -l app=redis-server

# Karpenter 노드 정리 (자동)
# TTL이 지나면 Karpenter가 자동으로 노드 제거
```

---

## 문제 해결

### Job이 Pending 상태로 유지됨
```bash
# 노드 상태 확인
kubectl get nodes -l karpenter.sh/nodepool=benchmark-4vcpu-intel

# NodePool limit 확인
kubectl get nodepool benchmark-4vcpu-intel -o yaml | grep -A5 limits
```

### 로그 수집 실패
```bash
# Job 상태 확인
kubectl get jobs -n benchmark -l benchmark=springboot-coldstart

# Pod 로그 직접 확인
kubectl logs -n benchmark <pod-name>
```

### Graviton 인스턴스에서 이미지 풀 실패
```bash
# multi-arch 이미지 확인
docker manifest inspect <image:tag> | grep architecture
```
