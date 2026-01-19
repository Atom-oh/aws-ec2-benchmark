#!/bin/bash
# Redis Full Benchmark - 51 instances x 5 runs
# Using redis-benchmark.yaml (client on dedicated c6in.8xlarge node)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BENCHMARK_DIR="/home/ec2-user/benchmark"
RESULTS_DIR="${BENCHMARK_DIR}/results/redis"
SERVER_TEMPLATE="${BENCHMARK_DIR}/benchmarks/redis/redis-server.yaml"
BENCHMARK_TEMPLATE="${BENCHMARK_DIR}/benchmarks/redis/redis-benchmark.yaml"

# All 51 instances
INSTANCES=(
  c8i.xlarge c8i-flex.xlarge c8g.xlarge
  c7i.xlarge c7i-flex.xlarge c7g.xlarge c7gd.xlarge
  c6i.xlarge c6id.xlarge c6in.xlarge c6g.xlarge c6gd.xlarge c6gn.xlarge
  c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge
  m8i.xlarge m8g.xlarge
  m7i.xlarge m7i-flex.xlarge m7g.xlarge m7gd.xlarge
  m6i.xlarge m6id.xlarge m6in.xlarge m6idn.xlarge m6g.xlarge m6gd.xlarge
  m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge
  r8i.xlarge r8i-flex.xlarge r8g.xlarge
  r7i.xlarge r7g.xlarge r7gd.xlarge
  r6i.xlarge r6id.xlarge r6g.xlarge r6gd.xlarge
  r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge
)

NUM_RUNS=5
PARALLEL_SERVERS=51  # Deploy all servers at once
PARALLEL_BENCHMARKS=10  # Run 10 benchmarks in parallel

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARN:${NC} $1"; }
error() { echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"; }

# Create results directories
mkdir -p "${RESULTS_DIR}"
for inst in "${INSTANCES[@]}"; do
  mkdir -p "${RESULTS_DIR}/${inst}"
done

# ========== PHASE 1: Deploy Redis ConfigMap ==========
log "Phase 1: Deploying Redis ConfigMap..."
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: benchmark
data:
  redis.conf: |
    bind 0.0.0.0
    port 6379
    protected-mode no
    maxmemory 0
    tcp-backlog 511
    tcp-keepalive 300
    loglevel notice
    save ""
    appendonly no
    io-threads 2
    io-threads-do-reads yes
EOF

# ========== PHASE 2: Deploy All Redis Servers ==========
log "Phase 2: Deploying ${#INSTANCES[@]} Redis servers..."

for INSTANCE in "${INSTANCES[@]}"; do
  SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')

  # Check if already exists
  if kubectl get deployment "redis-server-${SAFE_NAME}" -n benchmark &>/dev/null; then
    log "  Redis server for ${INSTANCE} already exists, skipping..."
    continue
  fi

  # Deploy server
  sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
      -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      "${SERVER_TEMPLATE}" | grep -v "^apiVersion: v1" | grep -v "^kind: ConfigMap" | \
      sed '/^metadata:/,/^---/{ /name: redis-config/,/^---/d }' | \
      kubectl apply -f - 2>/dev/null || true

  log "  Deployed redis-server-${SAFE_NAME}"
done

# ========== PHASE 3: Wait for All Redis Servers ==========
log "Phase 3: Waiting for all Redis servers to be ready..."

READY_COUNT=0
MAX_WAIT=600  # 10 minutes
START_TIME=$(date +%s)

while [ $READY_COUNT -lt ${#INSTANCES[@]} ]; do
  READY_COUNT=0
  for INSTANCE in "${INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    STATUS=$(kubectl get pods -n benchmark -l "app=redis-server,instance-type=${INSTANCE}" -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
    if [ "$STATUS" = "Running" ]; then
      READY_COUNT=$((READY_COUNT + 1))
    fi
  done

  ELAPSED=$(($(date +%s) - START_TIME))
  log "  Ready: ${READY_COUNT}/${#INSTANCES[@]} (elapsed: ${ELAPSED}s)"

  if [ $ELAPSED -gt $MAX_WAIT ]; then
    error "Timeout waiting for Redis servers!"
    exit 1
  fi

  if [ $READY_COUNT -lt ${#INSTANCES[@]} ]; then
    sleep 10
  fi
done

log "All ${#INSTANCES[@]} Redis servers are ready!"

# ========== PHASE 4: Run Benchmarks ==========
log "Phase 4: Running benchmarks (${NUM_RUNS} runs per instance)..."

# Function to run a single benchmark
run_benchmark() {
  local INSTANCE=$1
  local RUN=$2
  local SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
  local JOB_NAME="redis-benchmark-${SAFE_NAME}-run${RUN}"
  local LOG_FILE="${RESULTS_DIR}/${INSTANCE}/run${RUN}.log"

  # Delete old job if exists
  kubectl delete job "${JOB_NAME}" -n benchmark --ignore-not-found=true &>/dev/null

  # Create benchmark job
  sed -e "s/JOB_NAME/${JOB_NAME}/g" \
      -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
      -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      "${BENCHMARK_TEMPLATE}" | kubectl apply -f - &>/dev/null

  # Wait for completion
  local MAX_WAIT=300
  local ELAPSED=0
  while [ $ELAPSED -lt $MAX_WAIT ]; do
    STATUS=$(kubectl get job "${JOB_NAME}" -n benchmark -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
    FAILED=$(kubectl get job "${JOB_NAME}" -n benchmark -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null)

    if [ "$STATUS" = "True" ]; then
      # Collect logs
      POD=$(kubectl get pods -n benchmark -l job-name="${JOB_NAME}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
      kubectl logs -n benchmark "${POD}" > "${LOG_FILE}" 2>/dev/null
      echo "OK:${INSTANCE}:run${RUN}"
      return 0
    elif [ "$FAILED" = "True" ]; then
      echo "FAILED:${INSTANCE}:run${RUN}"
      return 1
    fi

    sleep 5
    ELAPSED=$((ELAPSED + 5))
  done

  echo "TIMEOUT:${INSTANCE}:run${RUN}"
  return 1
}

export -f run_benchmark
export RESULTS_DIR BENCHMARK_TEMPLATE

# Create job list
JOB_LIST_FILE=$(mktemp)
for RUN in $(seq 1 $NUM_RUNS); do
  for INSTANCE in "${INSTANCES[@]}"; do
    echo "${INSTANCE} ${RUN}"
  done
done > "${JOB_LIST_FILE}"

TOTAL_JOBS=$((${#INSTANCES[@]} * NUM_RUNS))
log "Total benchmark jobs: ${TOTAL_JOBS}"

# Run benchmarks in parallel
COMPLETED=0
FAILED=0

# Process in batches
while IFS=' ' read -r INSTANCE RUN; do
  # Check active jobs
  while true; do
    ACTIVE=$(kubectl get jobs -n benchmark -l benchmark=redis-benchmark -o jsonpath='{range .items[?(@.status.active==1)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | wc -l)
    if [ "$ACTIVE" -lt "$PARALLEL_BENCHMARKS" ]; then
      break
    fi
    sleep 5
  done

  SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
  JOB_NAME="redis-benchmark-${SAFE_NAME}-run${RUN}"
  LOG_FILE="${RESULTS_DIR}/${INSTANCE}/run${RUN}.log"

  # Skip if log already exists
  if [ -f "${LOG_FILE}" ] && [ -s "${LOG_FILE}" ]; then
    log "  Skip ${INSTANCE} run${RUN} (already exists)"
    COMPLETED=$((COMPLETED + 1))
    continue
  fi

  # Delete old job
  kubectl delete job "${JOB_NAME}" -n benchmark --ignore-not-found=true &>/dev/null

  # Create job
  sed -e "s/JOB_NAME/${JOB_NAME}/g" \
      -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
      -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      "${BENCHMARK_TEMPLATE}" | kubectl apply -f - &>/dev/null

  log "  Started ${JOB_NAME} ($((COMPLETED + 1))/${TOTAL_JOBS})"

done < "${JOB_LIST_FILE}"

rm -f "${JOB_LIST_FILE}"

# Wait for all jobs to complete
log "Waiting for all benchmark jobs to complete..."

while true; do
  RUNNING=$(kubectl get jobs -n benchmark -l benchmark=redis-benchmark -o jsonpath='{range .items[?(@.status.active==1)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | wc -l)
  SUCCEEDED=$(kubectl get jobs -n benchmark -l benchmark=redis-benchmark -o jsonpath='{range .items[?(@.status.succeeded==1)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | wc -l)

  log "  Running: ${RUNNING}, Completed: ${SUCCEEDED}/${TOTAL_JOBS}"

  if [ "$RUNNING" -eq 0 ]; then
    break
  fi

  sleep 15
done

# ========== PHASE 5: Collect Logs ==========
log "Phase 5: Collecting logs..."

for INSTANCE in "${INSTANCES[@]}"; do
  SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
  for RUN in $(seq 1 $NUM_RUNS); do
    JOB_NAME="redis-benchmark-${SAFE_NAME}-run${RUN}"
    LOG_FILE="${RESULTS_DIR}/${INSTANCE}/run${RUN}.log"

    if [ ! -f "${LOG_FILE}" ] || [ ! -s "${LOG_FILE}" ]; then
      POD=$(kubectl get pods -n benchmark -l job-name="${JOB_NAME}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
      if [ -n "$POD" ]; then
        kubectl logs -n benchmark "${POD}" > "${LOG_FILE}" 2>/dev/null
        log "  Collected ${INSTANCE} run${RUN}"
      fi
    fi
  done
done

# ========== PHASE 6: Summary ==========
log "Phase 6: Summary..."

COLLECTED=0
for INSTANCE in "${INSTANCES[@]}"; do
  for RUN in $(seq 1 $NUM_RUNS); do
    LOG_FILE="${RESULTS_DIR}/${INSTANCE}/run${RUN}.log"
    if [ -f "${LOG_FILE}" ] && [ -s "${LOG_FILE}" ]; then
      COLLECTED=$((COLLECTED + 1))
    fi
  done
done

log "=========================================="
log "Redis Benchmark Complete!"
log "Total: ${TOTAL_JOBS} benchmarks"
log "Collected: ${COLLECTED} logs"
log "Results: ${RESULTS_DIR}"
log "=========================================="
