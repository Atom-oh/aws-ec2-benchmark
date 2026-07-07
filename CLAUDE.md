# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EKS EC2 Node Benchmark - 다양한 EC2 인스턴스 타입(5세대~8세대, 54개)의 성능을 비교하는 Kubernetes 기반 벤치마크 프로젝트. Karpenter를 사용하여 노드를 동적 프로비저닝.

## 현재 상태 (2026-06-29)

### 인스턴스 목록 51→54 확장
`ap-northeast-2a/b/c` 서브넷이 모두 열리면서(이전 a/c만) 8세대에서 빠져 있던 3개 인스턴스를 정본 목록에
추가함(다른 세대는 이미 대응 변형이 있었음 — 5/6/7세대 전체 스윕으로 추가 누락 없음 확인):
- **c8gn.xlarge** (Graviton4, 네트워크 최적화 — c6gn 대응)
- **r8gd.xlarge** (Graviton4 + 로컬 NVMe — r6gd/r7gd 대응)
- **m8i-flex.xlarge** (Intel 8세대 flex — c8i-flex/r8i-flex 대응)

**⚠️ 라이브 NodePool과 `karpenter/nodepool-4vcpu.yaml` 드리프트 발견**: 이 파일은 실제 클러스터에서 쓰이지
않음(다른 NodePool 이름/존재하지 않는 nodeClass 참조). 실제 인스턴스 타입 제약은 라이브 `benchmark-server`
NodePool의 `requirements`에 있으며, 3개 신규 타입은 `kubectl patch nodepool benchmark-server --type=json`으로
직접 추가함(파일도 참고용으로 동기화해 둠). 향후 인스턴스 타입 추가 시 **라이브 NodePool을 직접 patch**할 것.

**백필 완료 (2026-07-02)**: sysbench CPU/Memory, Redis, Nginx, Elasticsearch Coldstart,
SpringBoot(Coldstart+wrk), iperf3, ClickHouse ClickBench — **8종 전부 신규 3개 인스턴스 원시
데이터 수집·검증 완료(54/54)**. 백필 과정에서 발견·수정한 버그 2건 (재현 시 참고):

1. **arch 정규식 버그** (ES coldstart, SpringBoot coldstart): `[[ "$1" =~ g\. ]]` 식 정규식은
   `c8gn.xlarge`/`r8gd.xlarge`처럼 "g" 뒤에 "n"/"d"가 오는 접미사를 못 잡아 **arm64를 amd64로
   오판** → nodeSelector가 `arch=amd64 AND instance-type=c8gn.xlarge`라는 불가능한 조합을 요구해
   영구 `FailedScheduling`. **AWS 용량 문제가 아니었음** — 겉보기엔 그렇게 보여서 처음엔 오진했음.
   해결: `config/instances-4vcpu.txt` 컬럼2를 `awk`로 조회(ClickHouse 스크립트와 동일 패턴), 정규식 금지.
2. **iperf3 서버 IP placeholder 미치환**: 템플릿의 `SERVER="IPERF_SERVER_IP"`는 서버 Service의
   실제 ClusterIP로 sed 치환해야 하는데 누락 → 전 테스트 "Bad file descriptor" 오류로 무효 데이터.
   해결: 서버 배포 후 `kubectl get svc ... -o jsonpath='{.spec.clusterIP}'`로 IP 획득, sed 치환.

**리포트 갱신 범위**: **ClickHouse ClickBench 리포트만 51→54 반영**(파서가 `results/`를 동적 스캔 +
`config/instances-4vcpu.txt` 조회라 재실행만으로 완료, 신규 3개 가격도 `aws pricing get-products`로
조회해 추가). **나머지 6개 리포트(sysbench/Redis/Nginx/ES/SpringBoot/iperf3)는 51개 기준 그대로** —
각 리포트가 과거에 별도 세션이 원시 로그를 수동 집계해 HTML에 JS 배열로 직접 박아넣은 방식이라
(예: sysbench의 `cpu_efficiency`/`mem_efficiency` 산출식) 정확히 재현하려면 원본 집계 로직을
역산해야 해서 리스크가 있어 보류. **원시 로그 자체는 8종 모두 54개 인스턴스분 존재**하니,
추후 이 6개 리포트를 갱신할 때는 새로 만들지 말고 각 리포트의 기존 JS 배열 스키마를 그대로 따라
54개분을 다시 계산해 넣을 것.

## 이전 상태 (2026-04-10)

### 변경사항
- **인스턴스 크기 **: 4 vCPU (xlarge)
- **Anti-affinity 적용**: 모든 템플릿에 `podAntiAffinity` 추가 - 노드 격리 보장
- **JVM Heap 60%**: Elasticsearch, SpringBoot에서 가용 메모리의 60%를 힙으로 설정
- **JVM TieredCompilation OFF**: SpringBoot 벤치마크에서 `-XX:-TieredCompilation` 필수 적용 (아래 상세 설명)

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
원시데이터=실제 로그 파일 수(54개 정본 목록 기준). 리포트=`reports/*.html`에 반영된 인스턴스 수
(원시데이터 확보와 리포트 반영은 별개 — 위 "리포트 갱신 범위" 참고).
| 벤치마크 | 원시데이터 | 리포트 | 반복 | 템플릿 | 결과 위치 |
|----------|------|------|------|--------|-----------|
| sysbench CPU | 54/54 | 51/54 | 5회 | `benchmarks/system/sysbench-cpu.yaml` | `results/sysbench-cpu/<instance>/` |
| sysbench Memory | 54/54 | 51/54 | 5회 | `benchmarks/system/sysbench-memory.yaml` | `results/sysbench-memory/<instance>/` |
| Redis | 54/54 | 51/54 | 5회 | `benchmarks/redis/redis-*.yaml` | `results/redis/<instance>/run<N>.log` |
| Nginx (wrk) | 54/54 | 51/54 | 5회 | `benchmarks/nginx/nginx-*.yaml` | `results/nginx/<instance>/run<N>.log` |
| ES Coldstart | 54/54 | 51/54 | 5회 | `benchmarks/elasticsearch/elasticsearch-coldstart.yaml` | `results/elasticsearch/<instance>/run<N>.log` |
| SpringBoot Coldstart | 54/54 | 51/54 | 5회 | `benchmarks/springboot/springboot-coldstart.yaml` | `results/springboot/<instance>/coldstart<N>.log` |
| SpringBoot wrk | 54/54 | 51/54 | 5회 | `benchmarks/springboot/springboot-benchmark.yaml` | `results/springboot/<instance>/wrk<N>.log` |
| iperf3 Network | 54/54 | 51/54 | 5회 | `benchmarks/system/iperf3-network.yaml` | `results/iperf3/<instance>/run<N>.log` |
| ClickHouse ClickBench | 54/54 | **54/54** | 5세트 | `benchmarks/clickhouse/clickhouse-clickbench.yaml` | `results/clickhouse/<instance>/set<N>.log` |
| Kafka (베이스라인) | 54/54 | **54/54** | 5회 | `benchmarks/kafka/kafka-server.yaml` + `kafka-benchmark.yaml` | `results/kafka/<instance>/run<N>.log` |
| Kafka (포화, 8-way+압축) | 54/54 | **54/54** | 5회×3코덱 | `kafka-server.yaml` + `kafka-benchmark-max.yaml` | `results/kafka-max/<instance>/<codec>-run<N>.log` |
| Kafka (램프업, Phase 3) | 54/54 | **54/54** | 1회(8단계) | `kafka-server.yaml` + `kafka-benchmark-ramp.yaml` | `results/kafka-ramp/<instance>/run1.log` |

### 알려진 결과 문제
- ~~**c7i-flex.xlarge 프로비저닝 불가**~~: mall-apne2-mgmt 클러스터 서브넷이 ap-northeast-2a/2c에만 존재해 2b/2d 전용인
  c7i-flex.xlarge가 프로비저닝 불가했던 문제. SpringBoot wrk는 2026-01-20 수집 시점에 이미 51/51 정상 완료(당시
  "50/51 누락" 기록은 오기). ClickHouse ClickBench는 실제로 누락 상태였다가 **2026-06-29 ap-northeast-2b 서브넷
  추가로 해결**되어 51/51로 재수집 완료.
- **Nginx r8i.xlarge**: run3, run5에서 성능 저하 (80k vs 250k req/sec). 재테스트 필요.
  - 원인: 특정 노드에서 간헐적 성능 저하 (noisy neighbor 또는 CPU throttling 추정)
- **Kafka 베이스라인 고지연 인스턴스 11개**: 위 "Kafka" 상세 섹션 참고 — c7g/c7i/c8i 등 5/5 run 재현되는
  70~150ms 고지연. 원인 미확정.
- ~~**Kafka 포화 r5a.xlarge lz4 run4 타임아웃**~~: 최초 전체 실행(810 Job) 중 1건 `JOB_TIMEOUT`(1200s)
  초과로 로그 미수집. 브로커 재배포 후 해당 조합만 단독 재실행해 백필 완료(15/15).

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
    value: "-XX:InitialRAMPercentage=50.0 -XX:MaxRAMPercentage=60.0 -XX:+UseG1GC -XX:MaxGCPauseMillis=100 -XX:-TieredCompilation -XX:ReservedCodeCacheSize=64M -XX:InitialCodeCacheSize=64M"
```

### JVM TieredCompilation OFF (필수)
SpringBoot 벤치마크에서 **`-XX:-TieredCompilation`을 반드시 적용**해야 합니다.

**적용 플래그:**
```
-XX:-TieredCompilation          # C1 JIT 건너뛰고 C2만 사용
-XX:ReservedCodeCacheSize=64M   # C2 전용 코드 캐시 크기 최적화
-XX:InitialCodeCacheSize=64M    # 초기 코드 캐시 할당
```

**이유:**
- 기본 JVM은 C1(빠른 컴파일) → C2(최적화 컴파일) 2단계 TieredCompilation 사용
- C2 컴파일러가 생성하는 네이티브 코드 품질이 아키텍처(ARM/x86)에 따라 다름
- TieredCompilation OFF로 C2만 사용하면 아키텍처별 최적 네이티브 코드를 생성하여 **공정한 비교** 가능
- wrk 벤치마크는 30초 warm-up 후 측정하므로 C2 워밍업 지연이 결과에 영향 없음

**검증 결과 (c8g vs c8i, 100 connections 평균):**
| 설정 | c8g (Graviton4) | c8i (Intel 8th) | Graviton vs Intel |
|------|----------------|----------------|-------------------|
| TieredCompilation ON (기본) | 66,933 req/s | 81,303 req/s | -17.6% |
| TieredCompilation OFF (적용) | 72,867 req/s | 75,708 req/s | -3.7% |

**⚠️ 주의: 이 플래그 없이 측정하면 JIT 컴파일 전략 차이가 인스턴스 성능 차이로 잘못 해석될 수 있음.**

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
| clickhouse-clickbench.yaml | ❌ | ✅ | ✅ | ✅ |
| kafka-server.yaml | ❌ | ✅ | ✅ | ✅ |
| kafka-benchmark.yaml | ❌ | ✅ | ✅ | ❌ (클라이언트는 benchmark-client 노드에서 amd64 고정) |

> clickhouse-clickbench.yaml 은 추가로 `RUN_NUMBER`(세트 번호)와 `CLICKHOUSE_VERSION`(=`24.8.14.39`) placeholder를 사용한다.
> kafka-server.yaml/kafka-benchmark.yaml 은 추가로 `RUN_NUMBER`(kafka-benchmark만)와 `KAFKA_VERSION`(=`3.9.1`) placeholder를 사용한다.

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

### ClickHouse 벤치마크

#### ClickHouse ClickBench
- **목적**: OLAP 컬럼형 DB의 대용량 스캔·집계 쿼리 성능 측정 (기존 벤치마크와 다른 분석 워크로드)
- **워크로드**: ClickHouse 공식 **ClickBench** 43쿼리 + INSERT(1천만 행) + self-JOIN
- **템플릿**:
  - `benchmarks/clickhouse/clickhouse-storageclass.yaml`: SC `gp3-clickhouse`(16000 IOPS/1000MB/s) + VolumeSnapshotClass (둘 다 클러스터에 이미 존재, 멱등 apply)
  - `benchmarks/clickhouse/clickhouse-snapshot.yaml`: 정적 VolumeSnapshot `clickhouse-hits-024`(→ snap-024). 기존 `clickhouse-hits-snap`과 이름이 달라 live apply 안전(Retain). generate 스크립트가 실행 전 자동 apply
  - `benchmarks/clickhouse/clickhouse-clickbench.yaml`: Job + PVC(스냅샷 복구)
  - `benchmarks/clickhouse/queries/{queries,insert,join}.sql`
- **데이터**: EBS 스냅샷 **snap-024c86faa00cd0448**에서 PVC 복구 (적재 단계 생략).
  ClickHouse **24.8.14.39**, `default.hits` (MergeTree), **99,997,497행 / 13.44GiB / 105컬럼**.
- **이미지**: `clickhouse/clickhouse-server:24.8.14.39` (multi-arch — Intel/Graviton 동일 스냅샷)
- **측정 방식**: 단일 컨테이너에서 server 백그라운드 기동 → 쿼리 개별 실행(per-query cold/hot 타이밍) →
  INSERT → self-JOIN → 정상 종료. 5세트 = 5 Job 실행, 각 setN.log.
- **실행/리포트**:
  - `scripts/generate-clickhouse-benchmark.sh` (ConfigMap 생성 + 배치 12개 병렬 + 수집)
  - `scripts/generate-clickhouse-report.py` (setN.log 파싱 → `report-charts.html` 데이터 주입)
  - 검증: `bash tests/clickhouse/validate.sh`
- **⚠️ 공정성 주의 (EBS 교란)**: 모든 인스턴스가 동일 gp3 스펙을 쓰지만 실제 처리량은 **per-instance EBS
  대역폭 상한**에 종속되고, 13.44GiB는 8GB(C패밀리) page cache에 안 들어가 hot 쿼리도 EBS를 읽는다.
  → hot 지연은 "memory ≥ dataset"(R패밀리 등) 인스턴스에서만 순수 page-cache-bound. Pod에 **고정 메모리
  limit 미설정**(C/M/R 메모리 차이를 비교 변수로 보존). 자세한 내용은 `docs/superpowers/specs/2026-06-25-clickhouse-clickbench-design.md` §5.

#### Kafka
- **목적**: 이벤트 스트리밍 플랫폼의 producer/consumer 처리량·지연 측정 (기존 벤치마크와 다른 네트워크 중심 워크로드)
- **워크로드**: `kafka-producer-perf-test` → `kafka-consumer-perf-test`, 레코드 500만건 × 1KB(~4.77GiB/회),
  `acks=all linger.ms=10 batch.size=131072`
- **토폴로지**: 브로커(KRaft 단일 노드, combined broker+controller)는 대상 인스턴스에 Deployment로 배포,
  perf 클라이언트는 **별도 `benchmark-client` 노드풀(c6in.2xlarge, amd64 고정)**에서 podAffinity로 같은 AZ에 배치
  (redis/nginx의 서버-클라이언트 분리 패턴과 동일)
- **템플릿**:
  - `benchmarks/kafka/kafka-server.yaml`: PVC(gp3-clickhouse, 100Gi, 빈 볼륨) + Deployment(`strategy: Recreate`
    필수 — RWO PVC 단일 replica는 기본 RollingUpdate 시 신규 pod가 볼륨을 못 붙잡아 데드락) + Service
  - `benchmarks/kafka/kafka-benchmark.yaml`: 클라이언트 Job (produce→consume→토픽 정리)
- **이미지**: Docker Hub `apache/kafka:3.9.1` 직접 참조 (multi-arch amd64/arm64 — ClickHouse와 동일하게
  ECR pull-through 없이 Docker Hub 직접 pull. `docker-hub/` ECR pull-through prefix는 Docker Hub 인증
  자격증명이 있어야 생성 가능해 이 환경에는 실제로 존재하지 않음 — CLAUDE.md의 과거 서술과 달리 라이브로 확인됨)
- **바이너리 경로 주의**: 이미지 `PATH`에 `/opt/kafka/bin`이 없음 — `kafka-*.sh` 호출 전 반드시
  `export PATH="/opt/kafka/bin:${PATH}"` 필요(스크립트에 이미 반영)
- **힙**: 브로커 힙 = RAM의 **25%**(RAM-relative), 나머지는 OS page cache에 위임 — Kafka는 힙보다
  page cache 적중률이 처리량을 좌우하므로 절대 바이트가 아닌 비율로 설정. Pod에 memory limit 미설정
- **KRaft 기동 시 주의(재현 시 참고)**: `KAFKA_LOG_DIRS`를 PVC **루트에 직접** 잡으면 신규 ext4 볼륨의
  `lost+found` 디렉터리를 Kafka가 "topic-partition 형식이 아니다"라며 기동 실패시킨다 → `log.dirs`는
  PVC 루트가 아닌 하위 디렉터리(`/var/lib/kafka/data/logs`)로 잡을 것
- **bootstrap 주소**: 런타임 IP 치환 없이 Service DNS(`kafka-server-INSTANCE_SAFE.benchmark.svc.cluster.local:9092`)
  고정 — iperf3의 ClusterIP placeholder 미치환 버그를 원천 차단하는 설계
- **실행/리포트**:
  - `scripts/generate-kafka-benchmark.sh` (인스턴스별 브로커 1개 배포 → 클라이언트 Job 5회 순차 → 수집 → 정리, 인스턴스 간 완전 병렬)
  - `scripts/generate-kafka-report.py` (runN.log 파싱 → `report-charts.html` 데이터 주입)
  - 검증: `bash tests/kafka/validate.sh`
- **⚠️ 공정성 주의 (네트워크 교란)**: produce/consume 각 ~4.8GB가 네트워크를 지나므로 인스턴스별
  네트워크 baseline/burst 대역폭이 결과에 반영됨(구세대 xlarge는 버스트 크레딧 소진 가능) — **iperf3
  리포트와 교차 참조 권장**. 디스크는 gp3 스펙 통일이나 per-instance EBS 대역폭 상한에는 여전히 종속.
- **⚠️ 알려진 이슈 — 베이스라인 일부 인스턴스 고지연**: c7g/c7i/c8i, m7i-flex/m7gd/m8i/m8i-flex,
  r7gd/r8i/r8i-flex/r8gd.xlarge는 5회 run 전부에서 일관되게 produce 평균지연 70~150ms(다른 인스턴스는
  ~1ms)·처리량 ~200MB/s(다른 인스턴스는 ~285MB/s)로 낮게 나옴. **1~2회성 noisy neighbor가 아님**(5/5
  재현) — EBS 대역폭 캡(1000MB/s)도 배제됨(실제 처리량이 그 캡의 1/5 수준). 세대·flex 여부·NVMe 서픽스로
  깨끗이 갈리지 않아(같은 C7 패밀리에서 c7g만 느리고 c7gd는 빠름 등) 근본 원인 미확정 — 네트워크
  스택(지연 ACK/ENA 드라이버 세대차) 추정이나 확인 못함. 재현 시 조용한 상태에서 해당 인스턴스만 재측정 +
  패킷 캡처 권장.

#### Kafka Phase 2 — 포화(saturation) 시나리오
베이스라인은 싱글 producer/consumer + 무압축이라 CPU-bound가 아니라 단일 커넥션의 네트워크 RTT/배치
처리량에 상한이 걸려 대상 인스턴스 CPU를 다 못 쓰는 것으로 진단됨(위 고지연 이슈와는 별개 현상). 이를
제거하기 위해 8-way 병렬 + 토픽 레벨 압축(uncompressed/lz4/zstd, 5회×3코덱=15 run/인스턴스)을 추가 측정.
- **템플릿**: `benchmarks/kafka/kafka-benchmark-max.yaml` (브로커는 `kafka-server.yaml` 그대로 재사용)
- **압축은 토픽 설정으로 강제**(`kafka-topics.sh --config compression.type=CODEC`), **producer-props에는
  압축 설정 안 함** — producer 압축은 클라이언트(전 인스턴스 공통 c6in.2xlarge) CPU를 쓰므로 측정 목적이
  깨짐. 브로커(대상 인스턴스)가 쓰기 경로에서 재압축해야 대상 인스턴스에 실제 CPU 부하가 실림
- **payload**: `awk`로 JSON 골격 + `srand(42)` 고정시드 준랜덤 data 필드(500줄×1024B) 생성.
  단순 반복 패턴("ABAB..")은 100x+ 로 과압축되어 CPU 부하를 왜곡하므로 반드시 준랜덤 필드 필요
  (gzip 기준 실측 ratio ~1.7x로 현실적인 로그/이벤트 페이로드에 근접)
- **압축률 측정**: `kafka-log-dirs.sh --describe`로 토픽 온디스크 바이트 합산 → ratio = 원본/온디스크
- **실행**: `scripts/generate-kafka-max-benchmark.sh` (결과: `results/kafka-max/<instance>/<codec>-run<N>.log`)
- **1차 시도(gp3 1000MB/s)에서 발견한 문제 → 스토리지 상향 → 재측정**: 최초 측정(gp3-clickhouse,
  1000MB/s)에서 gen6~8 다수 인스턴스가 그 볼륨 캡 근처에 몰려 세대 "역전"(예: r7g 1038.9 > r8g 1010.3)이
  나타남 — AWS `describe-instance-types`로 R패밀리 6~8세대의 실제 EBS-optimized 한도가 **1250MB/s**임을
  확인, 우리가 그보다 낮은 1000MB/s로 스스로 캡을 걸었던 것이 원인이었음. lz4 압축 시 처리량이 오히려
  상승하는 것으로(디스크 부담 감소) EBS가 병목임을 검증.
  - **io2 전환을 시도했으나 계정 쿼터로 실패**: io2 Block Express(최대 4000MiB/s)로 전환해 64,000 IOPS로
    설정했더니, 계정 단위 "IOPS for Provisioned IOPS SSD (io2) volumes" 쿼터가 **리전 전체 100,000**이라
    (`aws service-quotas list-service-quotas --service-code ebs`로 확인) 볼륨 2개만 동시에 떠도 쿼터
    초과 — 54개 완전 병렬 실행이 53/54 스케줄 불가로 전멸. **io2는 이런 계정 단위 IOPS 쿼터가 있어
    대량 병렬 벤치마크에 근본적으로 부적합** — 재현 시 io2로 시도하지 말 것(쿼터 증량 없이는 불가).
  - **최종: gp3 절대 최대(2000MiB/s)로 상향**. gp3는 별도 IOPS 계정 쿼터가 없음(스토리지 TiB 쿼터만
    98TiB로 충분) — StorageClass `gp3-kafka`(`benchmarks/kafka/kafka-storageclass.yaml`, type=gp3,
    iops=16000, throughput=2000)로 재측정, **810/810 로그, 실패 0건**으로 완료.
- **최종 결과(gp3 2000MB/s 기준)**: 포화(uncompressed 8-way) 최고 처리량 c6in.xlarge 1122.6MB/s. **전
  54개 인스턴스 중 2000MB/s 캡의 90%(1800MB/s)에 도달한 인스턴스 0개** — 스토리지 캡이 결과에 더 이상
  영향을 주지 않음을 확인(m6in/m6idn/c6in처럼 자체 한도가 3125MB/s로 더 높은 인스턴스도 실측
  831~1123MB/s에 그쳐 캡과 무관하게 다른 요인이 병목). 세대별 평균: gen5 531 → gen6 865 → gen7 1023 →
  gen8 993MB/s — 이제 순수 하드웨어 차이 반영(gen7이 gen8보다 근소하게 높은 건 EBS 캡이 아닌 실측
  변동/특성). 최대 스케일링 배수 m8i-flex.xlarge 5.48x(베이스라인이 단일 커넥션에 그만큼 인위적으로
  제한돼 있었다는 증거). zstd는 lz4보다 압축률은 높지만(예: c5.xlarge 1.87x) 브로커 CPU 비용이 커
  produce 처리량이 하락하는 트레이드오프 확인.
- **⚠️ 방법론적 캐비어트(Phase 3에서 부분 해결)**: AWS 공식
  [performance-testing-framework-for-apache-kafka](https://github.com/aws-samples/performance-testing-framework-for-apache-kafka)는
  (1) 처리량을 점진적으로 올려 실제 포화점을 찾고, (2) 테스트 전 EC2 네트워크/EBS 버스트 크레딧을
  고갈시켜 sustained 성능을 측정하며, (3) 1시간 단위로 테스트한다. §9(포화)는 run당 수분짜리 짧은
  테스트라 burst 성능을 측정했을 가능성이 있었음 — **이 캐비어트는 아래 Phase 3(램프업)에서 (1)(2)를
  단축 적용해 부분적으로 해결**(1시간 단위는 54개×장시간이라 비용상 적용 안 함).
- **kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }` 방어 패턴 필수**: 이 환경은 공유
  kubeconfig라 무관한 다른 세션이 current-context를 바꿔놓을 수 있음(실제로 한 번 발생 — 다른 프로젝트의
  Istio mesh 테스트 세션이 context를 변경). 세 kafka 실행 스크립트 모두 `kubectl` 함수를 재정의해
  `--context mall-apne2-mgmt`를 강제하므로 ambient current-context와 무관하게 항상 올바른 클러스터를 향함.

#### Kafka Phase 3 — 램프업 · 포화점 · 지연곡선
§9(포화)는 항상 8-way 최대치로 밀어붙여 "얼마나 세게 밀면 이 정도 나온다"만 보여주고, burst 성능일
가능성도 있었음. AWS 공식 프레임워크의 핵심 방법론(점진 램프업 + 정지조건 + 버스트크레딧 고갈)을
54개 인스턴스 규모에 맞게 축소 적용해 **진짜 포화점과 처리량-지연 곡선**을 추가로 측정(1회 측정).
- **템플릿**: `benchmarks/kafka/kafka-benchmark-ramp.yaml` (브로커는 `kafka-server.yaml` 재사용)
- **흐름**: (1) 90초 무제한 8-way produce로 버스트 크레딧 고갈 → (2) 디스크 회수를 위해 토픽
  재생성 → (3) §9(uncompressed 8-way) 실측치의 20/40/60/80/100/120/140/160%를 8단계로 증가시키며
  각 20초씩 측정, 실제/목표 비율이 **99.5% 미달**하는 첫 단계를 포화점으로 판정하고 조기 종료
- **BASELINE_MB 치환 함정(재현 시 참고)**: 초기 구현에서 sed placeholder 이름을 그대로 bash 변수명/로그
  라벨로 재사용(`BASELINE_MB="BASELINE_MB"`, `echo "BASELINE_MB: ..."`) → sed가 변수명 자체까지
  치환해버려 `1067.86="1067.86"` 같은 문법 오류로 전부 깨짐. 변수명은 `BASE_MB`, 로그 라벨은
  `REF_MB:`로 분리해 해결 — **sed placeholder와 텍스트가 100% 동일한 문자열을 스크립트 다른 곳에
  재사용하지 말 것**(부분 문자열 포함도 위험: `BASELINE_MB_REF` 같은 이름도 여전히 치환됨).
- **⚠️ 디스크 폭증으로 브로커 크래시(재현 시 참고)**: 90초 무제한 고갈이 빠른 인스턴스(~1200MB/s)에서
  90초에 100GB+를 써서 원래 100Gi PVC를 채워 `No space left on device`로 브로커가
  CrashLoopBackOff에 빠짐. 램프 8단계 누적도 최대 ~140GB 가능해 합산 worst-case ≈250GB. PVC를
  **400Gi로 상향**(`kafka-server.yaml`, 세 Phase 공용) + 고갈 후 토픽 재생성으로 디스크 회수해 해결.
- **⚠️ pod 조회 레이스로 거짓 성공 로그(재현 시 참고)**: `kubectl get pods -l job-name=...`가 API
  순간 부하로 빈 값을 반환해도 `[ -n "$pod" ] && kubectl logs ...; log "수집 완료"`처럼 세미콜론으로
  연결돼 있으면 **로그 수집이 실패해도 "수집 완료"가 무조건 찍힘**(54개 중 8개에서 실제 발생, 로그
  파일은 비어있는데 스크립트는 성공으로 기록). 세 kafka 스크립트 모두 `find_pod()`(최대 5회 재시도) +
  `[ -s "$lf" ]`(실제 파일 크기 확인) 조합으로 수정 — 재시도 후에도 못 찾으면 명시적으로 실패 로그.
- **결과**: 54/54 인스턴스가 테스트 범위(baseline의 160%) 안에서 포화점에 도달. 최고 포화점
  c6in.xlarge 1302.2MB/s(§9의 8-way 최대치 1122.6MB/s보다 높음 — 램프가 §9보다 더 정밀하게 진짜
  한계를 찾아낸 것). 최저 c5a.xlarge 379.3MB/s(AMD, 예상대로 최하위).
- **실행/리포트**: `scripts/generate-kafka-ramp-benchmark.sh` (§9 uncompressed 실측치를 100% 기준점으로
  자동 조회), 결과 `results/kafka-ramp/<instance>/run1.log`, 검증 `bash tests/kafka/validate.sh`.

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
    <script src="report-nav.js" defer></script>
    <link rel="stylesheet" href="report-common.css">
    <style>/* 벤치마크별 고유 스타일만 (공통 변수/카드/차트/badge/navbar는 report-common.css에 있음) */</style>
</head>
```
**`<link>`는 반드시 `<style>`보다 앞**에 둘 것 — 인라인 `<style>`의 규칙이 캐스케이드에서 항상 이겨서
파일별 오버라이드가 안전하게 동작한다.

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

#### 8. 공통 navbar/CSS (`reports/` 발행본 전용, 2026-07-07 도입)
`reports/*-report.html` 11개가 각자 navbar를 하드코딩하던 걸 걷어내고 2개 공유 파일로 뺐다.
새 벤치마크 리포트를 추가할 때 **11개 파일을 고치지 말고**:
1. `reports/report-nav.js`의 `REPORTS` 배열에 `{ file: '<name>-report.html', name: '<표시명>' }` 1줄만 추가.
   (navbar `<nav>` 마크업은 이 스크립트가 `document.body` 맨 위에 런타임 주입 — HTML에는 없음)
2. 새 리포트 `<head>`에 위 헤더 예시처럼 `<script src="report-nav.js" defer>` + `<link href="report-common.css">` 추가.
3. `report-common.css`에는 `:root` 변수, `.container/header/.card/.chart-section/.chart-container/.grid-*/
   .tab-*/.metric-tab/.legend-*/.insights/.analysis-box/table/.badge-*/footer/.navbar*`가 들어있음(기준본:
   `nginx-report.html`). 벤치마크 고유 스타일(예: 커스텀 탭 UI)만 자체 `<style>`에 남길 것.
- **`results/kafka/report-charts.html`, `results/clickhouse/report-charts.html`**(패턴 A, 스크립트가
  데이터 주입 후 `reports/`로 복사)는 위치가 달라 `../../reports/report-common.css`,
  `../../reports/report-nav.js` 상대경로를 쓴다. `scripts/generate-{kafka,clickhouse}-report.py`가
  `reports/`로 복사할 때 `../../reports/` → `` 치환을 자동으로 해줌 — 새로 패턴 A 스크립트를 만들 때
  이 치환 한 줄을 그대로 가져다 쓸 것.
- **패턴 B**(geekbench/sysbench/passmark/stress-ng/redis — f-string으로 HTML 전체 생성, 과거 수동 집계
  로직이라 재생성 금지 대상)는 이번에 건드리지 않음. 이 5개를 재갱신할 일이 생기면 그때 헤더에 2줄
  추가 + navbar 마크업 제거를 적용할 것(스크립트 f-string 템플릿에 위 헤더 예시를 반영).
- `reports/index.html`(랜딩 페이지, 다크 테마 — 표준과 무관한 별도 디자인)의 리포트 링크는 형제 상대경로
  (`href="kafka-report.html"`)로 통일되어 있음. `reports/`를 통째로 옮기지 않는 한 건드릴 필요 없음.

### 참고 보고서
- `results/nginx/report-charts.html` - 가장 완성도 높음
- `results/redis/report-charts.html` - Redis 특화
- `results/stress-ng/report-charts.html` - 최신 생성
