# EC2 Instance Benchmark Guide

## 개요

AWS EC2 인스턴스 타입(5세대~8세대, 총 51개)의 성능을 비교하는 Kubernetes 기반 벤치마크.
Karpenter를 사용하여 노드를 동적 프로비저닝하고, **5회 반복 실행**으로 편차를 줄임.

## 테스트 환경

| 항목 | 값 |
|------|-----|
| EKS 클러스터 | demo-hirehub-eks (ap-northeast-2) |
| 인스턴스 크기 | xlarge (4 vCPU) |
| 반복 횟수 | **5회** (평균 및 표준편차 계산) |
| 노드 격리 | podAntiAffinity (노드당 1개 벤치마크) |
| 이미지 저장소 | ECR (180294183052.dkr.ecr.ap-northeast-2.amazonaws.com) |

---

## 벤치마크 목록 및 측정 메트릭

### 1. Sysbench CPU

**목적**: CPU 연산 성능 측정 (소수 계산)

**테스트 방법**:
```
- Warm-up: 10초
- Multi-thread: 4 threads × 60초 × 3회 반복
- Single-thread: 1 thread × 30초
- prime-max=20000
```

**측정 메트릭**:
| 메트릭 | 설명 | 단위 | 방향 |
|--------|------|------|------|
| **MT events/sec** | 멀티스레드 초당 이벤트 | events/s | ⬆️ 높을수록 좋음 |
| **ST events/sec** | 싱글스레드 초당 이벤트 | events/s | ⬆️ 높을수록 좋음 |
| Latency avg | 평균 지연시간 | ms | ⬇️ 낮을수록 좋음 |
| Latency 95th | 95% 백분위 지연시간 | ms | ⬇️ 낮을수록 좋음 |

**CSV 출력**: `results/sysbench-summary.csv`
```csv
Instance Type,MT events/sec (avg),MT events/sec (std),ST events/sec (avg),ST events/sec (std)
```

**템플릿**: `benchmarks/system/sysbench-cpu.yaml`

---

### 2. Nginx (wrk HTTP)

**목적**: HTTP 서버 처리량 및 지연시간 측정

**테스트 방법**:
```
- Warm-up: 2t/50c × 10초
- Test 1: 2 threads, 100 connections, 30초
- Test 2: 4 threads, 200 connections, 30초
- Test 3: 8 threads, 400 connections, 30초
- Endpoint: / (index page ~300 bytes)
```

**측정 메트릭**:
| 메트릭 | 설명 | 단위 | 방향 |
|--------|------|------|------|
| **2t/100c req/sec** | 저부하 처리량 | req/s | ⬆️ 높을수록 좋음 |
| **4t/200c req/sec** | 중부하 처리량 | req/s | ⬆️ 높을수록 좋음 |
| **8t/400c req/sec** | 고부하 처리량 | req/s | ⬆️ 높을수록 좋음 |
| **Latency Avg** | 평균 응답 지연 | ms | ⬇️ 낮을수록 좋음 |

**CSV 출력**: `results/nginx-summary.csv`
```csv
Instance Type,2t/100c (avg),2t/100c (std),4t/200c (avg),4t/200c (std),8t/400c (avg),8t/400c (std),Latency Avg (ms)
```

**템플릿**: `benchmarks/nginx/nginx-server.yaml`, `benchmarks/nginx/nginx-benchmark.yaml`

---

### 3. Redis

**목적**: In-memory 데이터스토어 처리량 및 지연시간 측정

**테스트 방법**:
```
- Standard: 50 clients, 100K requests (SET/GET/INCR/LPUSH 등)
- Pipeline: 50 clients, 100K requests, 16 commands/pipeline
- High Concurrency: 100 clients, 200K requests
- Large Value: 1KB, 4KB values
```

**측정 메트릭**:
| 메트릭 | 설명 | 단위 | 방향 |
|--------|------|------|------|
| **SET ops/sec** | SET 명령 처리량 | ops/s | ⬆️ 높을수록 좋음 |
| **GET ops/sec** | GET 명령 처리량 | ops/s | ⬆️ 높을수록 좋음 |
| **Pipeline SET** | 파이프라인 SET 처리량 | ops/s | ⬆️ 높을수록 좋음 |
| **Latency p50** | 50% 백분위 지연시간 | ms | ⬇️ 낮을수록 좋음 |

**CSV 출력**: `results/redis-summary.csv`
```csv
Instance Type,SET (avg),SET (std),GET (avg),GET (std),Pipeline SET (avg),Pipeline SET (std),Latency p50 (ms)
```

**템플릿**: `benchmarks/redis/redis-server.yaml`, `benchmarks/redis/redis-benchmark.yaml`

---

### 4. Elasticsearch Cold Start

**목적**: Elasticsearch 클러스터 시작 시간 및 인덱싱/검색 성능 측정

**테스트 방법**:
```
- ES 8.11.0 다운로드 및 설치
- JVM 힙: 4GB (-Xms2g -Xmx4g)
- 시작 시간: process start → cluster yellow/green
- 순차 인덱싱: 100개 문서 개별 인덱싱
- 벌크 인덱싱: 1000개 문서 _bulk API
- 검색 테스트: match_all, term query (각 10회)
- JVM/GC 통계: 테스트 전후 수집
```

**측정 메트릭**:
| 메트릭 | 설명 | 단위 | 방향 |
|--------|------|------|------|
| **Cold Start** | 프로세스 시작 → 클러스터 ready | ms | ⬇️ 낮을수록 좋음 |
| **Sequential Index** | 100개 문서 순차 인덱싱 | ms | ⬇️ 낮을수록 좋음 |
| **Bulk Index** | 1000개 문서 벌크 인덱싱 | ms | ⬇️ 낮을수록 좋음 |
| **Search (match_all)** | 전체 검색 평균 응답시간 | ms | ⬇️ 낮을수록 좋음 |
| **Search (term)** | 조건 검색 평균 응답시간 | ms | ⬇️ 낮을수록 좋음 |
| **GC Time** | 테스트 중 GC 소요시간 | ms | ⬇️ 낮을수록 좋음 |

**CSV 출력**: `results/elasticsearch-summary.csv`
```csv
Instance Type,Cold Start (avg),Cold Start (std),Seq Index (avg),Bulk Index (avg),Search match_all (avg),Search term (avg),GC Time (avg)
```

**템플릿**: `benchmarks/elasticsearch/elasticsearch-coldstart.yaml`

---

### 5. Spring Boot Cold Start

**목적**: JVM 애플리케이션 시작 시간 측정

**테스트 방법**:
```
- Spring Boot Simple App (actuator 포함)
- JVM 옵션: -Xms2g -Xmx4g -XX:+UseG1GC
- 측정: Pod 시작 → /actuator/health UP
```

**측정 메트릭**:
| 메트릭 | 설명 | 단위 | 방향 |
|--------|------|------|------|
| **Cold Start** | Pod 시작 → Application ready | ms | ⬇️ 낮을수록 좋음 |

**CSV 출력**: `results/springboot-summary.csv`
```csv
Instance Type,Cold Start (avg ms),Cold Start (std ms)
```

**템플릿**: `benchmarks/springboot/springboot-coldstart.yaml`

---

## 실행 방법

### 자동 실행 (권장)

```bash
# 전체 벤치마크 실행 (5회 반복)
./scripts/run-all-benchmarks.sh all

# 개별 벤치마크 실행
./scripts/run-all-benchmarks.sh sysbench
./scripts/run-all-benchmarks.sh nginx
./scripts/run-all-benchmarks.sh redis
./scripts/run-all-benchmarks.sh elasticsearch

# 결과 파싱 및 CSV 생성
./scripts/parse-results.sh all
```

### 수동 실행

```bash
# 단일 인스턴스 실행
INSTANCE="c8i.xlarge"
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    benchmarks/system/sysbench-cpu.yaml | kubectl apply -f -

# Job 완료 대기
kubectl wait --for=condition=complete job/sysbench-cpu-c8i-xlarge -n benchmark --timeout=300s

# 로그 수집
kubectl logs job/sysbench-cpu-c8i-xlarge -n benchmark > results/sysbench/c8i.xlarge/run1.log
```

---

## 결과 디렉토리 구조

```
results/
├── sysbench/
│   ├── c8i.xlarge/
│   │   ├── run1.log
│   │   ├── run2.log
│   │   ├── run3.log
│   │   ├── run4.log
│   │   └── run5.log
│   └── ...
├── nginx/
│   └── {instance}/run{1-5}.log
├── redis/
│   └── {instance}/run{1-5}.log
├── elasticsearch/
│   └── {instance}/run{1-5}.log
├── sysbench-summary.csv
├── nginx-summary.csv
├── redis-summary.csv
└── elasticsearch-summary.csv
```

---

## 인스턴스 목록 (51개)

### Compute Optimized (c) - 17개
| 세대 | Intel/AMD (x86_64) | Graviton (arm64) |
|------|-------------------|------------------|
| 8세대 | c8i, c8i-flex | c8g |
| 7세대 | c7i, c7i-flex | c7g, c7gd |
| 6세대 | c6i, c6id, c6in | c6g, c6gd, c6gn |
| 5세대 | c5, c5a, c5d, c5n | - |

### General Purpose (m) - 17개
| 세대 | Intel/AMD (x86_64) | Graviton (arm64) |
|------|-------------------|------------------|
| 8세대 | m8i | m8g |
| 7세대 | m7i, m7i-flex | m7g, m7gd |
| 6세대 | m6i, m6id, m6in, m6idn | m6g, m6gd |
| 5세대 | m5, m5a, m5ad, m5d, m5zn | - |

### Memory Optimized (r) - 17개
| 세대 | Intel/AMD (x86_64) | Graviton (arm64) |
|------|-------------------|------------------|
| 8세대 | r8i, r8i-flex | r8g |
| 7세대 | r7i | r7g, r7gd |
| 6세대 | r6i, r6id | r6g, r6gd |
| 5세대 | r5, r5a, r5ad, r5b, r5d, r5dn, r5n | - |

---

## 아키텍처별 지원

| 벤치마크 | Intel/AMD (x86_64) | Graviton (arm64) |
|----------|-------------------|------------------|
| sysbench-cpu | ✅ | ✅ |
| redis-benchmark | ✅ | ✅ |
| nginx (wrk) | ✅ | ✅ (클라이언트는 x86) |
| elasticsearch | ✅ | ✅ |
| springboot | ✅ | ✅ |

---

## 주의사항

1. **5회 반복**: 모든 테스트는 5회 실행하여 평균/표준편차 계산
2. **노드 격리**: podAntiAffinity로 노드당 하나의 벤치마크만 실행
3. **Job TTL**: 10~60분 후 자동 삭제 - 그 전에 로그 수집 필요
4. **Karpenter**: 새 노드 생성에 1-2분 소요
5. **리소스**: `resources: {}` 설정으로 노드 전체 리소스 사용
