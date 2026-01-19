#!/bin/bash
# Notion용 Markdown 리포트 생성 (메트릭 기반)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/../results"
METRICS_DIR="${RESULTS_DIR}/metrics"
OUTPUT_FILE="${RESULTS_DIR}/summary/notion-report.md"

mkdir -p "${RESULTS_DIR}/summary"

generate_report() {
    cat > "${OUTPUT_FILE}" << 'HEADER'
# EKS EC2 Node Benchmark Report

## 📋 테스트 개요

| 항목 | 내용 |
|------|------|
| **테스트 환경** | Amazon EKS with Karpenter |
| **노드 사이즈** | 8 vCPU (2xlarge) |
| **리소스 제한** | Pod limit 없음 (노드 전체 사용) |
| **테스트 일시** | {{DATE}} |

---

## 📊 벤치마크 결과 요약

### CPU 성능 (sysbench)

| Instance Type | Events/sec ⬆️ | Latency Avg (ms) ⬇️ | Latency P95 (ms) ⬇️ |
|---------------|---------------|---------------------|---------------------|
HEADER

    # CPU 메트릭 테이블
    for f in "${METRICS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local instance=$(jq -r '.instance_type' "$f")
        local events=$(jq -r '.system.cpu_events_per_sec // "-"' "$f")
        local lat_avg=$(jq -r '.system.cpu_latency_avg_ms // "-"' "$f")
        local lat_p95=$(jq -r '.system.cpu_latency_p95_ms // "-"' "$f")
        echo "| ${instance} | ${events} | ${lat_avg} | ${lat_p95} |" >> "${OUTPUT_FILE}"
    done

    cat >> "${OUTPUT_FILE}" << 'REDIS_HEADER'

### Redis 성능

| Instance Type | SET ops/sec ⬆️ | GET ops/sec ⬆️ | Pipeline ops/sec ⬆️ |
|---------------|----------------|----------------|---------------------|
REDIS_HEADER

    # Redis 메트릭 테이블
    for f in "${METRICS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local instance=$(jq -r '.instance_type' "$f")
        local set_ops=$(jq -r '.redis.set_ops_per_sec // "-"' "$f")
        local get_ops=$(jq -r '.redis.get_ops_per_sec // "-"' "$f")
        local pipe_ops=$(jq -r '.redis.pipeline_ops_per_sec // "-"' "$f")
        echo "| ${instance} | ${set_ops} | ${get_ops} | ${pipe_ops} |" >> "${OUTPUT_FILE}"
    done

    cat >> "${OUTPUT_FILE}" << 'NGINX_HEADER'

### Nginx 성능 (wrk)

| Instance Type | Requests/sec ⬆️ | Latency Avg (ms) ⬇️ | Latency P99 (ms) ⬇️ | Transfer (MB/s) ⬆️ |
|---------------|-----------------|---------------------|---------------------|-------------------|
NGINX_HEADER

    # Nginx 메트릭 테이블
    for f in "${METRICS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local instance=$(jq -r '.instance_type' "$f")
        local req_sec=$(jq -r '.nginx.requests_per_sec // "-"' "$f")
        local lat_avg=$(jq -r '.nginx.latency_avg_ms // "-"' "$f")
        local lat_p99=$(jq -r '.nginx.latency_p99_ms // "-"' "$f")
        local transfer=$(jq -r '.nginx.transfer_mb_sec // "-"' "$f")
        echo "| ${instance} | ${req_sec} | ${lat_avg} | ${lat_p99} | ${transfer} |" >> "${OUTPUT_FILE}"
    done

    cat >> "${OUTPUT_FILE}" << 'NODE_HEADER'

### 노드 정보

| Instance Type | Total Pods | DaemonSet Pods |
|---------------|------------|----------------|
NODE_HEADER

    # 노드 정보 테이블
    for f in "${METRICS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local instance=$(jq -r '.instance_type' "$f")
        local pod_total=$(jq -r '.node.pod_count_total // "-"' "$f")
        local pod_ds=$(jq -r '.node.pod_count_daemonset // "-"' "$f")
        echo "| ${instance} | ${pod_total} | ${pod_ds} |" >> "${OUTPUT_FILE}"
    done

    cat >> "${OUTPUT_FILE}" << 'FOOTER'

---

## 📈 메트릭 설명

| 지표 | 설명 | 좋은 방향 |
|------|------|----------|
| **Events/sec** | CPU 소수 계산 처리량 | ⬆️ 높을수록 좋음 |
| **Latency** | 연산/요청 지연시간 | ⬇️ 낮을수록 좋음 |
| **ops/sec** | 초당 명령 처리량 | ⬆️ 높을수록 좋음 |
| **Requests/sec** | HTTP 초당 요청 처리량 | ⬆️ 높을수록 좋음 |
| **Transfer** | 데이터 전송 속도 | ⬆️ 높을수록 좋음 |

---

## 🔧 테스트 환경 상세

### 사용된 벤치마크 도구
- **sysbench**: CPU prime number 계산 (20000 primes, 60초)
- **redis-benchmark**: SET/GET 100,000 ops, Pipeline 16
- **wrk**: HTTP 부하 테스트 (100 connections, 30초)

### 테스트 조건
- 각 인스턴스 타입별 독립 테스트 (노드 격리)
- DaemonSet 외 추가 Pod 없음 확인
- Warm-up 단계 포함

---

*Generated at {{DATE}}*
FOOTER

    # 날짜 치환
    sed -i "s/{{DATE}}/$(date '+%Y-%m-%d %H:%M:%S KST')/g" "${OUTPUT_FILE}"

    echo "✅ Notion report generated: ${OUTPUT_FILE}"
}

generate_report
