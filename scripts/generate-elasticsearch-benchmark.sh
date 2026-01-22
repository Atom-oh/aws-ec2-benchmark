#!/bin/bash
# Elasticsearch Benchmark Script
# - Coldstart: 5 runs -> results/elasticsearch/{instance}/coldstart{N}.log
# - Rally: 5 runs -> results/elasticsearch/{instance}/rally{N}.log
#
# Usage:
#   ./generate-elasticsearch-benchmark.sh           # Full: deploy + coldstart + rally + cleanup
#   ./generate-elasticsearch-benchmark.sh rally-only          # Rally only (ES servers already running)
#   ./generate-elasticsearch-benchmark.sh rally-only --force  # Force re-run (ignore existing logs)
#
# Pattern:
# - ES servers run as Deployments on target instances
# - Rally client runs on benchmark-client nodepool

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BASE_DIR/results/elasticsearch"
BENCHMARK_DIR="$BASE_DIR/benchmarks/elasticsearch"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"

NAMESPACE="benchmark"
COLDSTART_RUNS=5
RALLY_RUNS=5
MAX_PARALLEL=51  # Max parallel jobs (all instances)

# Parse arguments
MODE="${1:-full}"
FORCE_RERUN=false
if [ "$2" == "--force" ] || [ "$1" == "--force" ]; then
    FORCE_RERUN=true
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} $1"; }
error() { echo -e "${RED}[$(date '+%H:%M:%S')]${NC} $1"; }

# Get architecture for instance
get_arch() {
    local instance=$1
    if [[ "$instance" == *"g."* ]] || [[ "$instance" == *"gd."* ]] || [[ "$instance" == *"gn."* ]]; then
        echo "arm64"
    else
        echo "amd64"
    fi
}

# Read instance list
INSTANCES=()
while IFS=$'\t' read -r instance arch mem; do
    [[ "$instance" =~ ^#.*$ || -z "$instance" ]] && continue
    INSTANCES+=("$instance")
done < "$INSTANCE_FILE"

log "Found ${#INSTANCES[@]} instances to benchmark"
log "Mode: $MODE | Force: $FORCE_RERUN | Rally runs: $RALLY_RUNS"

# Create results directories
for inst in "${INSTANCES[@]}"; do
    mkdir -p "$RESULTS_DIR/$inst"
done

# ============================================================
# PHASE 1: Deploy all ES servers (skip in rally-only mode)
# ============================================================
if [ "$MODE" != "rally-only" ]; then
    log "Phase 1: Deploying ${#INSTANCES[@]} ES servers..."

    # Apply ConfigMap (only once)
    FIRST_INSTANCE="${INSTANCES[0]}"
    SAFE_NAME=$(echo "$FIRST_INSTANCE" | tr '.' '-')
    ARCH=$(get_arch "$FIRST_INSTANCE")
    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/INSTANCE_TYPE/${FIRST_INSTANCE}/g" \
        -e "s/ARCH/${ARCH}/g" \
        "$BENCHMARK_DIR/elasticsearch-server.yaml" | kubectl apply -f - 2>/dev/null | grep -E "configmap" || true

    # Deploy all servers
    for INSTANCE in "${INSTANCES[@]}"; do
        SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
        ARCH=$(get_arch "$INSTANCE")

        sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
            -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
            -e "s/ARCH/${ARCH}/g" \
            "$BENCHMARK_DIR/elasticsearch-server.yaml" | \
            kubectl apply -f - 2>&1 | grep -v "configmap" | grep -v "unchanged" || true
    done

    log "Waiting for ES servers to be ready..."
    sleep 60

    # Wait for all pods to be ready
    READY_COUNT=0
    MAX_WAIT=600
    WAIT_TIME=0
    while [ $READY_COUNT -lt ${#INSTANCES[@]} ] && [ $WAIT_TIME -lt $MAX_WAIT ]; do
        READY_COUNT=$(kubectl get pods -n $NAMESPACE -l app=es-server --no-headers 2>/dev/null | grep "Running" | wc -l)
        log "ES servers ready: $READY_COUNT / ${#INSTANCES[@]}"
        [ $READY_COUNT -lt ${#INSTANCES[@]} ] && sleep 15
        WAIT_TIME=$((WAIT_TIME + 15))
    done

    if [ $READY_COUNT -lt ${#INSTANCES[@]} ]; then
        warn "Only $READY_COUNT servers ready after ${MAX_WAIT}s, proceeding anyway..."
    fi
else
    log "Phase 1: SKIPPED (rally-only mode)"
    # Verify ES servers are running
    READY_COUNT=$(kubectl get pods -n $NAMESPACE -l app=es-server --no-headers 2>/dev/null | grep "Running" | wc -l)
    log "Found $READY_COUNT ES servers already running"
    if [ $READY_COUNT -eq 0 ]; then
        error "No ES servers found! Deploy servers first or use 'full' mode"
        exit 1
    fi
fi

# ============================================================
# PHASE 2: Run Coldstart benchmarks (skip in rally-only mode)
# ============================================================
if [ "$MODE" != "rally-only" ]; then
    log "Phase 2: Running Coldstart benchmarks..."

run_coldstart_job() {
    local INSTANCE=$1
    local RUN_NUM=$2

    local SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    local ARCH=$(get_arch "$INSTANCE")
    local JOB_NAME="es-coldstart-${SAFE_NAME}-run${RUN_NUM}"
    local LOG_FILE="$RESULTS_DIR/$INSTANCE/coldstart${RUN_NUM}.log"

    # Skip if already completed
    if [ -f "$LOG_FILE" ] && grep -q "Complete" "$LOG_FILE" 2>/dev/null; then
        echo "[$INSTANCE] coldstart ${RUN_NUM} already complete, skipping"
        return 0
    fi

    # Delete old job if exists
    kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found 2>/dev/null

    # Create job (coldstart runs ES internally)
    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
        -e "s/ARCH/${ARCH}/g" \
        "$BENCHMARK_DIR/elasticsearch-coldstart.yaml" | \
        sed "s/es-coldstart-INSTANCE_SAFE/es-coldstart-${SAFE_NAME}-run${RUN_NUM}/" | \
        kubectl apply -f - >/dev/null 2>&1

    # Wait for completion
    local MAX_WAIT=600
    local WAIT=0
    while [ $WAIT -lt $MAX_WAIT ]; do
        local STATUS=$(kubectl get job "$JOB_NAME" -n $NAMESPACE -o jsonpath='{.status.succeeded}' 2>/dev/null)
        if [ "$STATUS" == "1" ]; then
            break
        fi

        local FAILED=$(kubectl get job "$JOB_NAME" -n $NAMESPACE -o jsonpath='{.status.failed}' 2>/dev/null)
        if [ "$FAILED" == "1" ]; then
            echo "[$INSTANCE] coldstart ${RUN_NUM} FAILED"
            kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found >/dev/null 2>&1
            return 1
        fi

        sleep 10
        WAIT=$((WAIT + 10))
    done

    # Collect logs
    local POD=$(kubectl get pods -n $NAMESPACE -l job-name=$JOB_NAME --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -n "$POD" ]; then
        kubectl logs -n $NAMESPACE "$POD" > "$LOG_FILE" 2>/dev/null
        echo "[$INSTANCE] coldstart ${RUN_NUM} completed -> coldstart${RUN_NUM}.log"
    else
        echo "[$INSTANCE] coldstart ${RUN_NUM} - no pod found"
    fi

    # Cleanup
    kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found >/dev/null 2>&1
}

# Run coldstart for each instance (sequential per instance, parallel across instances)
run_instance_coldstarts() {
    local INSTANCE=$1
    for RUN in $(seq 1 $COLDSTART_RUNS); do
        run_coldstart_job "$INSTANCE" "$RUN"
    done
    echo "[$INSTANCE] All coldstart runs completed"
}

export -f run_coldstart_job run_instance_coldstarts get_arch
export RESULTS_DIR BENCHMARK_DIR NAMESPACE COLDSTART_RUNS

if command -v parallel &> /dev/null; then
    printf '%s\n' "${INSTANCES[@]}" | parallel -j $MAX_PARALLEL run_instance_coldstarts {}
else
    RUNNING=0
    for INSTANCE in "${INSTANCES[@]}"; do
        run_instance_coldstarts "$INSTANCE" &
        RUNNING=$((RUNNING + 1))

        if [ $RUNNING -ge $MAX_PARALLEL ]; then
            wait -n 2>/dev/null || wait
            RUNNING=$((RUNNING - 1))
        fi
    done
    wait
fi
else
    log "Phase 2: SKIPPED (rally-only mode)"
fi

# ============================================================
# PHASE 3: Run Rally benchmarks
# ============================================================
log "Phase 3: Running Rally benchmarks..."

run_rally_job() {
    local INSTANCE=$1
    local RUN_NUM=$2

    local SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    local ARCH=$(get_arch "$INSTANCE")
    local JOB_NAME="es-rally-${SAFE_NAME}-run${RUN_NUM}"
    local LOG_FILE="$RESULTS_DIR/$INSTANCE/rally${RUN_NUM}.log"

    # Skip if already completed (unless --force)
    if [ "$FORCE_RERUN" != "true" ]; then
        if [ -f "$LOG_FILE" ] && grep -q "Rally Benchmark Complete" "$LOG_FILE" 2>/dev/null; then
            echo "[$INSTANCE] rally ${RUN_NUM} already complete, skipping"
            return 0
        fi
    fi

    # Delete old job if exists
    kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found 2>/dev/null

    # Create Rally job (connects to existing ES server)
    # Uses RUN_NUMBER placeholder from YAML template
    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
        -e "s/RUN_NUMBER/${RUN_NUM}/g" \
        -e "s/ARCH/${ARCH}/g" \
        "$BENCHMARK_DIR/elasticsearch-rally.yaml" | \
        kubectl apply -f - >/dev/null 2>&1

    # Wait for completion (Rally takes longer)
    local MAX_WAIT=1800  # 30 minutes
    local WAIT=0
    while [ $WAIT -lt $MAX_WAIT ]; do
        local STATUS=$(kubectl get job "$JOB_NAME" -n $NAMESPACE -o jsonpath='{.status.succeeded}' 2>/dev/null)
        if [ "$STATUS" == "1" ]; then
            break
        fi

        local FAILED=$(kubectl get job "$JOB_NAME" -n $NAMESPACE -o jsonpath='{.status.failed}' 2>/dev/null)
        if [ "$FAILED" == "1" ]; then
            echo "[$INSTANCE] rally ${RUN_NUM} FAILED"
            kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found >/dev/null 2>&1
            return 1
        fi

        sleep 15
        WAIT=$((WAIT + 15))
    done

    # Collect logs
    local POD=$(kubectl get pods -n $NAMESPACE -l job-name=$JOB_NAME --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -n "$POD" ]; then
        kubectl logs -n $NAMESPACE "$POD" > "$LOG_FILE" 2>/dev/null
        echo "[$INSTANCE] rally ${RUN_NUM} completed -> rally${RUN_NUM}.log"
    else
        echo "[$INSTANCE] rally ${RUN_NUM} - no pod found"
    fi

    # Cleanup job (keep ES server running for next rally run)
    kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found >/dev/null 2>&1
}

# Run Rally for each instance
run_instance_rallies() {
    local INSTANCE=$1
    for RUN in $(seq 1 $RALLY_RUNS); do
        run_rally_job "$INSTANCE" "$RUN"
    done
    echo "[$INSTANCE] All rally runs completed"
}

export -f run_rally_job run_instance_rallies get_arch
export RESULTS_DIR BENCHMARK_DIR NAMESPACE RALLY_RUNS FORCE_RERUN

if command -v parallel &> /dev/null; then
    printf '%s\n' "${INSTANCES[@]}" | parallel -j $MAX_PARALLEL run_instance_rallies {}
else
    RUNNING=0
    for INSTANCE in "${INSTANCES[@]}"; do
        run_instance_rallies "$INSTANCE" &
        RUNNING=$((RUNNING + 1))

        if [ $RUNNING -ge $MAX_PARALLEL ]; then
            wait -n 2>/dev/null || wait
            RUNNING=$((RUNNING - 1))
        fi
    done
    wait
fi

# ============================================================
# PHASE 4: Cleanup ES servers (skip in rally-only mode)
# ============================================================
if [ "$MODE" != "rally-only" ]; then
    log "Phase 4: Cleaning up ES servers..."

    for INSTANCE in "${INSTANCES[@]}"; do
        SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
        kubectl delete deployment "es-server-${SAFE_NAME}" -n $NAMESPACE --ignore-not-found >/dev/null 2>&1
        kubectl delete service "es-server-${SAFE_NAME}" -n $NAMESPACE --ignore-not-found >/dev/null 2>&1
    done
else
    log "Phase 4: SKIPPED (rally-only mode - ES servers kept running)"
fi

# ============================================================
# PHASE 5: Summary
# ============================================================
log "Phase 5: Generating summary..."

COLDSTART_LOGS=$(find "$RESULTS_DIR" -name "coldstart*.log" -size +0 2>/dev/null | wc -l)
RALLY_LOGS=$(find "$RESULTS_DIR" -name "rally*.log" -size +0 2>/dev/null | wc -l)
EXPECTED_COLDSTART=$((${#INSTANCES[@]} * COLDSTART_RUNS))
EXPECTED_RALLY=$((${#INSTANCES[@]} * RALLY_RUNS))

echo ""
echo "=============================================="
echo "Elasticsearch Benchmark Complete"
echo "=============================================="
echo "Mode: $MODE"
echo "Instances: ${#INSTANCES[@]}"
if [ "$MODE" != "rally-only" ]; then
    echo "Coldstart logs: $COLDSTART_LOGS / $EXPECTED_COLDSTART"
fi
echo "Rally logs: $RALLY_LOGS / $EXPECTED_RALLY"
echo ""

# Show missing logs
MISSING_COUNT=0
for INSTANCE in "${INSTANCES[@]}"; do
    if [ "$MODE" != "rally-only" ]; then
        for RUN in $(seq 1 $COLDSTART_RUNS); do
            LOG_FILE="$RESULTS_DIR/$INSTANCE/coldstart${RUN}.log"
            if [ ! -f "$LOG_FILE" ] || [ ! -s "$LOG_FILE" ]; then
                warn "Missing: $INSTANCE/coldstart${RUN}.log"
                MISSING_COUNT=$((MISSING_COUNT + 1))
            fi
        done
    fi
    for RUN in $(seq 1 $RALLY_RUNS); do
        LOG_FILE="$RESULTS_DIR/$INSTANCE/rally${RUN}.log"
        if [ ! -f "$LOG_FILE" ] || [ ! -s "$LOG_FILE" ]; then
            warn "Missing: $INSTANCE/rally${RUN}.log"
            MISSING_COUNT=$((MISSING_COUNT + 1))
        fi
    done
done

if [ $MISSING_COUNT -eq 0 ]; then
    log "All logs collected successfully!"
else
    warn "Missing $MISSING_COUNT log files"
fi

log "Results saved to: $RESULTS_DIR"
