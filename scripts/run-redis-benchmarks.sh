#!/bin/bash
# Run Redis Benchmarks - 51 instances x 5 runs = 255 benchmarks
# Uses redis-benchmark.yaml (client on dedicated benchmark-client node)

set -e

BENCHMARK_DIR="/home/ec2-user/benchmark"
RESULTS_DIR="${BENCHMARK_DIR}/results/redis"
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
PARALLEL_JOBS=10

log() { echo "[$(date '+%H:%M:%S')] $1"; }

# Create results directories
for inst in "${INSTANCES[@]}"; do
  mkdir -p "${RESULTS_DIR}/${inst}"
done

TOTAL=$((${#INSTANCES[@]} * NUM_RUNS))
log "Starting Redis Benchmarks: ${#INSTANCES[@]} instances x ${NUM_RUNS} runs = ${TOTAL} total"

# Create all benchmark jobs
for RUN in $(seq 1 $NUM_RUNS); do
  for INSTANCE in "${INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    JOB_NAME="redis-benchmark-${SAFE_NAME}-run${RUN}"
    LOG_FILE="${RESULTS_DIR}/${INSTANCE}/run${RUN}.log"

    # Skip if log already exists
    if [ -f "${LOG_FILE}" ] && [ -s "${LOG_FILE}" ]; then
      log "Skip ${INSTANCE} run${RUN} (already exists)"
      continue
    fi

    # Wait if too many jobs running
    while true; do
      ACTIVE=$(kubectl get jobs -n benchmark -l benchmark=redis-benchmark -o jsonpath='{range .items[?(@.status.active==1)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | wc -l)
      if [ "$ACTIVE" -lt "$PARALLEL_JOBS" ]; then
        break
      fi
      sleep 5
    done

    # Delete old job if exists
    kubectl delete job "${JOB_NAME}" -n benchmark --ignore-not-found=true &>/dev/null

    # Create job
    sed -e "s/JOB_NAME/${JOB_NAME}/g" \
        -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
        "${BENCHMARK_TEMPLATE}" | kubectl apply -f - &>/dev/null

    log "Started ${JOB_NAME}"
  done
done

log "All jobs submitted. Waiting for completion..."

# Wait for all jobs to complete and collect logs
while true; do
  RUNNING=$(kubectl get jobs -n benchmark -l benchmark=redis-benchmark -o jsonpath='{range .items[?(@.status.active==1)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | wc -l)
  SUCCEEDED=$(kubectl get jobs -n benchmark -l benchmark=redis-benchmark -o jsonpath='{range .items[?(@.status.succeeded==1)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | wc -l)

  log "Running: ${RUNNING}, Completed: ${SUCCEEDED}/${TOTAL}"

  if [ "$RUNNING" -eq 0 ]; then
    break
  fi

  # Collect completed logs
  for INSTANCE in "${INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    for RUN in $(seq 1 $NUM_RUNS); do
      JOB_NAME="redis-benchmark-${SAFE_NAME}-run${RUN}"
      LOG_FILE="${RESULTS_DIR}/${INSTANCE}/run${RUN}.log"

      if [ ! -f "${LOG_FILE}" ] || [ ! -s "${LOG_FILE}" ]; then
        STATUS=$(kubectl get job "${JOB_NAME}" -n benchmark -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
        if [ "$STATUS" = "True" ]; then
          POD=$(kubectl get pods -n benchmark -l job-name="${JOB_NAME}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
          if [ -n "$POD" ]; then
            kubectl logs -n benchmark "${POD}" > "${LOG_FILE}" 2>/dev/null
            log "Collected ${INSTANCE} run${RUN}"
          fi
        fi
      fi
    done
  done

  sleep 15
done

# Final collection
log "Final log collection..."
for INSTANCE in "${INSTANCES[@]}"; do
  SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
  for RUN in $(seq 1 $NUM_RUNS); do
    JOB_NAME="redis-benchmark-${SAFE_NAME}-run${RUN}"
    LOG_FILE="${RESULTS_DIR}/${INSTANCE}/run${RUN}.log"

    if [ ! -f "${LOG_FILE}" ] || [ ! -s "${LOG_FILE}" ]; then
      POD=$(kubectl get pods -n benchmark -l job-name="${JOB_NAME}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
      if [ -n "$POD" ]; then
        kubectl logs -n benchmark "${POD}" > "${LOG_FILE}" 2>/dev/null
        log "Collected ${INSTANCE} run${RUN}"
      fi
    fi
  done
done

# Summary
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
log "Collected: ${COLLECTED}/${TOTAL} logs"
log "Results: ${RESULTS_DIR}"
log "=========================================="
