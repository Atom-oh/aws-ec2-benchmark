#!/bin/bash
# Spring Boot Flex Instance Time-Series Performance Test
# Uses benchmarks/springboot/springboot-timeseries.yaml
# - 30s warmup (matches regular benchmark)
# - 5 runs per instance: timeseries1.log ~ timeseries5.log
# - 60 data points per run (10 minutes)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BASE_DIR/results/springboot-flex"
BENCHMARK_DIR="$BASE_DIR/benchmarks/springboot"

NAMESPACE="benchmark"
TOTAL_RUNS=5

# Flex instances only
FLEX_INSTANCES=(
    "c7i-flex.xlarge"
    "c8i-flex.xlarge"
    "m7i-flex.xlarge"
    "r8i-flex.xlarge"
)

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARN:${NC} $1"; }

# Create result directories
for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    mkdir -p "$RESULTS_DIR/$INSTANCE"
done

log "=== Spring Boot Flex Time-Series Test ==="
log "Using: benchmarks/springboot/springboot-timeseries.yaml"
log "Config: 30s warmup, 5 runs x 60 points (10min each)"
log "Result: results/springboot-flex/<instance>/timeseries1.log ~ timeseries5.log"
echo ""

# Phase 1: Deploy Spring Boot servers
log "Phase 1: Deploying Spring Boot servers..."

for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')

    cat "$BENCHMARK_DIR/springboot-server.yaml" | \
        sed "s/\${INSTANCE_TYPE}/${INSTANCE}/g" | \
        sed "s/INSTANCE_SAFE/${SAFE_NAME}/g" | \
        sed "s/ARCH/amd64/g" | \
        kubectl apply -f - 2>/dev/null || true

    log "Deployed server: $INSTANCE"
done

log "Waiting for servers to be ready (90s)..."
sleep 90

for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    kubectl wait --for=condition=ready pod -l app=springboot-server,instance-type="$INSTANCE" -n $NAMESPACE --timeout=300s 2>/dev/null || warn "Timeout waiting for $INSTANCE"
done

# Phase 2: Run 5 times
for RUN in $(seq 1 $TOTAL_RUNS); do
    log "========== Run $RUN/$TOTAL_RUNS =========="
    echo ""

    # Deploy all jobs for this run
    for INSTANCE in "${FLEX_INSTANCES[@]}"; do
        SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')

        cat "$BENCHMARK_DIR/springboot-timeseries.yaml" | \
            sed "s/\${INSTANCE_TYPE}/${INSTANCE}/g" | \
            sed "s/INSTANCE_SAFE/${SAFE_NAME}/g" | \
            sed "s/RUN_NUMBER/${RUN}/g" | \
            kubectl apply -f -

        log "Started: $INSTANCE (run $RUN)"
    done

    # Wait for all jobs to complete
    log "Waiting for run $RUN to complete (~11 minutes)..."

    for INSTANCE in "${FLEX_INSTANCES[@]}"; do
        SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
        JOB_NAME="springboot-timeseries-${SAFE_NAME}-${RUN}"
        LOG_FILE="$RESULTS_DIR/$INSTANCE/timeseries${RUN}.log"

        kubectl wait --for=condition=complete job/$JOB_NAME -n $NAMESPACE --timeout=900s 2>/dev/null || warn "Timeout: $INSTANCE run $RUN"

        POD=$(kubectl get pods -n $NAMESPACE -l job-name=$JOB_NAME --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
        if [ -n "$POD" ]; then
            kubectl logs -n $NAMESPACE "$POD" > "$LOG_FILE" 2>/dev/null
            log "Collected: $LOG_FILE"
        else
            warn "No pod found for $INSTANCE run $RUN"
        fi

        # Cleanup job after collecting logs
        kubectl delete job "$JOB_NAME" -n $NAMESPACE --ignore-not-found 2>/dev/null || true
    done

    echo ""
done

# Phase 3: Generate combined CSV
log "Phase 3: Generating combined CSV..."

CSV_FILE="$RESULTS_DIR/timeseries-all.csv"
echo "instance,run,elapsed_sec,requests_per_sec,avg_latency_ms,p99_latency_ms" > "$CSV_FILE"

for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    for RUN in $(seq 1 $TOTAL_RUNS); do
        LOG_FILE="$RESULTS_DIR/$INSTANCE/timeseries${RUN}.log"
        if [ -f "$LOG_FILE" ]; then
            grep -E "^[0-9]+," "$LOG_FILE" | while read line; do
                echo "$INSTANCE,$RUN,$line"
            done >> "$CSV_FILE"
        fi
    done
done

log "CSV: $CSV_FILE"

# Phase 4: Summary
log "Phase 4: Generating summary..."

SUMMARY_FILE="$RESULTS_DIR/timeseries-summary.txt"
cat > "$SUMMARY_FILE" << 'EOF'
===== Spring Boot Flex Time-Series Summary =====

Test Configuration:
  - Warmup: 30s (JIT compilation)
  - Runs: 5 (10 minutes each = 60 data points)
  - wrk settings: -t2 -c100 -d10s (matches regular benchmark)

EOF

for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    echo "=== $INSTANCE ===" >> "$SUMMARY_FILE"

    for RUN in $(seq 1 $TOTAL_RUNS); do
        LOG_FILE="$RESULTS_DIR/$INSTANCE/timeseries${RUN}.log"
        if [ -f "$LOG_FILE" ]; then
            RPS_VALUES=$(grep -E "^[0-9]+," "$LOG_FILE" | awk -F',' '{print $2}')
            if [ -n "$RPS_VALUES" ]; then
                AVG=$(echo "$RPS_VALUES" | awk '{sum+=$1} END {printf "%.0f", sum/NR}')
                MAX=$(echo "$RPS_VALUES" | sort -n | tail -1)
                MIN=$(echo "$RPS_VALUES" | sort -n | head -1)
                echo "  Run $RUN: avg=${AVG} req/s, min=${MIN}, max=${MAX}" >> "$SUMMARY_FILE"
            fi
        fi
    done
    echo "" >> "$SUMMARY_FILE"
done

cat "$SUMMARY_FILE"

# Phase 5: Cleanup option
echo ""
read -p "Cleanup servers? (y/N): " CLEANUP

if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
    log "Phase 5: Cleanup..."

    for INSTANCE in "${FLEX_INSTANCES[@]}"; do
        SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
        kubectl delete deployment "springboot-server-${SAFE_NAME}" -n $NAMESPACE --ignore-not-found 2>/dev/null || true
        kubectl delete service "springboot-server-${SAFE_NAME}" -n $NAMESPACE --ignore-not-found 2>/dev/null || true
    done

    log "Cleanup complete"
else
    log "Skipping cleanup - servers still running"
fi

log "=== Complete ==="
echo ""
echo "Results:"
ls -la "$RESULTS_DIR"/*/timeseries*.log 2>/dev/null | head -20
echo ""
echo "CSV: $CSV_FILE"
echo "Summary: $SUMMARY_FILE"
