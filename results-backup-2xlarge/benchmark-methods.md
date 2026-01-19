# EC2 벤치마크 방법 상세 문서

## 1. sysbench CPU 벤치마크

### 개요
- **목적**: CPU 연산 성능 측정 (소수 계산)
- **도구**: sysbench
- **완료**: 51개 인스턴스

### 템플릿 위치
```
/home/ec2-user/benchmark/benchmarks/system/sysbench-cpu.yaml
```

### 테스트 파라미터
| 항목 | 값 |
|------|-----|
| 테스트 | Prime calculation |
| Prime limit | 20000 |
| Multi-thread | 8 threads, 60초 x 3회 |
| Single-thread | 1 thread, 30초 |
| Warm-up | 10초 |

### 실행 명령
```bash
# Intel/AMD (x86_64)
INSTANCE="c8i.2xlarge"
SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    /home/ec2-user/benchmark/benchmarks/system/sysbench-cpu.yaml | \
    kubectl apply -f -

# Graviton (arm64)
INSTANCE="c8g.2xlarge"
SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    /home/ec2-user/benchmark/benchmarks/system/sysbench-cpu.yaml | \
    kubectl apply -f -
```

### 결과 수집
```bash
POD=$(kubectl get pods -n benchmark -l benchmark=sysbench --no-headers -o custom-columns=":metadata.name" | grep $SAFE_NAME)
kubectl logs -n benchmark $POD > /home/ec2-user/benchmark/results/all/${INSTANCE}.log
```

### 결과 파싱
```bash
# Multi-thread events/sec
grep "events per second:" ${INSTANCE}.log | tail -1 | awk '{print $NF}'

# Single-thread events/sec
grep -A20 "Single Thread" ${INSTANCE}.log | grep "events per second:" | awk '{print $NF}'
```

### 결과 파일
- 로그: `/home/ec2-user/benchmark/results/all/*.log`
- CSV: `/home/ec2-user/benchmark/results/sysbench-summary.csv`

---

## 2. Redis 벤치마크

### 개요
- **목적**: In-memory 데이터베이스 성능 측정
- **도구**: memtier_benchmark (Intel/AMD), redis-benchmark (Graviton)
- **완료**: 38개 인스턴스

### 템플릿 위치
```
# 서버
/home/ec2-user/benchmark/benchmarks/redis/redis-server.yaml

# 클라이언트 (Intel/AMD)
/home/ec2-user/benchmark/benchmarks/redis/memtier-benchmark.yaml

# 클라이언트 (Graviton - memtier가 ARM 미지원)
/home/ec2-user/benchmark/benchmarks/redis/redis-benchmark.yaml
```

### 테스트 파라미터
| 항목 | memtier | redis-benchmark |
|------|---------|-----------------|
| Clients | 50 | 50 |
| Requests | 100,000 | 100,000 |
| Data size | 64 bytes | 64 bytes |
| Pipeline | 16 | 16 |

### 실행 명령
```bash
# 1. Redis 서버 배포
INSTANCE="c8i.2xlarge"
SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    /home/ec2-user/benchmark/benchmarks/redis/redis-server.yaml | \
    kubectl apply -f -

# 2. 서버 준비 대기
kubectl wait --for=condition=ready pod -l app=redis-server,instance-type=$INSTANCE -n benchmark --timeout=120s

# 3. 벤치마크 실행 (Intel/AMD)
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    /home/ec2-user/benchmark/benchmarks/redis/memtier-benchmark.yaml | \
    kubectl apply -f -

# 3. 벤치마크 실행 (Graviton)
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    /home/ec2-user/benchmark/benchmarks/redis/redis-benchmark.yaml | \
    kubectl apply -f -
```

### 결과 파싱
```bash
# memtier - SET ops/sec
grep "Sets" ${INSTANCE}.log | awk '{print $2}'

# redis-benchmark - SET ops/sec
grep "SET:" ${INSTANCE}.log | awk -F',' '{print $2}' | awk '{print $1}'
```

### 결과 파일
- 로그: `/home/ec2-user/benchmark/results/redis/*.log`
- CSV: `/home/ec2-user/benchmark/results/redis-summary.csv`

---

## 3. Nginx 벤치마크

### 개요
- **목적**: HTTP 서버 처리량 측정
- **도구**: wrk
- **완료**: 30개 인스턴스

### 템플릿 위치
```
# 서버
/home/ec2-user/benchmark/benchmarks/nginx/nginx-server.yaml

# 클라이언트
/home/ec2-user/benchmark/benchmarks/nginx/nginx-benchmark.yaml
```

### 테스트 파라미터
| 테스트 | Threads | Connections | Duration |
|--------|---------|-------------|----------|
| Low | 2 | 100 | 30s |
| Medium | 4 | 200 | 30s |
| High | 8 | 400 | 30s |

### Nginx 서버 설정
- `worker_processes auto`
- `worker_connections 10240`
- `keepalive_requests 10000`
- Access log 비활성화
- Gzip 비활성화 (순수 처리량 측정)

### 실행 명령
```bash
# 1. Nginx 서버 배포
INSTANCE="c8g.2xlarge"
SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    /home/ec2-user/benchmark/benchmarks/nginx/nginx-server.yaml | \
    kubectl apply -f -

# 2. 서버 준비 대기
kubectl wait --for=condition=ready pod -l app=nginx-server,instance-type=$INSTANCE -n benchmark --timeout=120s

# 3. 벤치마크 실행
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    /home/ec2-user/benchmark/benchmarks/nginx/nginx-benchmark.yaml | \
    kubectl apply -f -
```

### 결과 파싱
```bash
# Requests/sec (8t/400c 테스트)
grep "Requests/sec:" ${INSTANCE}.log | tail -1 | awk '{print $2}'

# Latency avg
grep "Latency" ${INSTANCE}.log | tail -1 | awk '{print $2}'
```

### 결과 파일
- 로그: `/home/ec2-user/benchmark/results/nginx/*.log`
- CSV: `/home/ec2-user/benchmark/results/nginx-summary.csv`

---

## 4. Elasticsearch Cold Start (보류)

### 개요
- **목적**: 컨테이너 시작부터 API 가용까지 시간 측정
- **상태**: 측정 방식 문제로 보류

### 템플릿 위치
```
/tmp/elasticsearch-coldstart-v3.yaml
```

### 알려진 문제
Sidecar 컨테이너가 ES와 동시에 시작되어 정확한 cold start 시간 측정 불가

---

## 5. Spring Boot JVM Startup (미완료)

### 개요
- **목적**: JVM 애플리케이션 시작 시간 측정
- **상태**: 테스트가 너무 단순하여 재설계 필요

### 현재 템플릿
```
/tmp/springboot-coldstart-job.yaml
```

### 문제점
- 단순 health check는 JVM warm-up을 반영하지 못함
- 실제 워크로드 하의 시작 시간 측정 필요

### 개선 계획
1. 실제 Spring Boot 애플리케이션 (예: petclinic) 사용
2. 첫 번째 HTTP 요청 응답까지의 시간 측정
3. JIT 컴파일 완료 후 성능 측정 포함

---

## 6. Elasticsearch Cold Start (미완료)

### 개요
- **목적**: ES 컨테이너 시작부터 클러스터 ready까지 시간 측정
- **상태**: 측정 방식 문제로 보류

### 현재 템플릿
```
/tmp/elasticsearch-coldstart-v3.yaml
```

### 측정 항목 (계획)
| 항목 | 설명 |
|------|------|
| HTTP_READY_MS | HTTP 포트 응답까지 시간 |
| COLD_START_MS | 클러스터 yellow/green까지 시간 |
| INDEX_TIME_MS | 100개 문서 인덱싱 시간 |

### 문제점
- Sidecar가 ES와 동시 시작 → 시작 시간 기준점 불명확
- 현재 결과: 7-15ms (비현실적, 실제 30-60초 예상)

### 개선 계획
1. **Option A**: InitContainer로 시작 시간 기록 후 ES 시작
2. **Option B**: Kubernetes Job 생성 시간을 기준점으로 사용
3. **Option C**: 별도 모니터링 Pod에서 ES Pod 감시

### 실행 명령 (현재)
```bash
INSTANCE="c8i.2xlarge"
SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
ARCH="amd64"  # arm64 for Graviton

sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
    -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
    -e "s/ARCH/${ARCH}/g" \
    /tmp/elasticsearch-coldstart-v3.yaml | kubectl apply -f -
```

---

## 디렉토리 구조

```
/home/ec2-user/benchmark/
├── benchmarks/
│   ├── system/
│   │   └── sysbench-cpu.yaml      # CPU 벤치마크
│   ├── redis/
│   │   ├── redis-server.yaml      # Redis 서버
│   │   ├── redis-benchmark.yaml   # Graviton용
│   │   └── memtier-benchmark.yaml # Intel/AMD용
│   └── nginx/
│       ├── nginx-server.yaml      # Nginx 서버
│       └── nginx-benchmark.yaml   # wrk 클라이언트
└── results/
    ├── all/                       # sysbench 로그
    ├── redis/                     # Redis 로그
    ├── nginx/                     # Nginx 로그
    ├── sysbench-summary.csv       # CPU 결과
    ├── redis-summary.csv          # Redis 결과
    └── nginx-summary.csv          # Nginx 결과
```
