#!/bin/bash
# Benchmark 결과에서 메트릭 추출 및 JSON 저장

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/../results"
METRICS_DIR="${RESULTS_DIR}/metrics"
LOGS_DIR="${RESULTS_DIR}/logs"

mkdir -p "${METRICS_DIR}" "${LOGS_DIR}"

# Sysbench CPU 결과 파싱
parse_sysbench_cpu() {
    local log_content="$1"

    local events_per_sec=$(echo "$log_content" | grep "events per second:" | tail -1 | awk '{print $NF}')
    local latency_avg=$(echo "$log_content" | grep -A5 "Latency (ms):" | grep "avg:" | tail -1 | awk '{print $2}')
    local latency_p95=$(echo "$log_content" | grep -A5 "Latency (ms):" | grep "95th" | tail -1 | awk '{print $3}')

    echo "{\"cpu_events_per_sec\": ${events_per_sec:-0}, \"cpu_latency_avg_ms\": ${latency_avg:-0}, \"cpu_latency_p95_ms\": ${latency_p95:-0}}"
}

# Redis 결과 파싱
parse_redis() {
    local log_content="$1"

    # Standard benchmark 결과 (첫 번째)
    local set_ops=$(echo "$log_content" | grep -E "^SET:" | head -1 | awk '{print $2}')
    local get_ops=$(echo "$log_content" | grep -E "^GET:" | head -1 | awk '{print $2}')

    # Pipeline 결과
    local pipeline_set=$(echo "$log_content" | grep -A20 "Pipeline Benchmark" | grep -E "^SET:" | head -1 | awk '{print $2}')

    echo "{\"set_ops_per_sec\": ${set_ops:-0}, \"get_ops_per_sec\": ${get_ops:-0}, \"pipeline_ops_per_sec\": ${pipeline_set:-0}}"
}

# Nginx/wrk 결과 파싱
parse_nginx() {
    local log_content="$1"

    # 100 connections 결과
    local requests_sec=$(echo "$log_content" | grep -A15 "100 connections" | grep "Requests/sec:" | head -1 | awk '{print $2}')
    local latency_avg=$(echo "$log_content" | grep -A15 "100 connections" | grep "Latency" | head -1 | awk '{print $2}' | sed 's/ms//;s/us/*0.001/' | bc -l 2>/dev/null || echo "0")
    local transfer=$(echo "$log_content" | grep -A15 "100 connections" | grep "Transfer/sec:" | head -1 | awk '{print $2}' | sed 's/MB//;s/KB/*0.001/' | bc -l 2>/dev/null || echo "0")

    # Latency distribution에서 99%
    local latency_p99=$(echo "$log_content" | grep -A15 "100 connections" | grep "99%" | head -1 | awk '{print $2}' | sed 's/ms//;s/s/*1000/' | bc -l 2>/dev/null || echo "0")

    echo "{\"requests_per_sec\": ${requests_sec:-0}, \"latency_avg_ms\": ${latency_avg:-0}, \"latency_p99_ms\": ${latency_p99:-0}, \"transfer_mb_sec\": ${transfer:-0}}"
}

# Pod 리스트에서 카운트 추출
parse_pod_count() {
    local log_content="$1"

    local total=$(echo "$log_content" | grep -A100 "All Pods on Node" | grep -E "^\w" | grep -v "NAMESPACE" | grep -v "=====" | wc -l)
    local daemonset=$(echo "$log_content" | grep -A100 "All Pods on Node" | grep -E "kube-system|amazon|aws" | wc -l)

    echo "{\"pod_count_total\": ${total:-0}, \"pod_count_daemonset\": ${daemonset:-0}}"
}

# 단일 결과 파일에서 메트릭 추출
extract_metrics_from_file() {
    local log_file="$1"
    local instance_type=$(basename "$log_file" | sed 's/-[0-9]*-[0-9]*\.log$//' | tr '-' '.')
    local timestamp=$(basename "$log_file" | grep -oP '\d{8}-\d{6}' || date +%Y%m%d-%H%M%S)

    local log_content=$(cat "$log_file")

    # 각 섹션 파싱
    local cpu_section=$(echo "$log_content" | sed -n '/Sysbench CPU Results/,/=====/p')
    local redis_section=$(echo "$log_content" | sed -n '/Redis Benchmark Results/,/=====/p')
    local nginx_section=$(echo "$log_content" | sed -n '/Nginx Benchmark Results/,/=====/p')

    local cpu_metrics=$(parse_sysbench_cpu "$cpu_section")
    local redis_metrics=$(parse_redis "$redis_section")
    local nginx_metrics=$(parse_nginx "$nginx_section")
    local pod_metrics=$(parse_pod_count "$log_content")

    # JSON 병합
    cat << EOF
{
  "instance_type": "${instance_type}",
  "timestamp": "${timestamp}",
  "system": ${cpu_metrics},
  "redis": ${redis_metrics},
  "nginx": ${nginx_metrics},
  "node": ${pod_metrics}
}
EOF
}

# 모든 결과 파일 처리
process_all_results() {
    echo "📊 Parsing benchmark metrics..."

    for log_file in "${RESULTS_DIR}/all"/*.log; do
        [[ -f "$log_file" ]] || continue

        local instance_safe=$(basename "$log_file" | sed 's/-[0-9]*-[0-9]*\.log$//')
        local metrics_file="${METRICS_DIR}/${instance_safe}.json"

        echo "  Processing: $(basename "$log_file")"
        extract_metrics_from_file "$log_file" > "$metrics_file"

        # 로그 파일 이동
        mv "$log_file" "${LOGS_DIR}/" 2>/dev/null || true
    done

    echo "✅ Metrics saved to: ${METRICS_DIR}"
}

# CSV 요약 테이블 생성
generate_csv_summary() {
    local csv_file="${RESULTS_DIR}/summary/metrics-summary.csv"

    echo "📋 Generating CSV summary..."

    # 헤더
    echo "instance_type,cpu_events_sec,cpu_latency_avg_ms,redis_set_ops,redis_get_ops,nginx_req_sec,nginx_latency_p99_ms,pod_total,pod_daemonset" > "$csv_file"

    for metrics_file in "${METRICS_DIR}"/*.json; do
        [[ -f "$metrics_file" ]] || continue

        local instance=$(jq -r '.instance_type' "$metrics_file")
        local cpu_events=$(jq -r '.system.cpu_events_per_sec // 0' "$metrics_file")
        local cpu_latency=$(jq -r '.system.cpu_latency_avg_ms // 0' "$metrics_file")
        local redis_set=$(jq -r '.redis.set_ops_per_sec // 0' "$metrics_file")
        local redis_get=$(jq -r '.redis.get_ops_per_sec // 0' "$metrics_file")
        local nginx_req=$(jq -r '.nginx.requests_per_sec // 0' "$metrics_file")
        local nginx_lat=$(jq -r '.nginx.latency_p99_ms // 0' "$metrics_file")
        local pod_total=$(jq -r '.node.pod_count_total // 0' "$metrics_file")
        local pod_ds=$(jq -r '.node.pod_count_daemonset // 0' "$metrics_file")

        echo "${instance},${cpu_events},${cpu_latency},${redis_set},${redis_get},${nginx_req},${nginx_lat},${pod_total},${pod_ds}" >> "$csv_file"
    done

    echo "✅ CSV saved to: ${csv_file}"
}

# 메인
main() {
    mkdir -p "${RESULTS_DIR}/summary"

    case "${1:-all}" in
        parse)
            process_all_results
            ;;
        csv)
            generate_csv_summary
            ;;
        all|*)
            process_all_results
            generate_csv_summary
            ;;
    esac
}

main "$@"
