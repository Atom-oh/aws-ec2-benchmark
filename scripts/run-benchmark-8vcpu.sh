#!/bin/bash
# EKS EC2 Node Benchmark Runner - 8 vCPU (2xlarge)
# 51개 인스턴스 순차 테스트 + 즉시 삭제로 비용 최소화

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="benchmark"
RESULTS_DIR="${SCRIPT_DIR}/../results"
BENCHMARK_DIR="${SCRIPT_DIR}/../benchmarks"
CONFIG_FILE="${SCRIPT_DIR}/../config/instances-8vcpu.txt"

# 인스턴스 목록 로드 (주석 제외)
load_instances() {
    local filter="${1:-all}"  # all, x86_64, arm64, gen8, gen7, c, m, r

    grep -v "^#" "$CONFIG_FILE" | grep -v "^$" | while read -r line; do
        instance=$(echo "$line" | awk '{print $1}')
        arch=$(echo "$line" | awk '{print $2}')

        case $filter in
            x86_64|arm64) [[ "$arch" == "$filter" ]] && echo "$instance" ;;
            gen8) [[ "$instance" =~ [cmr]8 ]] && echo "$instance" ;;
            gen7) [[ "$instance" =~ [cmr]7 ]] && echo "$instance" ;;
            gen6) [[ "$instance" =~ [cmr]6 ]] && echo "$instance" ;;
            gen5) [[ "$instance" =~ [cmr]5 ]] && echo "$instance" ;;
            c) [[ "$instance" =~ ^c ]] && echo "$instance" ;;
            m) [[ "$instance" =~ ^m ]] && echo "$instance" ;;
            r) [[ "$instance" =~ ^r ]] && echo "$instance" ;;
            *) echo "$instance" ;;
        esac
    done
}

log_info() { echo -e "\033[0;34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[0;32m[SUCCESS]\033[0m $1"; }
log_error() { echo -e "\033[0;31m[ERROR]\033[0m $1"; }

# 노드의 모든 Pod 리스트 기록 (DaemonSet 포함)
record_node_pods() {
    local node_name=$1
    local output_file=$2

    echo "===== All Pods on Node: ${node_name} =====" >> "$output_file"
    echo "Timestamp: $(date -Iseconds)" >> "$output_file"
    kubectl get pods -A -o wide --field-selector spec.nodeName=${node_name} >> "$output_file" 2>&1 || true
    echo "" >> "$output_file"
}

# 노드에 벤치마크 Pod만 있는지 확인 (DaemonSet 제외)
wait_for_node_clean() {
    local instance_type=$1
    local max_wait=60
    local waited=0

    while [[ $waited -lt $max_wait ]]; do
        # benchmark namespace의 Running Pod 수 확인
        local pod_count=$(kubectl get pods -n ${NAMESPACE} --field-selector status.phase=Running -o name 2>/dev/null | wc -l)
        if [[ $pod_count -eq 0 ]]; then
            return 0
        fi
        log_info "Waiting for previous pods to terminate... ($pod_count running)"
        sleep 5
        waited=$((waited + 5))
    done
    log_error "Timeout waiting for pods to terminate"
}

# 단일 인스턴스 테스트 및 즉시 삭제
run_single_instance_test() {
    local instance_type=$1
    local instance_safe=$(echo $instance_type | tr '.' '-')
    local timestamp=$(date +%Y%m%d-%H%M%S)
    local result_file="${RESULTS_DIR}/all/${instance_safe}-${timestamp}.log"

    log_info "========== Testing: ${instance_type} =========="

    export INSTANCE_TYPE="${instance_type}"
    mkdir -p "${RESULTS_DIR}/all"

    # 이전 Pod 정리 대기
    wait_for_node_clean "${instance_type}"

    # 결과 파일 헤더
    echo "===== Benchmark Results: ${instance_type} =====" > "$result_file"
    echo "Timestamp: ${timestamp}" >> "$result_file"
    echo "" >> "$result_file"

    # 1. System Benchmark (단독 실행)
    log_info "Running sysbench CPU..."
    envsubst < "${BENCHMARK_DIR}/system/sysbench-cpu.yaml" | kubectl apply -f -
    kubectl wait --for=condition=complete -n ${NAMESPACE} job/sysbench-cpu-${instance_safe} --timeout=300s 2>/dev/null || true

    # 노드 이름 획득 및 Pod 리스트 기록
    local node_name=$(kubectl get pods -n ${NAMESPACE} -l benchmark=sysbench -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null || true)
    if [[ -n "$node_name" ]]; then
        record_node_pods "$node_name" "$result_file"
    fi

    echo "===== Sysbench CPU Results =====" >> "$result_file"
    kubectl logs -n ${NAMESPACE} job/sysbench-cpu-${instance_safe} >> "$result_file" 2>&1 || true
    kubectl delete -n ${NAMESPACE} job/sysbench-cpu-${instance_safe} --ignore-not-found --wait=true
    sleep 3  # Pod 완전 삭제 대기

    # 2. Redis Benchmark (Server + Client 순차)
    log_info "Running Redis benchmark..."
    envsubst < "${BENCHMARK_DIR}/redis/redis-server.yaml" | kubectl apply -f -
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/redis-server-${instance_safe} --timeout=180s 2>/dev/null || true
    sleep 2  # 서버 안정화

    envsubst < "${BENCHMARK_DIR}/redis/redis-benchmark.yaml" | kubectl apply -f -
    kubectl wait --for=condition=complete -n ${NAMESPACE} job/redis-benchmark-${instance_safe} --timeout=300s 2>/dev/null || true

    echo "===== Redis Benchmark Results =====" >> "$result_file"
    kubectl logs -n ${NAMESPACE} job/redis-benchmark-${instance_safe} >> "$result_file" 2>&1 || true
    kubectl delete -n ${NAMESPACE} deployment/redis-server-${instance_safe} job/redis-benchmark-${instance_safe} service/redis-server-${instance_safe} --ignore-not-found --wait=true
    sleep 3

    # 3. Nginx Benchmark (Server + Client 순차)
    log_info "Running Nginx benchmark..."
    envsubst < "${BENCHMARK_DIR}/nginx/nginx-server.yaml" | kubectl apply -f -
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/nginx-server-${instance_safe} --timeout=180s 2>/dev/null || true
    sleep 2

    envsubst < "${BENCHMARK_DIR}/nginx/nginx-benchmark.yaml" | kubectl apply -f -
    kubectl wait --for=condition=complete -n ${NAMESPACE} job/nginx-benchmark-${instance_safe} --timeout=300s 2>/dev/null || true

    echo "===== Nginx Benchmark Results =====" >> "$result_file"
    kubectl logs -n ${NAMESPACE} job/nginx-benchmark-${instance_safe} >> "$result_file" 2>&1 || true
    kubectl delete -n ${NAMESPACE} deployment/nginx-server-${instance_safe} job/nginx-benchmark-${instance_safe} service/nginx-server-${instance_safe} --ignore-not-found --wait=true
    sleep 3

    # 4. 노드 삭제 전 최종 Pod 리스트 기록
    if [[ -n "$node_name" ]]; then
        echo "===== Final Pod List Before Cleanup =====" >> "$result_file"
        record_node_pods "$node_name" "$result_file"
    fi

    # 5. 노드 삭제
    log_info "Cleaning up node for ${instance_type}..."
    kubectl delete node -l node.kubernetes.io/instance-type=${instance_type} --ignore-not-found 2>/dev/null || true

    log_success "Completed: ${instance_type} -> ${result_file}"
    echo ""
}

# 사용법
usage() {
    echo "Usage: $0 [FILTER] [OPTIONS]"
    echo ""
    echo "Filters:"
    echo "  all      - All 51 instances (default)"
    echo "  gen8     - 8th generation only (7 instances)"
    echo "  gen7     - 7th generation only"
    echo "  gen6     - 6th generation only"
    echo "  x86_64   - Intel/AMD only (34 instances)"
    echo "  arm64    - Graviton only (17 instances)"
    echo "  c        - Compute optimized only"
    echo "  m        - General purpose only"
    echo "  r        - Memory optimized only"
    echo ""
    echo "Options:"
    echo "  -i INSTANCE  - Test single instance (e.g., -i c8i.2xlarge)"
    echo "  -l           - List instances for filter"
    echo ""
    echo "Examples:"
    echo "  $0 gen8              # Test 8th gen instances"
    echo "  $0 arm64             # Test Graviton instances"
    echo "  $0 -i c8i.2xlarge    # Test single instance"
}

# 메인
main() {
    local filter="all"
    local single_instance=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            -i) single_instance="$2"; shift 2 ;;
            -l) load_instances "${2:-all}"; exit 0 ;;
            -h|--help) usage; exit 0 ;;
            *) filter="$1"; shift ;;
        esac
    done

    kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

    # ConfigMaps 적용
    kubectl apply -f "${BENCHMARK_DIR}/nginx/nginx-server.yaml" -n ${NAMESPACE} 2>/dev/null || true

    if [[ -n "$single_instance" ]]; then
        run_single_instance_test "$single_instance"
    else
        mapfile -t instances < <(load_instances "$filter")
        log_info "Testing ${#instances[@]} instance types (filter: $filter)"

        for instance in "${instances[@]}"; do
            run_single_instance_test "$instance"
            sleep 10  # 노드 정리 대기
        done
    fi

    log_success "All benchmarks completed! Results in: ${RESULTS_DIR}/all"
}

main "$@"
