#!/bin/bash
# EKS EC2 Node Benchmark Runner
# 다양한 인스턴스 타입에 대해 순차적으로 벤치마크 실행

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 설정
NAMESPACE="benchmark"
RESULTS_DIR="$(dirname "$0")/../results"
BENCHMARK_DIR="$(dirname "$0")/../benchmarks"

# 테스트할 인스턴스 타입 목록 (2 vCPU / large 사이즈)
# TODO: 실제 테스트할 인스턴스 타입 선택
INSTANCE_TYPES=(
    # Intel 계열
    "c5.large"
    "c6i.large"
    "c7i.large"
    "m5.large"
    "m6i.large"
    "m7i.large"
    "r5.large"
    "r6i.large"
    "r7i.large"
    # AMD 계열
    "c5a.large"
    "c6a.large"
    "c7a.large"
    "m5a.large"
    "m6a.large"
    "m7a.large"
    # Graviton (ARM) 계열 - 별도 NodeClass 필요
    # "c6g.large"
    # "c7g.large"
)

# 벤치마크 타입
BENCHMARK_TYPES=("system" "redis" "nginx" "springboot")

# 로그 함수
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 사용법 출력
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -t, --type TYPE       Run specific benchmark type (system|redis|nginx|springboot|all)"
    echo "  -i, --instance TYPE   Run on specific instance type (e.g., c5.large)"
    echo "  -l, --list            List available instance types"
    echo "  -c, --cleanup         Cleanup all benchmark resources"
    echo "  -h, --help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 -t system -i c5.large    Run system benchmark on c5.large"
    echo "  $0 -t all -i c6i.large      Run all benchmarks on c6i.large"
    echo "  $0 -t redis                  Run redis benchmark on all instance types"
}

# Namespace 생성
create_namespace() {
    log_info "Creating namespace: ${NAMESPACE}"
    kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -
}

# 특정 인스턴스 타입에서 벤치마크 실행
run_benchmark_on_instance() {
    local instance_type=$1
    local benchmark_type=$2
    local instance_safe=$(echo $instance_type | tr '.' '-')
    local timestamp=$(date +%Y%m%d-%H%M%S)
    local result_file="${RESULTS_DIR}/${benchmark_type}/${instance_safe}-${timestamp}.log"

    mkdir -p "${RESULTS_DIR}/${benchmark_type}"

    log_info "Running ${benchmark_type} benchmark on ${instance_type}"

    # 환경 변수 설정 및 manifest 적용
    export INSTANCE_TYPE="${instance_type}"

    case ${benchmark_type} in
        "system")
            # Sysbench CPU
            envsubst < "${BENCHMARK_DIR}/system/sysbench-cpu.yaml" | kubectl apply -f -
            wait_for_job "sysbench-cpu-${instance_safe}"
            kubectl logs -n ${NAMESPACE} job/sysbench-cpu-${instance_safe} > "${result_file}.cpu" 2>&1 || true

            # Sysbench Memory
            envsubst < "${BENCHMARK_DIR}/system/sysbench-memory.yaml" | kubectl apply -f -
            wait_for_job "sysbench-memory-${instance_safe}"
            kubectl logs -n ${NAMESPACE} job/sysbench-memory-${instance_safe} > "${result_file}.memory" 2>&1 || true

            # stress-ng
            envsubst < "${BENCHMARK_DIR}/system/stress-ng.yaml" | kubectl apply -f -
            wait_for_job "stress-ng-${instance_safe}"
            kubectl logs -n ${NAMESPACE} job/stress-ng-${instance_safe} > "${result_file}.stress-ng" 2>&1 || true
            ;;

        "redis")
            # Redis 서버 배포
            envsubst < "${BENCHMARK_DIR}/redis/redis-server.yaml" | kubectl apply -f -
            wait_for_deployment "redis-server-${instance_safe}"

            # Redis 벤치마크 실행
            envsubst < "${BENCHMARK_DIR}/redis/redis-benchmark.yaml" | kubectl apply -f -
            wait_for_job "redis-benchmark-${instance_safe}"
            kubectl logs -n ${NAMESPACE} job/redis-benchmark-${instance_safe} > "${result_file}" 2>&1 || true

            # 정리
            kubectl delete -n ${NAMESPACE} deployment/redis-server-${instance_safe} --ignore-not-found
            kubectl delete -n ${NAMESPACE} service/redis-server-${instance_safe} --ignore-not-found
            ;;

        "nginx")
            # Nginx 서버 배포
            envsubst < "${BENCHMARK_DIR}/nginx/nginx-server.yaml" | kubectl apply -f -
            wait_for_deployment "nginx-server-${instance_safe}"

            # Nginx 벤치마크 실행
            envsubst < "${BENCHMARK_DIR}/nginx/nginx-benchmark.yaml" | kubectl apply -f -
            wait_for_job "nginx-benchmark-${instance_safe}"
            kubectl logs -n ${NAMESPACE} job/nginx-benchmark-${instance_safe} > "${result_file}" 2>&1 || true

            # 정리
            kubectl delete -n ${NAMESPACE} deployment/nginx-server-${instance_safe} --ignore-not-found
            kubectl delete -n ${NAMESPACE} service/nginx-server-${instance_safe} --ignore-not-found
            ;;

        "springboot")
            # Spring Boot 서버 배포
            envsubst < "${BENCHMARK_DIR}/springboot/springboot-server.yaml" | kubectl apply -f -

            # Startup time 측정
            envsubst < "${BENCHMARK_DIR}/springboot/springboot-benchmark.yaml" | kubectl apply -f -

            # JVM startup 측정 먼저
            wait_for_job "springboot-startup-${instance_safe}"
            kubectl logs -n ${NAMESPACE} job/springboot-startup-${instance_safe} > "${result_file}.startup" 2>&1 || true

            # Spring Boot 서버가 준비될 때까지 대기
            wait_for_deployment "springboot-server-${instance_safe}"

            # throughput 벤치마크
            wait_for_job "springboot-benchmark-${instance_safe}"
            kubectl logs -n ${NAMESPACE} job/springboot-benchmark-${instance_safe} > "${result_file}.throughput" 2>&1 || true

            # 정리
            kubectl delete -n ${NAMESPACE} deployment/springboot-server-${instance_safe} --ignore-not-found
            kubectl delete -n ${NAMESPACE} service/springboot-server-${instance_safe} --ignore-not-found
            ;;
    esac

    log_success "Benchmark ${benchmark_type} on ${instance_type} completed"
}

# Job 완료 대기
wait_for_job() {
    local job_name=$1
    local timeout=600  # 10분 타임아웃

    log_info "Waiting for job ${job_name} to complete..."
    kubectl wait --for=condition=complete -n ${NAMESPACE} job/${job_name} --timeout=${timeout}s || {
        log_warn "Job ${job_name} may have failed or timed out"
        kubectl describe job/${job_name} -n ${NAMESPACE} || true
    }
}

# Deployment Ready 대기
wait_for_deployment() {
    local deployment_name=$1
    local timeout=300  # 5분 타임아웃

    log_info "Waiting for deployment ${deployment_name} to be ready..."
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/${deployment_name} --timeout=${timeout}s || {
        log_warn "Deployment ${deployment_name} may not be ready"
        kubectl describe deployment/${deployment_name} -n ${NAMESPACE} || true
    }
}

# 리소스 정리
cleanup() {
    log_info "Cleaning up benchmark resources..."
    kubectl delete namespace ${NAMESPACE} --ignore-not-found
    log_success "Cleanup completed"
}

# 메인 실행
main() {
    local benchmark_type="all"
    local target_instance=""

    # 인자 파싱
    while [[ $# -gt 0 ]]; do
        case $1 in
            -t|--type)
                benchmark_type="$2"
                shift 2
                ;;
            -i|--instance)
                target_instance="$2"
                shift 2
                ;;
            -l|--list)
                echo "Available instance types:"
                printf '%s\n' "${INSTANCE_TYPES[@]}"
                exit 0
                ;;
            -c|--cleanup)
                cleanup
                exit 0
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done

    # Namespace 생성
    create_namespace

    # ConfigMaps 적용 (Redis, Nginx 설정)
    log_info "Applying ConfigMaps..."
    kubectl apply -f "${BENCHMARK_DIR}/redis/redis-server.yaml" -n ${NAMESPACE} --dry-run=client -o yaml | grep -A100 "kind: ConfigMap" | kubectl apply -f - || true
    kubectl apply -f "${BENCHMARK_DIR}/nginx/nginx-server.yaml" -n ${NAMESPACE} --dry-run=client -o yaml | grep -A100 "kind: ConfigMap" | kubectl apply -f - || true

    # 인스턴스 타입 목록 결정
    local instances=("${INSTANCE_TYPES[@]}")
    if [[ -n "$target_instance" ]]; then
        instances=("$target_instance")
    fi

    # 벤치마크 타입 목록 결정
    local benchmarks=("${BENCHMARK_TYPES[@]}")
    if [[ "$benchmark_type" != "all" ]]; then
        benchmarks=("$benchmark_type")
    fi

    # 벤치마크 실행
    for instance in "${instances[@]}"; do
        log_info "========== Testing instance: ${instance} =========="

        for bench in "${benchmarks[@]}"; do
            run_benchmark_on_instance "$instance" "$bench"
        done

        log_success "========== Completed: ${instance} =========="
        echo ""
    done

    log_success "All benchmarks completed!"
    log_info "Results saved to: ${RESULTS_DIR}"
}

main "$@"
