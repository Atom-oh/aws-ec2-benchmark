# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EKS EC2 Node Benchmark - 다양한 EC2 인스턴스 타입(5세대~8세대, 51개)의 성능을 비교하는 Kubernetes 기반 벤치마크 프로젝트. Karpenter를 사용하여 노드를 동적 프로비저닝.

## 현재 상태 (2026-01-15)

### 변경사항
- **인스턴스 크기 변경**: 8 vCPU (2xlarge) → 4 vCPU (xlarge) - 비용 절감
- **Anti-affinity 적용**: 모든 템플릿에 `podAntiAffinity` 추가 - 노드 격리 보장
- **기존 결과 백업**: `results-backup-2xlarge/` (노드 격리 없이 실행되어 무효)

### 벤치마크 상태
| 벤치마크 | 완료 | 템플릿 |
|----------|------|--------|
| sysbench CPU | 0/51 | `benchmarks/system/sysbench-cpu.yaml` |
| Redis | 0/51 | `benchmarks/redis/redis-*.yaml` |
| Nginx (wrk) | 0/51 | `benchmarks/nginx/nginx-*.yaml` |
| Elasticsearch | 0/51 | `benchmarks/elasticsearch/elasticsearch-coldstart.yaml` |
| Spring Boot | 0/51 | `benchmarks/springboot/springboot-*.yaml` |

## 핵심 설계 원칙

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

## 벤치마크 실행 방법

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
│   │   ├── springboot-server.yaml      # Spring Boot 서버
│   │   ├── springboot-benchmark.yaml   # HTTP 벤치마크
│   │   └── springboot-coldstart.yaml   # Cold Start 측정
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

## 알려진 이슈

1. **memtier_benchmark**: x86 전용 → Graviton에서 redis-benchmark 사용
2. **Docker Hub Rate Limit**: ECR pull-through cache 사용
3. **Pod 로그 손실**: TTL 이전에 수집 필요
