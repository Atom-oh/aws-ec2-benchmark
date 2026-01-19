#!/bin/bash
# 전체 벤치마크 실행 스크립트 (5회 반복)
# Usage: ./run-all-benchmarks.sh [sysbench|nginx|redis|elasticsearch|all]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BASE_DIR/results"
CONFIG_FILE="$BASE_DIR/config/instances-4vcpu.txt"

# 반복 횟수
ITERATIONS=5

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_iter() { echo -e "${CYAN}[ITER]${NC} $1"; }

# 인스턴스 목록 로드
load_instances() {
    grep -v "^#" "$CONFIG_FILE" | grep -v "^$" | awk '{print $1}'
}

load_x86_instances() {
    grep -v "^#" "$CONFIG_FILE" | grep "x86_64" | awk '{print $1}'
}

load_arm64_instances() {
    grep -v "^#" "$CONFIG_FILE" | grep "arm64" | awk '{print $1}'
}

# Job 완료 대기
wait_for_job() {
    local job_name=$1
    local timeout=${2:-600}
    log_info "Waiting for job: $job_name (timeout: ${timeout}s)"
    kubectl wait --for=condition=complete "job/$job_name" -n benchmark --timeout="${timeout}s" 2>/dev/null || \
    kubectl wait --for=condition=failed "job/$job_name" -n benchmark --timeout="${timeout}s" 2>/dev/null || true
}

# 로그 수집
collect_log() {
    local job_name=$1
    local output_file=$2
    kubectl logs "job/$job_name" -n benchmark > "$output_file" 2>/dev/null || true
}

# ===================
# SYSBENCH CPU (5회 반복)
# ===================
run_sysbench() {
    local instance=$1
    local iteration=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local job_name="sysbench-cpu-$safe_name-run$iteration"
    local output_dir="$RESULTS_DIR/sysbench/$instance"

    log_iter "Sysbench $instance - Run $iteration/$ITERATIONS"

    mkdir -p "$output_dir"

    # 이미 완료된 경우 스킵
    if [[ -f "$output_dir/run$iteration.log" ]] && [[ -s "$output_dir/run$iteration.log" ]]; then
        log_warn "Skipping $instance run$iteration - already done"
        return 0
    fi

    # Job 생성 (이름에 iteration 포함)
    sed -e "s/\${INSTANCE_TYPE}/$instance/g" \
        -e "s/sysbench-cpu-\${INSTANCE_TYPE\\/\\/.\\/-}/sysbench-cpu-$safe_name-run$iteration/g" \
        "$BASE_DIR/benchmarks/system/sysbench-cpu.yaml" | kubectl apply -f -

    wait_for_job "$job_name" 600
    collect_log "$job_name" "$output_dir/run$iteration.log"
    kubectl delete job "$job_name" -n benchmark --ignore-not-found=true

    log_info "Completed sysbench $instance run $iteration"
}

run_all_sysbench() {
    log_info "=== Starting Sysbench CPU Benchmark ($ITERATIONS iterations) ==="
    local instances=($(load_instances))
    local total=${#instances[@]}
    local count=0

    for instance in "${instances[@]}"; do
        ((count++))
        log_info "[$count/$total] $instance"
        for iter in $(seq 1 $ITERATIONS); do
            run_sysbench "$instance" "$iter"
            sleep 3
        done
        sleep 5
    done

    log_info "=== Sysbench CPU Complete ==="
}

# ===================
# NGINX (5회 반복)
# ===================
run_nginx() {
    local instance=$1
    local iteration=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local server_name="nginx-server-$safe_name"
    local benchmark_name="nginx-benchmark-$safe_name-run$iteration"
    local output_dir="$RESULTS_DIR/nginx/$instance"

    log_iter "Nginx $instance - Run $iteration/$ITERATIONS"

    mkdir -p "$output_dir"

    if [[ -f "$output_dir/run$iteration.log" ]] && [[ -s "$output_dir/run$iteration.log" ]]; then
        log_warn "Skipping $instance run$iteration - already done"
        return 0
    fi

    # 서버가 없으면 배포
    if ! kubectl get deployment "$server_name" -n benchmark &>/dev/null; then
        kubectl apply -f "$BASE_DIR/benchmarks/nginx/nginx-server.yaml" 2>/dev/null | head -1 || true
        sed -e "s/\${INSTANCE_TYPE}/$instance/g" \
            "$BASE_DIR/benchmarks/nginx/nginx-server.yaml" | kubectl apply -f -
        sleep 30
        kubectl wait --for=condition=available "deployment/$server_name" -n benchmark --timeout=300s || true
        sleep 10
    fi

    # 벤치마크 실행
    sed -e "s/\${INSTANCE_TYPE}/$instance/g" \
        -e "s/nginx-benchmark-\${INSTANCE_TYPE\\/\\/.\\/-}/nginx-benchmark-$safe_name-run$iteration/g" \
        "$BASE_DIR/benchmarks/nginx/nginx-benchmark.yaml" | kubectl apply -f -

    wait_for_job "$benchmark_name" 300
    collect_log "$benchmark_name" "$output_dir/run$iteration.log"
    kubectl delete job "$benchmark_name" -n benchmark --ignore-not-found=true

    log_info "Completed nginx $instance run $iteration"
}

cleanup_nginx_server() {
    local instance=$1
    local safe_name=$(echo "$instance" | tr '.' '-')
    kubectl delete deployment "nginx-server-$safe_name" -n benchmark --ignore-not-found=true
    kubectl delete service "nginx-server-$safe_name" -n benchmark --ignore-not-found=true
}

run_all_nginx() {
    log_info "=== Starting Nginx Benchmark ($ITERATIONS iterations) ==="
    local instances=($(load_instances))
    local total=${#instances[@]}
    local count=0

    for instance in "${instances[@]}"; do
        ((count++))
        log_info "[$count/$total] $instance"

        for iter in $(seq 1 $ITERATIONS); do
            run_nginx "$instance" "$iter"
            sleep 5
        done

        # 모든 iteration 완료 후 서버 정리
        cleanup_nginx_server "$instance"
        sleep 10
    done

    log_info "=== Nginx Benchmark Complete ==="
}

# ===================
# REDIS (5회 반복)
# ===================
run_redis() {
    local instance=$1
    local iteration=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local server_name="redis-server-$safe_name"
    local benchmark_name="redis-benchmark-$safe_name-run$iteration"
    local output_dir="$RESULTS_DIR/redis/$instance"

    log_iter "Redis $instance - Run $iteration/$ITERATIONS"

    mkdir -p "$output_dir"

    if [[ -f "$output_dir/run$iteration.log" ]] && [[ -s "$output_dir/run$iteration.log" ]]; then
        log_warn "Skipping $instance run$iteration - already done"
        return 0
    fi

    # 서버가 없으면 배포
    if ! kubectl get deployment "$server_name" -n benchmark &>/dev/null; then
        sed -e "s/\${INSTANCE_TYPE}/$instance/g" \
            "$BASE_DIR/benchmarks/redis/redis-server.yaml" | kubectl apply -f -
        sleep 30
        kubectl wait --for=condition=available "deployment/$server_name" -n benchmark --timeout=300s || true
        sleep 10
    fi

    # 벤치마크 실행
    sed -e "s/\${INSTANCE_TYPE}/$instance/g" \
        -e "s/redis-benchmark-\${INSTANCE_TYPE\\/\\/.\\/-}/redis-benchmark-$safe_name-run$iteration/g" \
        "$BASE_DIR/benchmarks/redis/redis-benchmark.yaml" | kubectl apply -f -

    wait_for_job "$benchmark_name" 600
    collect_log "$benchmark_name" "$output_dir/run$iteration.log"
    kubectl delete job "$benchmark_name" -n benchmark --ignore-not-found=true

    log_info "Completed redis $instance run $iteration"
}

cleanup_redis_server() {
    local instance=$1
    local safe_name=$(echo "$instance" | tr '.' '-')
    kubectl delete deployment "redis-server-$safe_name" -n benchmark --ignore-not-found=true
    kubectl delete service "redis-server-$safe_name" -n benchmark --ignore-not-found=true
}

run_all_redis() {
    log_info "=== Starting Redis Benchmark ($ITERATIONS iterations) ==="
    local instances=($(load_instances))
    local total=${#instances[@]}
    local count=0

    for instance in "${instances[@]}"; do
        ((count++))
        log_info "[$count/$total] $instance"

        for iter in $(seq 1 $ITERATIONS); do
            run_redis "$instance" "$iter"
            sleep 5
        done

        cleanup_redis_server "$instance"
        sleep 10
    done

    log_info "=== Redis Benchmark Complete ==="
}

# ===================
# ELASTICSEARCH (5회 반복)
# ===================
run_elasticsearch() {
    local instance=$1
    local arch=$2
    local iteration=$3
    local safe_name=$(echo "$instance" | tr '.' '-')
    local job_name="es-coldstart-$safe_name-run$iteration"
    local output_dir="$RESULTS_DIR/elasticsearch/$instance"

    log_iter "Elasticsearch $instance ($arch) - Run $iteration/$ITERATIONS"

    mkdir -p "$output_dir"

    if [[ -f "$output_dir/run$iteration.log" ]] && [[ -s "$output_dir/run$iteration.log" ]]; then
        log_warn "Skipping $instance run$iteration - already done"
        return 0
    fi

    # Job 생성
    sed -e "s/INSTANCE_SAFE/$safe_name/g" \
        -e "s/INSTANCE_TYPE/$instance/g" \
        -e "s/ARCH/$arch/g" \
        -e "s/es-coldstart-INSTANCE_SAFE/es-coldstart-$safe_name-run$iteration/g" \
        "$BASE_DIR/benchmarks/elasticsearch/elasticsearch-coldstart.yaml" | kubectl apply -f -

    wait_for_job "$job_name" 900
    collect_log "$job_name" "$output_dir/run$iteration.log"
    kubectl delete job "$job_name" -n benchmark --ignore-not-found=true

    log_info "Completed elasticsearch $instance run $iteration"
}

run_all_elasticsearch() {
    log_info "=== Starting Elasticsearch Benchmark ($ITERATIONS iterations) ==="

    local x86_instances=($(load_x86_instances))
    local arm64_instances=($(load_arm64_instances))
    local total=$((${#x86_instances[@]} + ${#arm64_instances[@]}))
    local count=0

    for instance in "${x86_instances[@]}"; do
        ((count++))
        log_info "[$count/$total] $instance (amd64)"
        for iter in $(seq 1 $ITERATIONS); do
            run_elasticsearch "$instance" "amd64" "$iter"
            sleep 5
        done
        sleep 10
    done

    for instance in "${arm64_instances[@]}"; do
        ((count++))
        log_info "[$count/$total] $instance (arm64)"
        for iter in $(seq 1 $ITERATIONS); do
            run_elasticsearch "$instance" "arm64" "$iter"
            sleep 5
        done
        sleep 10
    done

    log_info "=== Elasticsearch Benchmark Complete ==="
}

# ===================
# MAIN
# ===================
case "${1:-all}" in
    sysbench)
        run_all_sysbench
        ;;
    nginx)
        run_all_nginx
        ;;
    redis)
        run_all_redis
        ;;
    elasticsearch)
        run_all_elasticsearch
        ;;
    all)
        run_all_sysbench
        run_all_nginx
        run_all_redis
        run_all_elasticsearch
        ;;
    *)
        echo "Usage: $0 [sysbench|nginx|redis|elasticsearch|all]"
        exit 1
        ;;
esac

log_info "All benchmarks completed!"
log_info "Run: ./scripts/parse-results.sh to generate CSV summaries"
