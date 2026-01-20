# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EKS EC2 Node Benchmark - 다양한 EC2 인스턴스 타입(5세대~8세대, 51개)의 성능을 비교하는 Kubernetes 기반 벤치마크 프로젝트. Karpenter를 사용하여 노드를 동적 프로비저닝.

## 현재 상태 (2026-01-20)

### 변경사항
- **인스턴스 크기 **: 4 vCPU (xlarge)
- **Anti-affinity 적용**: 모든 템플릿에 `podAntiAffinity` 추가 - 노드 격리 보장
- **JVM Heap 60%**: Elasticsearch, SpringBoot에서 가용 메모리의 60%를 힙으로 설정

### SpringBoot Docker 이미지

벤치마크 용도에 따라 2개의 이미지가 있음:

| 이미지 | ECR 경로 | 용도 | 크기 | 특징 |
|--------|----------|------|------|------|
| **springboot-simple** | `180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/benchmark/springboot-simple:latest` | wrk throughput | ~80MB | 최소한의 REST API (2개 엔드포인트) |
| **springboot-petclinic** | `180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/benchmark/springboot-petclinic:latest` | **Coldstart** | ~253MB | 실제 애플리케이션 (DB, 템플릿, 다수의 빈) |

#### springboot-simple
- Spring Boot 3.2 + Java 21 기반 최소 앱
- `spring-boot-starter-web`, `spring-boot-starter-actuator` 의존성만 포함
- Cold start 2-3초로 인스턴스 간 차이가 작음
- **wrk HTTP throughput 벤치마크에 사용**

#### springboot-petclinic (Coldstart 측정용)
- [Spring PetClinic](https://github.com/spring-projects/spring-petclinic) 프로젝트 기반
- H2 인메모리 DB, Thymeleaf 템플릿 엔진, 다수의 엔티티/서비스/컨트롤러
- Cold start 5-8초로 인스턴스 간 성능 차이가 명확
- **Coldstart 벤치마크에 사용** - 인스턴스 성능 비교에 적합

#### Dockerfile 위치
```
docker/springboot-simple/Dockerfile      # minimal REST API
docker/springboot-petclinic/Dockerfile   # full PetClinic app
```

#### Multi-arch 지원
두 이미지 모두 `amd64` (Intel/AMD) 및 `arm64` (Graviton) 아키텍처 지원


### 벤치마크 상태 (60% heap, 5회 반복)
| 벤치마크 | 완료 | 반복 | 템플릿 | 결과 위치 |
|----------|------|------|--------|-----------|
| sysbench CPU | 51/51 | 5회 | `benchmarks/system/sysbench-cpu.yaml` | `results/sysbench-cpu/<instance>/` |
| sysbench Memory | 51/51 | 5회 | `benchmarks/system/sysbench-memory.yaml` | `results/sysbench-memory/<instance>/` |
| Redis | 51/51 | 5회 | `benchmarks/redis/redis-*.yaml` | `results/redis/<instance>/run<N>.log` |
| Nginx (wrk) | 51/51 | 5회 | `benchmarks/nginx/nginx-*.yaml` | `results/nginx/<instance>/run<N>.log` |
| ES Coldstart | 51/51 | 5회 | `benchmarks/elasticsearch/elasticsearch-coldstart.yaml` | `results/elasticsearch/<instance>/run<N>.log` |
| SpringBoot Coldstart | 진행중 | 5회 | `benchmarks/springboot/springboot-coldstart.yaml` | `results/springboot/<instance>/coldstart<N>.log` |
| SpringBoot wrk | 재측정 | 5회 | `benchmarks/springboot/springboot-benchmark.yaml` | `results/springboot/<instance>/wrk<N>.log` |
| iperf3 Network | 51/51 | 1회 | `benchmarks/system/iperf3-network.yaml` | `results/iperf3/<instance>.log` |

### 알려진 결과 문제
- **Nginx r8i.xlarge**: run3, run5에서 성능 저하 (80k vs 250k req/sec). 재테스트 필요.
  - 원인: 특정 노드에서 간헐적 성능 저하 (noisy neighbor 또는 CPU throttling 추정)

---

## SpringBoot 벤치마크 실행 가이드 (2026-01-20)

SpringBoot 벤치마크는 **Coldstart**와 **wrk** 두 가지 테스트로 구성됩니다.
두 테스트는 **독립적**이므로 병렬 실행 가능합니다.

### 결과 저장 구조
```
results/springboot/
├── c7i-flex.xlarge/
│   ├── coldstart1.log ~ coldstart5.log   # Cold Start 5회
│   └── wrk1.log ~ wrk5.log               # wrk 벤치마크 5회
├── c8g.xlarge/
│   ├── coldstart1.log ~ coldstart5.log
│   └── wrk1.log ~ wrk5.log
└── ... (51개 인스턴스)
```

### 1. Coldstart 벤치마크 (병렬 실행 + 실시간 로그 수집)

**특징**: 51개 인스턴스 × 5회 = 255개 Job을 **동시에** 실행

**⚠️ 중요: TTL 문제**
- `ttlSecondsAfterFinished: 1800` (30분)으로 설정됨
- 255개 Job을 동시 배포하면 먼저 완료된 Job은 TTL 만료로 삭제될 수 있음
- **해결책**: Job 완료 즉시 로그 수집 (배포와 수집을 동시 진행)

**권장 실행 방법 (스크립트 사용)**:
```bash
./scripts/generate-springboot-benchmark.sh coldstart
```

**수동 실행 시 (배포 + 실시간 수집 병렬)**:
```bash
# 터미널 1: Job 배포
INTEL="c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge c6i.xlarge c6id.xlarge c6in.xlarge c7i.xlarge c7i-flex.xlarge c8i.xlarge c8i-flex.xlarge m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge m6i.xlarge m6id.xlarge m6idn.xlarge m6in.xlarge m7i.xlarge m7i-flex.xlarge m8i.xlarge r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge r6i.xlarge r6id.xlarge r7i.xlarge r8i.xlarge r8i-flex.xlarge"
GRAVITON="c6g.xlarge c6gd.xlarge c6gn.xlarge c7g.xlarge c7gd.xlarge c8g.xlarge m6g.xlarge m6gd.xlarge m7g.xlarge m7gd.xlarge m8g.xlarge r6g.xlarge r6gd.xlarge r7g.xlarge r7gd.xlarge r8g.xlarge"

for RUN in 1 2 3 4 5; do
    for instance in $INTEL; do
        safe_name=$(echo "$instance" | tr '.' '-')
        cat benchmarks/springboot/springboot-coldstart.yaml | \
            sed "s/springboot-coldstart-INSTANCE_SAFE/springboot-coldstart-${safe_name}-run${RUN}/g" | \
            sed "s/INSTANCE_SAFE/${safe_name}/g" | \
            sed "s/INSTANCE_TYPE/${instance}/g" | \
            sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: amd64|g" | \
            kubectl apply -f -
    done
    for instance in $GRAVITON; do
        safe_name=$(echo "$instance" | tr '.' '-')
        cat benchmarks/springboot/springboot-coldstart.yaml | \
            sed "s/springboot-coldstart-INSTANCE_SAFE/springboot-coldstart-${safe_name}-run${RUN}/g" | \
            sed "s/INSTANCE_SAFE/${safe_name}/g" | \
            sed "s/INSTANCE_TYPE/${instance}/g" | \
            sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: arm64|g" | \
            kubectl apply -f -
    done
done

# 터미널 2: 실시간 로그 수집 (완료된 Job 즉시 수집)
while true; do
    for instance in $INTEL $GRAVITON; do
        safe_name=$(echo "$instance" | tr '.' '-')
        mkdir -p "results/springboot/$instance"
        for RUN in 1 2 3 4 5; do
            log_file="results/springboot/$instance/coldstart${RUN}.log"
            [ -s "$log_file" ] && continue  # 이미 수집됨

            job_name="springboot-coldstart-${safe_name}-run${RUN}"
            # Job이 완료되었는지 확인
            status=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.succeeded}' 2>/dev/null)
            if [ "$status" = "1" ]; then
                pod=$(kubectl get pods -n benchmark -l job-name=$job_name --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
                if [ -n "$pod" ]; then
                    kubectl logs -n benchmark "$pod" > "$log_file" 2>/dev/null
                    echo "[$(date '+%H:%M:%S')] Collected: $instance run$RUN"
                fi
            fi
        done
    done

    # 수집 완료 확인
    collected=$(find results/springboot -name "coldstart*.log" -size +0 | wc -l)
    echo "[$(date '+%H:%M:%S')] Progress: $collected/255 logs collected"
    [ "$collected" -ge 255 ] && break
    sleep 30
done
```

### 2. wrk 벤치마크 (인스턴스별 순차, 인스턴스 간 병렬)

**특징**:
- 각 인스턴스 내에서는 run1 → run2 → run3 → run4 → run5 **순차 실행**
- 서로 다른 인스턴스는 **동시 실행** 가능

**실행 순서**:
1. SpringBoot 서버 51개 배포 (Deployment)
2. 각 인스턴스별로 wrk 벤치마크 5회 순차 실행
3. 로그 수집 후 서버 정리

**Step 1: 서버 배포**
```bash
# Intel 서버 배포
for instance in $INTEL; do
    safe_name=$(echo "$instance" | tr '.' '-')
    cat benchmarks/springboot/springboot-server.yaml | \
        sed "s/INSTANCE_SAFE/${safe_name}/g" | \
        sed "s/INSTANCE_TYPE/${instance}/g" | \
        sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: amd64|g" | \
        kubectl apply -f -
done

# Graviton 서버 배포
for instance in $GRAVITON; do
    safe_name=$(echo "$instance" | tr '.' '-')
    cat benchmarks/springboot/springboot-server.yaml | \
        sed "s/INSTANCE_SAFE/${safe_name}/g" | \
        sed "s/INSTANCE_TYPE/${instance}/g" | \
        sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: arm64|g" | \
        kubectl apply -f -
done

# 서버 Ready 대기
kubectl wait --for=condition=available deployment -l app=springboot-server -n benchmark --timeout=600s
```

**Step 2: wrk 벤치마크 실행 (인스턴스별 5회 순차)**
```bash
# 각 인스턴스를 백그라운드로 실행하여 병렬화
for instance in $INTEL $GRAVITON; do
    (
        safe_name=$(echo "$instance" | tr '.' '-')
        arch=$([[ "$instance" =~ g\. ]] && echo "arm64" || echo "amd64")
        mkdir -p "results/springboot/$instance"

        for RUN in 1 2 3 4 5; do
            job_name="springboot-wrk-${safe_name}-run${RUN}"

            # wrk Job 배포
            cat benchmarks/springboot/springboot-benchmark.yaml | \
                sed "s/INSTANCE_SAFE/${safe_name}/g" | \
                sed "s/INSTANCE_TYPE/${instance}/g" | \
                sed "s/RUN_NUMBER/${RUN}/g" | \
                sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g" | \
                kubectl apply -f -

            # 완료 대기
            kubectl wait --for=condition=complete job/$job_name -n benchmark --timeout=300s

            # 로그 수집
            pod=$(kubectl get pods -n benchmark -l job-name=$job_name --no-headers -o custom-columns=":metadata.name" | head -1)
            kubectl logs -n benchmark "$pod" > "results/springboot/$instance/wrk${RUN}.log"

            # Job 정리 (다음 run을 위해)
            kubectl delete job $job_name -n benchmark
        done

        echo "[$instance] 완료"
    ) &
done

# 모든 백그라운드 프로세스 대기
wait
echo "모든 wrk 벤치마크 완료"
```

**Step 3: 서버 정리**
```bash
kubectl delete deployment -n benchmark -l app=springboot-server
kubectl delete service -n benchmark -l app=springboot-server
```

### 3. 병렬 실행 전략 요약

| 테스트 | 병렬화 수준 | 동시 실행 수 |
|--------|-------------|--------------|
| Coldstart | 완전 병렬 | 255개 (51 × 5) |
| wrk | 인스턴스 간 병렬 | 51개 (각 인스턴스 내 5회 순차) |

### 4. 모니터링
```bash
# Job 진행 상황
watch -n 10 'echo "=== Coldstart ==="; kubectl get jobs -n benchmark -l benchmark=springboot-coldstart --no-headers | grep -c "1/1"; echo "=== wrk ==="; kubectl get jobs -n benchmark -l benchmark=springboot-wrk --no-headers | grep -c "1/1"'

# Pod 상태
kubectl get pods -n benchmark -l benchmark --sort-by=.status.startTime | tail -20
```

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

## 벤치마크 상세 설명

### System 벤치마크 (CPU/Memory)

#### sysbench CPU
- **목적**: CPU 연산 성능 측정 (정수/부동소수점)
- **템플릿**: `benchmarks/system/sysbench-cpu.yaml`
- **메트릭**: events/sec (높을수록 좋음)
- **테스트 종류**:
  - Multi-thread (4 threads): 인스턴스 전체 CPU 성능
  - Single-thread: 단일 코어 성능
- **이미지**: `severalnines/sysbench:latest` (ECR pull-through)
- **특징**: 가장 기본적인 CPU 벤치마크, 인스턴스 간 비교에 적합

#### sysbench Memory
- **목적**: 메모리 대역폭/지연시간 측정
- **템플릿**: `benchmarks/system/sysbench-memory.yaml`
- **메트릭**: MiB/sec, operations/sec
- **이미지**: `severalnines/sysbench:latest`

#### iperf3 Network
- **목적**: 네트워크 대역폭 측정
- **템플릿**: `benchmarks/system/iperf3-network.yaml`
- **메트릭**: Gbits/sec
- **구성**: 서버 Pod + 클라이언트 Pod (같은 AZ 내 통신)

### Elasticsearch 벤치마크

#### ES Coldstart
- **목적**: Elasticsearch 노드 시작 시간 측정
- **템플릿**: `benchmarks/elasticsearch/elasticsearch-coldstart.yaml`
- **메트릭**: 시작 시간 (초) - 낮을수록 좋음
- **이미지**: `180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/benchmark/elasticsearch:8.11.1`
- **JVM 설정**: 가용 메모리의 60%를 힙으로 설정
- **측정 방식**: "started" 로그 메시지 출력까지의 시간
- **특징**:
  - C/M/R 패밀리 간 메모리 차이 (8GB/16GB/32GB)로 인한 성능 차이 확인
  - 노드 재시작, 스케일 아웃 시나리오에 중요

### Redis 벤치마크

#### Redis Server + Benchmark
- **목적**: 인메모리 데이터베이스 처리량 측정
- **템플릿**:
  - `benchmarks/redis/redis-server.yaml`: Redis 서버
  - `benchmarks/redis/redis-benchmark.yaml`: 벤치마크 클라이언트 (Graviton)
  - `benchmarks/redis/memtier-benchmark.yaml`: 벤치마크 클라이언트 (Intel/AMD)
- **메트릭**: ops/sec (SET/GET operations per second)
- **이미지**: `redis:7-alpine` (ECR pull-through)
- **구성**:
  1. Redis 서버 배포 (각 인스턴스에 1개)
  2. 벤치마크 클라이언트 실행 (같은 노드에 배치)
- **특징**:
  - Intel/AMD: memtier_benchmark 사용 (더 정밀한 latency 측정)
  - Graviton: redis-benchmark 사용 (memtier는 x86 전용)
  - 메모리 대역폭 + CPU 성능이 결합된 실제 워크로드

### Nginx 벤치마크

#### Nginx Server + wrk
- **목적**: HTTP 서버 처리량 및 지연시간 측정
- **템플릿**:
  - `benchmarks/nginx/nginx-server.yaml`: Nginx 서버
  - `benchmarks/nginx/nginx-benchmark.yaml`: wrk 클라이언트
- **메트릭**:
  - Requests/sec (처리량)
  - Latency (avg, p99)
- **이미지**: `nginx:alpine` (ECR pull-through)
- **wrk 설정**: `-t4 -c100 -d30s` (4 threads, 100 connections, 30초)
- **구성**:
  1. Nginx 서버 배포 (각 인스턴스에 1개)
  2. wrk 클라이언트 실행 (같은 Zone, 다른 노드에 배치)
- **특징**:
  - 실제 웹 서버 워크로드 시뮬레이션
  - Zone Affinity로 네트워크 지연 최소화
  - podAntiAffinity로 서버/클라이언트 노드 분리

### SpringBoot 벤치마크

#### SpringBoot Coldstart (PetClinic)
- **목적**: Java/Spring Boot 애플리케이션 시작 시간 측정
- **템플릿**: `benchmarks/springboot/springboot-coldstart.yaml`
- **메트릭**: 시작 시간 (초) - 낮을수록 좋음
- **이미지**: `180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/benchmark/springboot-petclinic:latest`
- **JVM 설정**: `-XX:InitialRAMPercentage=50.0 -XX:MaxRAMPercentage=60.0 -XX:+UseG1GC`
- **측정 방식**: "Started.*Application" 로그 메시지까지의 시간 파싱
- **특징**:
  - PetClinic 앱 사용 (실제 규모의 Spring 애플리케이션)
  - 5-8초 시작 시간으로 인스턴스 간 차이가 명확
  - JVM warm-up, class loading, Spring context 초기화 포함

#### SpringBoot wrk (Simple App)
- **목적**: Spring Boot REST API 처리량 측정
- **템플릿**:
  - `benchmarks/springboot/springboot-server.yaml`: 서버 (Deployment)
  - `benchmarks/springboot/springboot-benchmark.yaml`: wrk 클라이언트
- **메트릭**: Requests/sec, Latency
- **이미지**: `180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/benchmark/springboot-simple:latest`
- **특징**:
  - 간단한 REST API로 throughput 측정에 집중
  - JVM이 warmed-up된 상태에서 테스트
  - Zone Affinity로 네트워크 지연 최소화

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
