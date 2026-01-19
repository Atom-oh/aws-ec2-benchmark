#!/bin/bash
# Run all system benchmarks for all 51 instance types
# Includes: sysbench-cpu, sysbench-memory, stress-ng, fio-disk

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BENCHMARK_DIR/results"
CONFIG_FILE="$BENCHMARK_DIR/config/instances-4vcpu.txt"

# Configuration
MAX_CONCURRENT=15  # Number of concurrent jobs
RUNS=5

# Get instance list
INSTANCES=$(grep -v "^#" "$CONFIG_FILE" | grep -v "^$")
TOTAL_INSTANCES=$(echo "$INSTANCES" | wc -l)

echo "===== System Benchmarks Runner ====="
echo "Instances: $TOTAL_INSTANCES"
echo "Concurrent: $MAX_CONCURRENT"
echo "Runs per instance: $RUNS"
echo ""

run_benchmark() {
    local bench_type=$1
    local template=$2

    echo ""
    echo "========================================"
    echo "Starting: $bench_type"
    echo "========================================"

    local result_dir="$RESULTS_DIR/$bench_type"
    mkdir -p "$result_dir"

    # Phase 1: Deploy all jobs
    echo "=== Phase 1: Deploying jobs ==="

    local running=0
    for instance in $INSTANCES; do
        local safe_name=$(echo "$instance" | tr '.' '-')
        local instance_dir="$result_dir/$instance"
        mkdir -p "$instance_dir"

        # Check how many runs already exist
        local existing_runs=$(find "$instance_dir" -name "*.log" -size +0 2>/dev/null | wc -l)
        if [ "$existing_runs" -ge "$RUNS" ]; then
            echo "[Skip] $instance - already has $existing_runs runs"
            continue
        fi

        # Create jobs for missing runs
        for run in $(seq 1 $RUNS); do
            local logfile="$instance_dir/run${run}.log"
            if [ -s "$logfile" ]; then
                continue
            fi

            # Wait if too many concurrent jobs
            while [ $running -ge $MAX_CONCURRENT ]; do
                sleep 10
                running=$(kubectl get jobs -n benchmark -l benchmark=${bench_type%%"-"*} --no-headers 2>/dev/null | grep -v "Complete\|Failed" | wc -l)
            done

            local job_name="${bench_type}-${safe_name}-run${run}"

            # Delete existing job if any
            kubectl delete job -n benchmark "$job_name" --ignore-not-found=true 2>/dev/null || true

            # Create job
            sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
                -e "s/\${INSTANCE_TYPE}/${instance}/g" \
                "$template" | \
            sed "s/name: ${bench_type}-${safe_name}/name: ${job_name}/" | \
            kubectl apply -f - 2>/dev/null

            echo "[Deploy] $job_name"
            ((running++))
        done
    done

    # Phase 2: Wait for completion
    echo ""
    echo "=== Phase 2: Waiting for jobs to complete ==="

    while true; do
        local pending=$(kubectl get jobs -n benchmark -l benchmark=${bench_type%%"-"*} --no-headers 2>/dev/null | grep -v "Complete\|Failed" | wc -l)
        if [ "$pending" -eq 0 ]; then
            break
        fi
        echo "  $pending jobs still running..."
        sleep 30
    done

    # Phase 3: Collect logs
    echo ""
    echo "=== Phase 3: Collecting logs ==="

    for instance in $INSTANCES; do
        local safe_name=$(echo "$instance" | tr '.' '-')
        local instance_dir="$result_dir/$instance"

        for run in $(seq 1 $RUNS); do
            local logfile="$instance_dir/run${run}.log"
            if [ -s "$logfile" ]; then
                continue
            fi

            local job_name="${bench_type}-${safe_name}-run${run}"
            local pod=$(kubectl get pods -n benchmark -l job-name="$job_name" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

            if [ -n "$pod" ]; then
                kubectl logs -n benchmark "$pod" > "$logfile" 2>/dev/null || true
                if [ -s "$logfile" ]; then
                    echo "[Collected] $instance run$run"
                fi
            fi
        done
    done

    # Phase 4: Cleanup
    echo ""
    echo "=== Phase 4: Cleaning up ==="

    for instance in $INSTANCES; do
        local safe_name=$(echo "$instance" | tr '.' '-')
        for run in $(seq 1 $RUNS); do
            kubectl delete job -n benchmark "${bench_type}-${safe_name}-run${run}" --ignore-not-found=true 2>/dev/null || true
        done
    done

    # Summary
    echo ""
    echo "=== $bench_type Summary ==="
    local complete=0
    for instance in $INSTANCES; do
        local instance_dir="$result_dir/$instance"
        local count=$(find "$instance_dir" -name "*.log" -size +0 2>/dev/null | wc -l)
        if [ "$count" -ge "$RUNS" ]; then
            ((complete++))
        fi
    done
    echo "Complete instances: $complete / $TOTAL_INSTANCES"
}

# Check if cluster is ready
echo "Checking cluster readiness..."
pending_jobs=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep -v "Complete\|Failed" | wc -l)
if [ "$pending_jobs" -gt 0 ]; then
    echo "WARNING: $pending_jobs jobs still running. Wait for completion or press Enter to continue anyway."
    read -t 30 || true
fi

# Run each benchmark type
echo ""
echo "Starting system benchmarks..."

# 1. sysbench-cpu
run_benchmark "sysbench-cpu" "$BENCHMARK_DIR/benchmarks/system/sysbench-cpu.yaml"

# 2. sysbench-memory
run_benchmark "sysbench-memory" "$BENCHMARK_DIR/benchmarks/system/sysbench-memory.yaml"

# 3. stress-ng
run_benchmark "stress-ng" "$BENCHMARK_DIR/benchmarks/system/stress-ng.yaml"

# 4. fio-disk
run_benchmark "fio-disk" "$BENCHMARK_DIR/benchmarks/system/fio-disk.yaml"

echo ""
echo "===== All System Benchmarks Complete ====="
echo ""
echo "Results saved to: $RESULTS_DIR"
