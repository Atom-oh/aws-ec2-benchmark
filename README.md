# EC2 Instance Benchmark Suite

EKS 클러스터에서 Karpenter를 사용하여 다양한 EC2 인스턴스 타입의 성능을 비교하는 벤치마크 스위트입니다.

> **상세 문서**: [BENCHMARK-GUIDE.md](./BENCHMARK-GUIDE.md) - 벤치마크 방법, 결과 형식, Docker 이미지 정보

## 테스트 환경

- **EKS 클러스터**: demo-hirehub-eks (ap-northeast-2)
- **인스턴스 크기**: xlarge (4 vCPU)
- **Karpenter NodePool**: benchmark-4vcpu-* (dedicated taints)
- **노드 격리**: podAntiAffinity로 벤치마크 Pod 격리

## 벤치마크 종류

### 1. CPU Benchmark (sysbench)
- **테스트**: Prime calculation, 20000 prime limit
- **측정**: Multi-thread (4 threads, 60s), Single-thread (1 thread, 30s)
- **템플릿**: `benchmarks/system/sysbench-cpu.yaml`

### 2. Redis Benchmark
- **테스트**: memtier_benchmark (Intel/AMD), redis-benchmark (Graviton)
- **측정**: SET ops/sec, GET ops/sec, Pipeline SET ops/sec, Latency p50
- **템플릿**: `benchmarks/redis/redis-*.yaml`

### 3. Nginx Benchmark (wrk)
- **테스트**: HTTP requests, 2 threads, various connections
- **측정**: Requests/sec, Latency average
- **템플릿**: `benchmarks/nginx/nginx-*.yaml`

### 4. Elasticsearch Cold Start
- **테스트**: ES 8.11.0 시작 시간 (single container 방식)
- **측정**: HTTP Ready 시간, Cluster Ready 시간, Index 성능
- **템플릿**: `benchmarks/elasticsearch/elasticsearch-coldstart.yaml`

### 5. Spring Boot Cold Start
- **테스트**: JVM 시작 시간
- **측정**: Application ready 시간
- **템플릿**: `benchmarks/springboot/springboot-coldstart.yaml`

## 테스트 대상 인스턴스 타입 (51개)

### Intel (x86_64)
| Generation | Compute (c) | General (m) | Memory-Opt (r) |
|------------|-------------|-------------|----------------|
| 5th | c5, c5d, c5n | m5, m5d, m5zn | r5, r5b, r5d, r5n, r5dn |
| 6th | c6i, c6id, c6in | m6i, m6id, m6in, m6idn | r6i, r6id |
| 7th | c7i, c7i-flex | m7i, m7i-flex | r7i |
| 8th | c8i, c8i-flex | m8i | r8i, r8i-flex |

### AMD (x86_64)
| Generation | Compute | General | Memory-Opt |
|------------|---------|---------|------------|
| 5th | c5a | m5a, m5ad | r5a, r5ad |

### Graviton (arm64)
| Generation | Compute (c) | General (m) | Memory-Opt (r) |
|------------|-------------|-------------|----------------|
| Graviton 2 (6g) | c6g, c6gd, c6gn | m6g, m6gd | r6g, r6gd |
| Graviton 3 (7g) | c7g, c7gd | m7g, m7gd | r7g, r7gd |
| Graviton 4 (8g) | c8g | m8g | r8g |

## 실행 방법

### Prerequisites
```bash
# EKS 클러스터 접근
aws eks update-kubeconfig --name demo-hirehub-eks --region ap-northeast-2

# Karpenter NodePool 적용
kubectl apply -f karpenter/nodepool-4vcpu.yaml
```

### 벤치마크 Job 실행
```bash
# Intel 인스턴스
INSTANCE="c8i.xlarge"
sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
    benchmarks/system/sysbench-cpu.yaml | kubectl apply -f -

# Graviton 인스턴스
INSTANCE="c8g.xlarge"
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

### 결과 수집
```bash
# Pod 로그 수집
POD=$(kubectl get pods -n benchmark -l benchmark=sysbench --no-headers -o custom-columns=":metadata.name" | grep c8i)
kubectl logs -n benchmark $POD > results/sysbench/c8i.xlarge.log
```

## 디렉토리 구조

```
/home/ec2-user/benchmark/
├── README.md                    # 이 파일
├── CLAUDE.md                    # Claude Code 작업 가이드
├── config/
│   └── instances-4vcpu.txt      # xlarge 인스턴스 목록 (51개)
├── benchmarks/
│   ├── system/                  # sysbench, stress-ng, fio, iperf3
│   ├── redis/                   # redis-server, redis-benchmark, memtier
│   ├── nginx/                   # nginx-server, wrk, wrk2
│   ├── springboot/              # springboot-server, benchmark, coldstart
│   └── elasticsearch/           # elasticsearch-coldstart
├── karpenter/
│   └── nodepool-4vcpu.yaml      # Karpenter NodePool (xlarge)
├── results/                     # 결과 저장
└── results-backup-2xlarge/      # 이전 2xlarge 결과 백업 (무효)
```

## 핵심 설계 원칙

### 노드 격리 (Anti-Affinity)
모든 벤치마크 Pod에 podAntiAffinity 적용:
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

이를 통해 한 노드에 하나의 벤치마크 Pod만 실행되어 정확한 성능 측정 보장.

## 주의사항

1. **Docker Hub Rate Limit**: ECR Public 이미지 사용
2. **ARM 이미지 호환성**: memtier_benchmark는 x86 only → Graviton에서 redis-benchmark 사용
3. **노드 스케일링**: Karpenter가 인스턴스 프로비저닝에 1-2분 소요
4. **로그 수집**: Job TTL 이전에 로그 수집 필요
