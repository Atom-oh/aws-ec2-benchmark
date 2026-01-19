#!/bin/bash
# 테스트 실행 스크립트 - c5.xlarge, c6g.xlarge만 실행
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BASE_DIR/results"

ITERATIONS=5
TEST_INSTANCES=("c5.xlarge" "c6g.xlarge")

GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_iter() { echo -e "${CYAN}[ITER]${NC} $1"; }

wait_for_job() {
    local job_name=$1
    local timeout=${2:-600}
    log_info "Waiting for job: $job_name"
    kubectl wait --for=condition=complete "job/$job_name" -n benchmark --timeout="${timeout}s" 2>/dev/null || \
    kubectl wait --for=condition=failed "job/$job_name" -n benchmark --timeout="${timeout}s" 2>/dev/null || true
}

collect_log() {
    local job_name=$1
    local output_file=$2
    kubectl logs "job/$job_name" -n benchmark > "$output_file" 2>/dev/null || true
}

# ===================
# SYSBENCH
# ===================
run_sysbench() {
    local instance=$1
    local iteration=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local job_name="sysbench-cpu-${safe_name}-run${iteration}"
    local output_dir="$RESULTS_DIR/sysbench/$instance"

    mkdir -p "$output_dir"
    [[ -f "$output_dir/run${iteration}.log" ]] && [[ -s "$output_dir/run${iteration}.log" ]] && return 0

    log_iter "Sysbench $instance - Run $iteration/$ITERATIONS"

    cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: benchmark
  labels:
    benchmark: sysbench
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 0
  template:
    metadata:
      labels:
        benchmark: sysbench
    spec:
      restartPolicy: Never
      nodeSelector:
        node.kubernetes.io/instance-type: "${instance}"
      tolerations:
        - key: "benchmark"
          operator: "Equal"
          value: "true"
          effect: "NoSchedule"
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: benchmark
                    operator: Exists
              topologyKey: "kubernetes.io/hostname"
      containers:
        - name: sysbench
          image: 180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/docker-hub/severalnines/sysbench:latest
          resources: {}
          command: ["/bin/sh", "-c"]
          args:
            - |
              echo "===== Sysbench CPU: ${instance} ====="
              echo "Timestamp: \$(date -Iseconds)"
              cat /proc/cpuinfo | grep "model name" | head -1
              echo "CPU cores: \$(nproc)"
              echo ""
              echo "--- Warm-up (10s) ---"
              sysbench cpu --threads=\$(nproc) --time=10 run > /dev/null
              for i in 1 2 3; do
                echo ""
                echo "--- Run \$i/3 ---"
                sysbench cpu --threads=\$(nproc) --time=60 --cpu-max-prime=20000 run
              done
              echo ""
              echo "===== Single Thread Performance ====="
              sysbench cpu --threads=1 --time=30 --cpu-max-prime=20000 run
              echo ""
              echo "===== Complete ====="
EOF

    wait_for_job "$job_name" 600
    collect_log "$job_name" "$output_dir/run${iteration}.log"
    kubectl delete job "$job_name" -n benchmark --ignore-not-found=true
}

# ===================
# NGINX
# ===================
run_nginx() {
    local instance=$1
    local iteration=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local server_name="nginx-server-${safe_name}"
    local benchmark_name="nginx-benchmark-${safe_name}-run${iteration}"
    local output_dir="$RESULTS_DIR/nginx/$instance"

    mkdir -p "$output_dir"
    [[ -f "$output_dir/run${iteration}.log" ]] && [[ -s "$output_dir/run${iteration}.log" ]] && return 0

    log_iter "Nginx $instance - Run $iteration/$ITERATIONS"

    # 서버 배포 (첫 iteration만)
    if ! kubectl get deployment "$server_name" -n benchmark &>/dev/null; then
        sed -e "s/\${INSTANCE_TYPE}/$instance/g" \
            "$BASE_DIR/benchmarks/nginx/nginx-server.yaml" | kubectl apply -f -
        sleep 30
        kubectl wait --for=condition=available "deployment/$server_name" -n benchmark --timeout=300s || true
        sleep 10
    fi

    # 벤치마크
    cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${benchmark_name}
  namespace: benchmark
  labels:
    benchmark: nginx-benchmark
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 0
  template:
    metadata:
      labels:
        benchmark: nginx-benchmark
    spec:
      restartPolicy: Never
      nodeSelector:
        node-type: benchmark-client
      tolerations:
        - key: "benchmark-client"
          operator: "Equal"
          value: "true"
          effect: "NoSchedule"
      initContainers:
        - name: wait-for-nginx
          image: public.ecr.aws/docker/library/alpine:latest
          command: ["/bin/sh", "-c"]
          args:
            - |
              until wget -q -O - http://${server_name}/health 2>/dev/null | grep -q healthy; do
                sleep 2
              done
      containers:
        - name: benchmark
          image: 180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/benchmark/wrk:latest
          resources:
            requests:
              cpu: "4"
              memory: "4Gi"
          command: ["/bin/sh", "-c"]
          args:
            - |
              echo "===== Nginx Benchmark: ${instance} ====="
              echo "Timestamp: \$(date -Iseconds)"
              echo ""
              echo "=== Warm-up (10s) ==="
              wrk -t2 -c50 -d10s http://${server_name}/ > /dev/null 2>&1
              sleep 2
              echo "=== wrk Test (2 threads, 100 connections, 30s) ==="
              wrk -t2 -c100 -d30s http://${server_name}/
              echo ""
              sleep 2
              echo "=== wrk Test (4 threads, 200 connections, 30s) ==="
              wrk -t4 -c200 -d30s http://${server_name}/
              echo ""
              sleep 2
              echo "=== wrk Test (8 threads, 400 connections, 30s) ==="
              wrk -t8 -c400 -d30s http://${server_name}/
              echo ""
              echo "===== Complete ====="
EOF

    wait_for_job "$benchmark_name" 300
    collect_log "$benchmark_name" "$output_dir/run${iteration}.log"
    kubectl delete job "$benchmark_name" -n benchmark --ignore-not-found=true
}

cleanup_nginx() {
    local instance=$1
    local safe_name=$(echo "$instance" | tr '.' '-')
    kubectl delete deployment "nginx-server-${safe_name}" -n benchmark --ignore-not-found=true
    kubectl delete service "nginx-server-${safe_name}" -n benchmark --ignore-not-found=true
}

# ===================
# REDIS
# ===================
run_redis() {
    local instance=$1
    local iteration=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local server_name="redis-server-${safe_name}"
    local benchmark_name="redis-benchmark-${safe_name}-run${iteration}"
    local output_dir="$RESULTS_DIR/redis/$instance"

    mkdir -p "$output_dir"
    [[ -f "$output_dir/run${iteration}.log" ]] && [[ -s "$output_dir/run${iteration}.log" ]] && return 0

    log_iter "Redis $instance - Run $iteration/$ITERATIONS"

    # 서버 배포
    if ! kubectl get deployment "$server_name" -n benchmark &>/dev/null; then
        sed -e "s/\${INSTANCE_TYPE}/$instance/g" \
            "$BASE_DIR/benchmarks/redis/redis-server.yaml" | kubectl apply -f -
        sleep 30
        kubectl wait --for=condition=available "deployment/$server_name" -n benchmark --timeout=300s || true
        sleep 10
    fi

    # 벤치마크
    cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${benchmark_name}
  namespace: benchmark
  labels:
    benchmark: redis-benchmark
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 0
  template:
    metadata:
      labels:
        benchmark: redis-benchmark
    spec:
      restartPolicy: Never
      nodeSelector:
        node-type: benchmark-client
      tolerations:
        - key: "benchmark-client"
          operator: "Equal"
          value: "true"
          effect: "NoSchedule"
      initContainers:
        - name: wait-for-redis
          image: public.ecr.aws/docker/library/redis:7-alpine
          command: ["/bin/sh", "-c"]
          args:
            - |
              until redis-cli -h ${server_name} ping | grep -q PONG; do
                sleep 2
              done
      containers:
        - name: benchmark
          image: public.ecr.aws/docker/library/redis:7-alpine
          resources:
            requests:
              cpu: "2"
              memory: "2Gi"
          command: ["/bin/sh", "-c"]
          args:
            - |
              echo "===== Redis Benchmark: ${instance} ====="
              echo "Timestamp: \$(date -Iseconds)"
              echo ""
              echo "--- Standard Benchmark (50 clients, 100000 requests) ---"
              redis-benchmark -h ${server_name} -c 50 -n 100000 -q
              echo ""
              echo "--- Pipeline Benchmark (16 commands per pipeline) ---"
              redis-benchmark -h ${server_name} -c 50 -n 100000 -P 16 -q
              echo ""
              echo "--- High Concurrency (100 clients) ---"
              redis-benchmark -h ${server_name} -c 100 -n 200000 -q
              echo ""
              echo "===== Complete ====="
EOF

    wait_for_job "$benchmark_name" 600
    collect_log "$benchmark_name" "$output_dir/run${iteration}.log"
    kubectl delete job "$benchmark_name" -n benchmark --ignore-not-found=true
}

cleanup_redis() {
    local instance=$1
    local safe_name=$(echo "$instance" | tr '.' '-')
    kubectl delete deployment "redis-server-${safe_name}" -n benchmark --ignore-not-found=true
    kubectl delete service "redis-server-${safe_name}" -n benchmark --ignore-not-found=true
}

# ===================
# ELASTICSEARCH
# ===================
run_elasticsearch() {
    local instance=$1
    local arch=$2
    local iteration=$3
    local safe_name=$(echo "$instance" | tr '.' '-')
    local job_name="es-coldstart-${safe_name}-run${iteration}"
    local output_dir="$RESULTS_DIR/elasticsearch/$instance"

    mkdir -p "$output_dir"
    [[ -f "$output_dir/run${iteration}.log" ]] && [[ -s "$output_dir/run${iteration}.log" ]] && return 0

    log_iter "Elasticsearch $instance ($arch) - Run $iteration/$ITERATIONS"

    sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
        -e "s/INSTANCE_TYPE/${instance}/g" \
        -e "s/ARCH/${arch}/g" \
        -e "s/es-coldstart-${safe_name}/es-coldstart-${safe_name}-run${iteration}/g" \
        "$BASE_DIR/benchmarks/elasticsearch/elasticsearch-coldstart.yaml" | kubectl apply -f -

    wait_for_job "$job_name" 900
    collect_log "$job_name" "$output_dir/run${iteration}.log"
    kubectl delete job "$job_name" -n benchmark --ignore-not-found=true
}

# ===================
# MAIN
# ===================
log_info "=== Starting Test Run (c5.xlarge, c6g.xlarge) ==="
log_info "Iterations: $ITERATIONS"
log_info ""

# Sysbench
log_info "=== SYSBENCH CPU ==="
for instance in "${TEST_INSTANCES[@]}"; do
    for iter in $(seq 1 $ITERATIONS); do
        run_sysbench "$instance" "$iter"
        sleep 3
    done
done

# Nginx
log_info "=== NGINX ==="
for instance in "${TEST_INSTANCES[@]}"; do
    for iter in $(seq 1 $ITERATIONS); do
        run_nginx "$instance" "$iter"
        sleep 3
    done
    cleanup_nginx "$instance"
done

# Redis
log_info "=== REDIS ==="
for instance in "${TEST_INSTANCES[@]}"; do
    for iter in $(seq 1 $ITERATIONS); do
        run_redis "$instance" "$iter"
        sleep 3
    done
    cleanup_redis "$instance"
done

# Elasticsearch
log_info "=== ELASTICSEARCH ==="
run_elasticsearch "c5.xlarge" "amd64" 1
for iter in $(seq 2 $ITERATIONS); do
    run_elasticsearch "c5.xlarge" "amd64" "$iter"
    sleep 5
done
for iter in $(seq 1 $ITERATIONS); do
    run_elasticsearch "c6g.xlarge" "arm64" "$iter"
    sleep 5
done

log_info ""
log_info "=== Test Run Complete ==="
log_info "Run: ./scripts/parse-results.sh all"
