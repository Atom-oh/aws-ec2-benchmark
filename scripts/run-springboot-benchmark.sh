#!/bin/bash
# Spring Boot Benchmark Runner
# Max 20 concurrent jobs, auto-collect results and delete completed jobs

# Don't use set -e - arithmetic operations return 1 when result is 0

BENCHMARK_TEMPLATE="/home/ec2-user/benchmark/benchmarks/springboot/springboot-benchmark.yaml"
RESULTS_DIR="/home/ec2-user/benchmark/results/springboot"
LOG_FILE="/home/ec2-user/benchmark/results/springboot-runner.log"
MAX_CONCURRENT=20

# All 51 instance types (xlarge)
INTEL_INSTANCES=(
  c5.xlarge c5d.xlarge c5n.xlarge
  c6i.xlarge c6id.xlarge c6in.xlarge
  c7i.xlarge c7i-flex.xlarge
  c8i.xlarge c8i-flex.xlarge
  m5.xlarge m5d.xlarge m5zn.xlarge
  m6i.xlarge m6id.xlarge m6idn.xlarge m6in.xlarge
  m7i.xlarge m7i-flex.xlarge
  m8i.xlarge
  r5.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge
  r6i.xlarge r6id.xlarge
  r7i.xlarge
  r8i.xlarge r8i-flex.xlarge
)

AMD_INSTANCES=(
  c5a.xlarge
  m5a.xlarge m5ad.xlarge
  r5a.xlarge r5ad.xlarge
)
# Note: c6a, c7a, m6a, m7a, r6a, r7a are not available in ap-northeast-2 (Seoul)

GRAVITON_INSTANCES=(
  c6g.xlarge c6gd.xlarge c6gn.xlarge
  c7g.xlarge c7gd.xlarge
  c8g.xlarge
  m6g.xlarge m6gd.xlarge
  m7g.xlarge m7gd.xlarge
  m8g.xlarge
  r6g.xlarge r6gd.xlarge
  r7g.xlarge r7gd.xlarge
  r8g.xlarge
)

ALL_INSTANCES=("${INTEL_INSTANCES[@]}" "${AMD_INSTANCES[@]}" "${GRAVITON_INSTANCES[@]}")

mkdir -p "$RESULTS_DIR"

# Track which instances have been started
declare -A STARTED
declare -A COMPLETED

# Check if a springboot-server exists for an instance
check_server_exists() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  kubectl get deployment -n benchmark "springboot-server-${safe_name}" &>/dev/null
}

# Start a benchmark job for an instance
start_benchmark() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')

  # Check if server exists
  if ! check_server_exists "$instance"; then
    echo "  [SKIP] No server for $instance"
    COMPLETED[$instance]=1
    return
  fi

  # Check if result already exists
  if [ -f "$RESULTS_DIR/${instance}.log" ]; then
    echo "  [SKIP] Result exists for $instance"
    COMPLETED[$instance]=1
    return
  fi

  echo "  [START] $instance"
  # Use | as sed delimiter to avoid conflict with instance name
  sed -e "s|\${INSTANCE_TYPE//./-}|${safe_name}|g" \
      -e "s|\${INSTANCE_TYPE}|${instance}|g" \
      "$BENCHMARK_TEMPLATE" | grep -A1000 "^---$" | tail -n +2 | kubectl apply -f - 2>/dev/null || true

  STARTED[$instance]=1
}

# Collect results and delete completed job
collect_and_delete() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="springboot-benchmark-${safe_name}"

  # Get logs
  echo "  [COLLECT] $instance"
  kubectl logs -n benchmark "job/${job_name}" > "$RESULTS_DIR/${instance}.log" 2>/dev/null || true

  # Delete job
  kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null

  COMPLETED[$instance]=1
  unset STARTED[$instance]
}

echo "===== Spring Boot Benchmark Runner ====="
echo "Total instances: ${#ALL_INSTANCES[@]}"
echo "Max concurrent: $MAX_CONCURRENT"
echo "Results dir: $RESULTS_DIR"
echo ""

# Main loop
instance_idx=0
while true; do
  # Check for completed jobs and collect results
  for instance in "${!STARTED[@]}"; do
    safe_name=$(echo "$instance" | tr '.' '-')
    job_name="springboot-benchmark-${safe_name}"

    # Check if job is complete (successful or failed)
    status=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
    failed=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || echo "")

    if [ "$status" = "True" ] || [ "$failed" = "True" ]; then
      collect_and_delete "$instance"
    fi
  done

  # Count running jobs
  running=${#STARTED[@]}
  completed=${#COMPLETED[@]}

  echo "[Status] Running: $running, Completed: $completed/${#ALL_INSTANCES[@]}"

  # Start new jobs if under limit
  while [ $running -lt $MAX_CONCURRENT ] && [ $instance_idx -lt ${#ALL_INSTANCES[@]} ]; do
    instance=${ALL_INSTANCES[$instance_idx]}
    ((instance_idx++))

    # Skip if already completed
    if [ -n "${COMPLETED[$instance]}" ]; then
      continue
    fi

    start_benchmark "$instance"
    ((running++)) || true
  done

  # Check if all done
  if [ $completed -eq ${#ALL_INSTANCES[@]} ]; then
    echo ""
    echo "===== All benchmarks completed! ====="
    break
  fi

  # Wait before next check
  sleep 15
done

# List results
echo ""
echo "=== Results ==="
ls -la "$RESULTS_DIR"/*.log 2>/dev/null | wc -l
echo "log files collected"
