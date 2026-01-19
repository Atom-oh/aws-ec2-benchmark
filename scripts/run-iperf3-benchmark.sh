#!/bin/bash
# iperf3 Network Benchmark Runner
# Server-Client 아키텍처로 2개 노드 사용

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BENCHMARK_DIR/results/iperf3"
TEMPLATE="$BENCHMARK_DIR/benchmarks/system/iperf3-network.yaml"

# Configuration
MAX_CONCURRENT=10  # 동시 실행 수 (인스턴스당 2노드 필요하므로 적게)
RUNS=5

mkdir -p "$RESULTS_DIR"

# Get instance list
INSTANCES=$(grep -v "^#" "$BENCHMARK_DIR/config/instances-4vcpu.txt" | grep -v "^$")

echo "===== iperf3 Network Benchmark ====="
echo "Template: $TEMPLATE"
echo "Results: $RESULTS_DIR"
echo "Concurrent: $MAX_CONCURRENT"
echo "Runs per instance: $RUNS"
echo ""

deploy_iperf3() {
    local instance=$1
    local run=$2
    local safe_name=$(echo "$instance" | tr '.' '-')

    echo "[Deploy] $instance run$run"

    # Deploy server and service first
    sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
        -e "s/\${INSTANCE_TYPE}/${instance}/g" \
        "$TEMPLATE" | \
    sed '/^---$/,/^kind: Job$/{ /^kind: Job$/!d }' | \
    sed '/^kind: Job$/,$d' | \
    kubectl apply -f - 2>/dev/null

    # Wait for server to be ready
    echo "  Waiting for server pod..."
    for i in {1..60}; do
        pod=$(kubectl get pods -n benchmark -l app=iperf3-server,instance-type="$instance" --no-headers -o custom-columns=":metadata.name,:status.phase" 2>/dev/null | grep Running | awk '{print $1}' | head -1)
        if [ -n "$pod" ]; then
            break
        fi
        sleep 5
    done

    if [ -z "$pod" ]; then
        echo "  ERROR: Server pod not ready after 5 minutes"
        return 1
    fi

    echo "  Server ready: $pod"

    # Deploy client job with unique name for each run
    local job_name="iperf3-benchmark-${safe_name}-run${run}"

    # Extract just the Job section and modify the name
    sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
        -e "s/\${INSTANCE_TYPE}/${instance}/g" \
        "$TEMPLATE" | \
    awk '/^---$/{p=0} /^kind: Job$/{p=1} p' | \
    sed "s/name: iperf3-benchmark-${safe_name}/name: ${job_name}/" | \
    kubectl apply -f - 2>/dev/null

    echo "  Client job created: $job_name"
}

wait_and_collect() {
    local instance=$1
    local run=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local job_name="iperf3-benchmark-${safe_name}-run${run}"
    local result_dir="$RESULTS_DIR/$instance"

    mkdir -p "$result_dir"

    echo "[Wait] $instance run$run"

    # Wait for job completion (max 10 minutes)
    for i in {1..60}; do
        status=$(kubectl get job -n benchmark "$job_name" --no-headers -o custom-columns=":status.succeeded,:status.failed" 2>/dev/null || echo "0 0")
        succeeded=$(echo "$status" | awk '{print $1}')
        failed=$(echo "$status" | awk '{print $2}')

        if [ "$succeeded" = "1" ]; then
            echo "  Job completed successfully"
            break
        elif [ "$failed" = "1" ]; then
            echo "  Job failed"
            break
        fi
        sleep 10
    done

    # Collect logs
    local pod=$(kubectl get pods -n benchmark -l job-name="$job_name" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -n "$pod" ]; then
        kubectl logs -n benchmark "$pod" > "$result_dir/run${run}.log" 2>/dev/null || true
        echo "  Logs saved: $result_dir/run${run}.log"
    fi
}

cleanup_instance() {
    local instance=$1
    local run=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local job_name="iperf3-benchmark-${safe_name}-run${run}"

    # Delete job only (keep server for next run)
    kubectl delete job -n benchmark "$job_name" --ignore-not-found=true 2>/dev/null || true
}

cleanup_server() {
    local instance=$1
    local safe_name=$(echo "$instance" | tr '.' '-')

    echo "[Cleanup] Server for $instance"
    kubectl delete deployment -n benchmark "iperf3-server-${safe_name}" --ignore-not-found=true 2>/dev/null || true
    kubectl delete service -n benchmark "iperf3-server-${safe_name}" --ignore-not-found=true 2>/dev/null || true
}

# Main execution
echo "=== Phase 1: Deploy servers and run benchmarks ==="

running=0
for instance in $INSTANCES; do
    result_dir="$RESULTS_DIR/$instance"

    # Check if already completed
    completed=0
    for run in $(seq 1 $RUNS); do
        if [ -s "$result_dir/run${run}.log" ]; then
            ((completed++))
        fi
    done

    if [ $completed -ge $RUNS ]; then
        echo "[Skip] $instance - already has $RUNS runs"
        continue
    fi

    # Deploy server once per instance
    safe_name=$(echo "$instance" | tr '.' '-')

    # Check if server already exists
    existing=$(kubectl get deployment -n benchmark "iperf3-server-${safe_name}" --no-headers 2>/dev/null | wc -l)
    if [ "$existing" -eq 0 ]; then
        # Deploy server
        sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
            -e "s/\${INSTANCE_TYPE}/${instance}/g" \
            "$TEMPLATE" | \
        awk '/^---$/{if(p)exit} {p=1; print}' | \
        kubectl apply -f - 2>/dev/null

        # Also deploy the deployment (second document)
        sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
            -e "s/\${INSTANCE_TYPE}/${instance}/g" \
            "$TEMPLATE" | \
        awk 'BEGIN{d=0} /^---$/{d++; next} d==1{print}' | \
        kubectl apply -f - 2>/dev/null

        echo "[Deploy] Server for $instance"
    fi

    # Run benchmarks for missing runs
    for run in $(seq 1 $RUNS); do
        if [ -s "$result_dir/run${run}.log" ]; then
            continue
        fi

        # Wait if too many concurrent
        while [ $running -ge $MAX_CONCURRENT ]; do
            sleep 30
            running=$(kubectl get jobs -n benchmark -l benchmark=iperf3 --no-headers 2>/dev/null | grep -v "Complete\|Failed" | wc -l)
        done

        # Wait for server to be ready
        echo "  Waiting for server..."
        for i in {1..60}; do
            ready=$(kubectl get pods -n benchmark -l app=iperf3-server,instance-type="$instance" --no-headers 2>/dev/null | grep Running | wc -l)
            if [ "$ready" -gt 0 ]; then
                break
            fi
            sleep 5
        done

        # Deploy client job
        job_name="iperf3-benchmark-${safe_name}-run${run}"

        sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
            -e "s/\${INSTANCE_TYPE}/${instance}/g" \
            "$TEMPLATE" | \
        awk 'BEGIN{d=0} /^---$/{d++; next} d==2{print}' | \
        sed "s/name: iperf3-benchmark-${safe_name}/name: ${job_name}/" | \
        kubectl apply -f - 2>/dev/null

        echo "[Run] $instance run$run - job: $job_name"
        ((running++))
    done
done

echo ""
echo "=== Phase 2: Wait for all jobs to complete ==="

# Wait for all jobs
while true; do
    pending=$(kubectl get jobs -n benchmark -l benchmark=iperf3 --no-headers 2>/dev/null | grep -v "Complete\|Failed" | wc -l)
    if [ "$pending" -eq 0 ]; then
        break
    fi
    echo "Waiting for $pending jobs..."
    sleep 30
done

echo ""
echo "=== Phase 3: Collect logs ==="

for instance in $INSTANCES; do
    safe_name=$(echo "$instance" | tr '.' '-')
    result_dir="$RESULTS_DIR/$instance"
    mkdir -p "$result_dir"

    for run in $(seq 1 $RUNS); do
        if [ -s "$result_dir/run${run}.log" ]; then
            continue
        fi

        job_name="iperf3-benchmark-${safe_name}-run${run}"
        pod=$(kubectl get pods -n benchmark -l job-name="$job_name" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

        if [ -n "$pod" ]; then
            kubectl logs -n benchmark "$pod" > "$result_dir/run${run}.log" 2>/dev/null || true
            if [ -s "$result_dir/run${run}.log" ]; then
                echo "[Collected] $instance run$run"
            fi
        fi
    done
done

echo ""
echo "=== Phase 4: Cleanup ==="

for instance in $INSTANCES; do
    safe_name=$(echo "$instance" | tr '.' '-')

    # Delete all jobs for this instance
    for run in $(seq 1 $RUNS); do
        kubectl delete job -n benchmark "iperf3-benchmark-${safe_name}-run${run}" --ignore-not-found=true 2>/dev/null || true
    done

    # Delete server
    kubectl delete deployment -n benchmark "iperf3-server-${safe_name}" --ignore-not-found=true 2>/dev/null || true
    kubectl delete service -n benchmark "iperf3-server-${safe_name}" --ignore-not-found=true 2>/dev/null || true
done

echo ""
echo "===== iperf3 Benchmark Complete ====="
echo "Results saved to: $RESULTS_DIR"

# Summary
echo ""
echo "=== Results Summary ==="
for instance in $INSTANCES; do
    count=$(ls -1 "$RESULTS_DIR/$instance"/*.log 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        echo "$instance: $count runs"
    fi
done
