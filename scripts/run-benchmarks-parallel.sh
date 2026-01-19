#!/bin/bash
# 51개 인스턴스 병렬 벤치마크 실행 스크립트
# Geekbench, Passmark, Spring Boot Cold Start

set -e

BENCHMARK_TYPE=${1:-all}  # all, geekbench, passmark, coldstart
RESULTS_DIR="/home/ec2-user/benchmark/results"

# 인스턴스 목록
INTEL_INSTANCES="c8i.xlarge c8i-flex.xlarge c7i.xlarge c7i-flex.xlarge c6i.xlarge c6id.xlarge c6in.xlarge c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge m8i.xlarge m7i.xlarge m7i-flex.xlarge m6i.xlarge m6id.xlarge m6in.xlarge m6idn.xlarge m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge r8i.xlarge r8i-flex.xlarge r7i.xlarge r6i.xlarge r6id.xlarge r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge"

GRAVITON_INSTANCES="c8g.xlarge c7g.xlarge c7gd.xlarge c6g.xlarge c6gd.xlarge c6gn.xlarge m8g.xlarge m7g.xlarge m7gd.xlarge m6g.xlarge m6gd.xlarge r8g.xlarge r7g.xlarge r7gd.xlarge r6g.xlarge r6gd.xlarge"

echo "=========================================="
echo " EC2 Benchmark Parallel Runner"
echo " Benchmark: $BENCHMARK_TYPE"
echo " Time: $(date)"
echo "=========================================="

# 결과 디렉토리 생성
mkdir -p "$RESULTS_DIR/geekbench"
mkdir -p "$RESULTS_DIR/passmark"
mkdir -p "$RESULTS_DIR/coldstart"

# 함수: Job 배포
deploy_job() {
    local benchmark=$1
    local instance=$2
    local arch=$3

    local safe_name=$(echo "$instance" | tr '.' '-')
    local template=""

    case $benchmark in
        geekbench)
            template="benchmarks/system/geekbench.yaml"
            ;;
        passmark)
            template="benchmarks/system/passmark.yaml"
            ;;
        coldstart)
            template="benchmarks/springboot/springboot-coldstart.yaml"
            ;;
    esac

    sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
        -e "s/INSTANCE_TYPE/${instance}/g" \
        -e "s/ARCH/${arch}/g" \
        "$template" | kubectl apply -f - 2>/dev/null

    echo "  Deployed: ${benchmark}-${safe_name}"
}

# 함수: 모든 Job 배포
deploy_all() {
    local benchmark=$1
    echo ""
    echo "=== Deploying $benchmark jobs ==="

    # Intel/AMD (amd64)
    for instance in $INTEL_INSTANCES; do
        deploy_job "$benchmark" "$instance" "amd64"
    done

    # Graviton (arm64)
    for instance in $GRAVITON_INSTANCES; do
        deploy_job "$benchmark" "$instance" "arm64"
    done

    echo "  Total: 51 jobs deployed"
}

# 함수: Job 완료 대기 및 로그 수집
wait_and_collect() {
    local benchmark=$1
    local timeout=${2:-1800}  # 기본 30분

    echo ""
    echo "=== Waiting for $benchmark jobs ==="
    echo "Timeout: ${timeout}s"

    local start_time=$(date +%s)
    local completed=0
    local failed=0

    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))

        if [ $elapsed -ge $timeout ]; then
            echo "TIMEOUT reached!"
            break
        fi

        # 완료된 Job 수 확인
        local total=$(kubectl get jobs -n benchmark -l benchmark=$benchmark --no-headers 2>/dev/null | wc -l)
        local succeeded=$(kubectl get jobs -n benchmark -l benchmark=$benchmark --no-headers 2>/dev/null | grep "1/1" | wc -l)
        local failed_jobs=$(kubectl get jobs -n benchmark -l benchmark=$benchmark --no-headers 2>/dev/null | grep -E "0/1.*0" | wc -l)

        echo -ne "\r  Progress: $succeeded/$total completed, $failed_jobs failed (${elapsed}s elapsed)    "

        if [ "$succeeded" -eq "$total" ] && [ "$total" -gt 0 ]; then
            echo ""
            echo "All jobs completed!"
            break
        fi

        sleep 30
    done

    # 로그 수집
    echo ""
    echo "=== Collecting logs ==="

    for instance in $INTEL_INSTANCES $GRAVITON_INSTANCES; do
        local safe_name=$(echo "$instance" | tr '.' '-')
        local job_name="${benchmark}-${safe_name}"
        local pod_name=$(kubectl get pods -n benchmark -l job-name=$job_name --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

        if [ -n "$pod_name" ]; then
            mkdir -p "$RESULTS_DIR/$benchmark/$instance"
            kubectl logs -n benchmark "$pod_name" > "$RESULTS_DIR/$benchmark/$instance/run1.log" 2>/dev/null || true
            echo "  Collected: $instance"
        fi
    done

    # Job 정리
    echo ""
    echo "=== Cleaning up ==="
    kubectl delete jobs -n benchmark -l benchmark=$benchmark --wait=false 2>/dev/null || true
}

# 메인 실행
case $BENCHMARK_TYPE in
    geekbench)
        deploy_all "geekbench"
        wait_and_collect "geekbench" 1800
        ;;
    passmark)
        deploy_all "passmark"
        wait_and_collect "passmark" 1800
        ;;
    coldstart)
        deploy_all "springboot-coldstart"
        wait_and_collect "springboot-coldstart" 600
        ;;
    all)
        echo ""
        echo "Running all benchmarks in sequence..."

        # Geekbench (가장 오래 걸림)
        deploy_all "geekbench"
        wait_and_collect "geekbench" 2400

        # Passmark
        deploy_all "passmark"
        wait_and_collect "passmark" 1800

        # Cold Start (가장 빠름)
        deploy_all "springboot-coldstart"
        wait_and_collect "springboot-coldstart" 600
        ;;
    *)
        echo "Usage: $0 [all|geekbench|passmark|coldstart]"
        exit 1
        ;;
esac

echo ""
echo "=========================================="
echo " Benchmark Complete!"
echo " Results: $RESULTS_DIR"
echo " Time: $(date)"
echo "=========================================="
