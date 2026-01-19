#!/bin/bash
# System Benchmark Runner
# Runs sysbench-cpu, sysbench-memory, stress-ng, fio-disk, iperf3
# Usage: ./run-system-benchmark.sh <benchmark-type> [run-number]
# benchmark-type: sysbench-cpu, sysbench-memory, stress-ng, fio-disk, iperf3

cd /home/ec2-user/benchmark

BENCHMARK_TYPE=${1:-sysbench-cpu}
RUN=${2:-1}
TEMPLATE="benchmarks/system/${BENCHMARK_TYPE}.yaml"
RESULTS_DIR="results/${BENCHMARK_TYPE}"
MAX_CONCURRENT=20

# All 51 instance types
INSTANCES=(
  c8i.xlarge c8i-flex.xlarge m8i.xlarge r8i.xlarge r8i-flex.xlarge
  c8g.xlarge m8g.xlarge r8g.xlarge
  c7i.xlarge c7i-flex.xlarge m7i.xlarge m7i-flex.xlarge r7i.xlarge
  c7g.xlarge c7gd.xlarge m7g.xlarge m7gd.xlarge r7g.xlarge r7gd.xlarge
  c6i.xlarge c6id.xlarge c6in.xlarge m6i.xlarge m6id.xlarge m6in.xlarge m6idn.xlarge r6i.xlarge r6id.xlarge
  c6g.xlarge c6gd.xlarge c6gn.xlarge m6g.xlarge m6gd.xlarge r6g.xlarge r6gd.xlarge
  c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge
  m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge
  r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge
)

if [ ! -f "$TEMPLATE" ]; then
  echo "Template not found: $TEMPLATE"
  exit 1
fi

mkdir -p "$RESULTS_DIR"

echo "===== System Benchmark Runner ====="
echo "Type: $BENCHMARK_TYPE"
echo "Run: $RUN"
echo "Total instances: ${#INSTANCES[@]}"
echo "Max concurrent: $MAX_CONCURRENT"
echo "Start: $(date)"
echo ""

declare -A RUNNING
declare -A COMPLETED

# Get architecture for instance
get_arch() {
  local instance=$1
  if [[ "$instance" =~ g\. ]] || [[ "$instance" =~ gd\. ]] || [[ "$instance" =~ gn\. ]]; then
    echo "arm64"
  else
    echo "amd64"
  fi
}

# Deploy benchmark job
deploy_job() {
  local instance=$1
  local safe=$(echo "$instance" | tr '.' '-')
  local arch=$(get_arch "$instance")

  sed -e "s/INSTANCE_SAFE/${safe}/g" \
      -e "s/\${INSTANCE_TYPE}/${instance}/g" \
      -e "s/INSTANCE_TYPE/${instance}/g" \
      -e "s/ARCH/${arch}/g" \
      "$TEMPLATE" | kubectl apply -f - 2>/dev/null
}

# Check if job is complete
is_job_complete() {
  local instance=$1
  local safe=$(echo "$instance" | tr '.' '-')
  local job_name="${BENCHMARK_TYPE}-${safe}-run${RUN}"

  # Try different job name patterns
  for pattern in "$job_name" "${BENCHMARK_TYPE}-${safe}"; do
    local status=$(kubectl get job -n benchmark "$pattern" -o jsonpath='{.status.succeeded}' 2>/dev/null)
    if [ "$status" = "1" ]; then
      return 0
    fi
  done
  return 1
}

# Collect log and cleanup
collect_and_cleanup() {
  local instance=$1
  local safe=$(echo "$instance" | tr '.' '-')
  local job_name="${BENCHMARK_TYPE}-${safe}-run${RUN}"

  mkdir -p "${RESULTS_DIR}/${instance}"

  # Try different job name patterns
  for pattern in "$job_name" "${BENCHMARK_TYPE}-${safe}"; do
    local pod=$(kubectl get pods -n benchmark -l "job-name=${pattern}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -n "$pod" ]; then
      kubectl logs -n benchmark "$pod" > "${RESULTS_DIR}/${instance}/run${RUN}.log" 2>/dev/null
      kubectl delete job -n benchmark "$pattern" 2>/dev/null
      echo "  [OK] $instance run${RUN} - log collected, job cleaned"
      return 0
    fi
  done
  return 1
}

# Start instance
start_instance() {
  local instance=$1
  local safe=$(echo "$instance" | tr '.' '-')

  # Check if result already exists
  if [ -f "${RESULTS_DIR}/${instance}/run${RUN}.log" ]; then
    echo "  [SKIP] $instance run${RUN} - result exists"
    COMPLETED[$instance]=1
    return
  fi

  echo "  [START] $instance"
  deploy_job "$instance"
  RUNNING[$instance]=1
}

# Main loop
while true; do
  running_count=0
  completed_count=0

  # Count completed
  for instance in "${INSTANCES[@]}"; do
    if [ "${COMPLETED[$instance]}" = "1" ]; then
      ((completed_count++))
    fi
  done

  # Check running jobs
  for instance in "${!RUNNING[@]}"; do
    if [ "${RUNNING[$instance]}" = "1" ]; then
      if is_job_complete "$instance"; then
        collect_and_cleanup "$instance"
        COMPLETED[$instance]=1
        unset RUNNING[$instance]
        ((completed_count++))
      else
        ((running_count++))
      fi
    fi
  done

  # Start new jobs if under limit
  for instance in "${INSTANCES[@]}"; do
    if [ "${COMPLETED[$instance]}" != "1" ] && [ "${RUNNING[$instance]}" != "1" ]; then
      if [ $running_count -lt $MAX_CONCURRENT ]; then
        start_instance "$instance"
        if [ "${COMPLETED[$instance]}" != "1" ]; then
          ((running_count++))
        fi
      fi
    fi
  done

  echo "[Status] Running: $running_count, Completed: $completed_count/${#INSTANCES[@]}"

  # Check if all done
  if [ $completed_count -eq ${#INSTANCES[@]} ]; then
    break
  fi

  sleep 10
done

echo ""
echo "===== Benchmark completed! ====="
echo "End: $(date)"
echo ""
echo "=== Results ==="
ls "${RESULTS_DIR}"/*/run${RUN}.log 2>/dev/null | wc -l
echo "log files collected for run${RUN}"
