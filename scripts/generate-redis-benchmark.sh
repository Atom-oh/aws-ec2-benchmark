#!/bin/bash
# Redis 8.4 Benchmark Script
# - Deploy all Redis servers in parallel
# - Run 5 sequential benchmarks per instance (same server reused)
# - Different instances run in parallel
# - Results: results/redis/{instance}/run{N}.log

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BASE_DIR/results/redis"
BENCHMARK_DIR="$BASE_DIR/benchmarks/redis"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"

NAMESPACE="benchmark"
RUNS=5
MAX_PARALLEL=51  # All instances run in parallel (each is unique)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} $1"; }
error() { echo -e "${RED}[$(date '+%H:%M:%S')]${NC} $1"; }

# Read instance list (tab-separated: instance arch memory)
INSTANCES=()
while IFS=$'\t' read -r instance arch mem; do
    [[ "$instance" =~ ^#.*$ || -z "$instance" ]] && continue
    INSTANCES+=("$instance")
done < "$INSTANCE_FILE"

log "Found ${#INSTANCES[@]} instances to benchmark"

# Create results directory
mkdir -p "$RESULTS_DIR"

# ============================================================
# PHASE 1: Deploy all Redis servers in parallel
# ============================================================
log "Phase 1: Deploying ${#INSTANCES[@]} Redis servers..."

# First apply ConfigMap (only once)
FIRST_INSTANCE="${INSTANCES[0]}"
SAFE_NAME=$(echo "$FIRST_INSTANCE" | tr '.' '-')
sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
    -e "s/\${INSTANCE_TYPE}/${FIRST_INSTANCE}/g" \
    "$BENCHMARK_DIR/redis-server.yaml" | kubectl apply -f - 2>/dev/null | grep -E "configmap" || true

# Deploy all servers
for INSTANCE in "${INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')

    # Skip ConfigMap (already created), only create Deployment and Service
    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
        "$BENCHMARK_DIR/redis-server.yaml" | \
        kubectl apply -f - 2>&1 | grep -v "configmap" | grep -v "unchanged" || true
done

log "Waiting for all Redis servers to be ready..."
sleep 30

# Wait for all pods to be ready
READY_COUNT=0
MAX_WAIT=300
WAIT_TIME=0
while [ $READY_COUNT -lt ${#INSTANCES[@]} ] && [ $WAIT_TIME -lt $MAX_WAIT ]; do
    READY_COUNT=$(kubectl get pods -n $NAMESPACE -l app=redis-server --no-headers 2>/dev/null | grep "Running" | wc -l)
    log "Redis servers ready: $READY_COUNT / ${#INSTANCES[@]}"
    [ $READY_COUNT -lt ${#INSTANCES[@]} ] && sleep 10
    WAIT_TIME=$((WAIT_TIME + 10))
done

if [ $READY_COUNT -lt ${#INSTANCES[@]} ]; then
    warn "Only $READY_COUNT servers ready after ${MAX_WAIT}s, proceeding anyway..."
fi

# ============================================================
# PHASE 2: Run benchmarks (parallel across instances, sequential per instance)
# ============================================================
log "Phase 2: Running benchmarks..."

# Function to run all 5 benchmarks for one instance
run_instance_benchmarks() {
    local INSTANCE=$1
    local SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    local INSTANCE_DIR="$RESULTS_DIR/$INSTANCE"

    mkdir -p "$INSTANCE_DIR"

    for RUN in $(seq 1 $RUNS); do
        local JOB_NAME="redis-bench-${SAFE_NAME}-run${RUN}"
        local LOG_FILE="$INSTANCE_DIR/run${RUN}.log"

        # Skip if already completed
        if [ -f "$LOG_FILE" ] && grep -q "Benchmark Complete" "$LOG_FILE" 2>/dev/null; then
            echo "[$INSTANCE] Run $RUN already complete, skipping"
            continue
        fi

        # Delete old job if exists
        kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found 2>/dev/null

        # Create and run job
        sed -e "s/JOB_NAME/${JOB_NAME}/g" \
            -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
            -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
            "$BENCHMARK_DIR/redis-benchmark.yaml" | kubectl apply -f - >/dev/null 2>&1

        # Wait for job completion
        local JOB_WAIT=0
        local JOB_MAX_WAIT=300
        while [ $JOB_WAIT -lt $JOB_MAX_WAIT ]; do
            local STATUS=$(kubectl get job "$JOB_NAME" -n $NAMESPACE -o jsonpath='{.status.succeeded}' 2>/dev/null)
            if [ "$STATUS" == "1" ]; then
                break
            fi
            sleep 5
            JOB_WAIT=$((JOB_WAIT + 5))
        done

        # Collect logs
        local POD=$(kubectl get pods -n $NAMESPACE -l job-name=$JOB_NAME --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
        if [ -n "$POD" ]; then
            kubectl logs -n $NAMESPACE "$POD" 2>/dev/null | tr '\r' '\n' > "$LOG_FILE"
            echo "[$INSTANCE] Run $RUN completed -> $LOG_FILE"
        else
            echo "[$INSTANCE] Run $RUN FAILED - no pod found"
        fi

        # Cleanup job
        kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found >/dev/null 2>&1
    done

    echo "[$INSTANCE] All $RUNS runs completed"
}

export -f run_instance_benchmarks
export RESULTS_DIR BENCHMARK_DIR NAMESPACE RUNS

# Run benchmarks in parallel (limited concurrency)
log "Starting parallel benchmark execution (max $MAX_PARALLEL concurrent)..."

# Using GNU parallel if available, otherwise simple background jobs
if command -v parallel &> /dev/null; then
    printf '%s\n' "${INSTANCES[@]}" | parallel -j $MAX_PARALLEL run_instance_benchmarks {}
else
    # Simple parallel with job control
    RUNNING=0
    for INSTANCE in "${INSTANCES[@]}"; do
        run_instance_benchmarks "$INSTANCE" &
        RUNNING=$((RUNNING + 1))

        if [ $RUNNING -ge $MAX_PARALLEL ]; then
            wait -n 2>/dev/null || wait
            RUNNING=$((RUNNING - 1))
        fi
    done
    wait
fi

# ============================================================
# PHASE 3: Summary
# ============================================================
log "Phase 3: Generating summary..."

TOTAL_LOGS=$(find "$RESULTS_DIR" -name "run*.log" | wc -l)
EXPECTED=$((${#INSTANCES[@]} * RUNS))

echo ""
echo "=============================================="
echo "Redis Benchmark Complete"
echo "=============================================="
echo "Instances: ${#INSTANCES[@]}"
echo "Runs per instance: $RUNS"
echo "Total logs: $TOTAL_LOGS / $EXPECTED"
echo ""

# Show any missing logs
for INSTANCE in "${INSTANCES[@]}"; do
    for RUN in $(seq 1 $RUNS); do
        LOG_FILE="$RESULTS_DIR/$INSTANCE/run${RUN}.log"
        if [ ! -f "$LOG_FILE" ]; then
            warn "Missing: $INSTANCE/run${RUN}.log"
        fi
    done
done

log "Results saved to: $RESULTS_DIR"
