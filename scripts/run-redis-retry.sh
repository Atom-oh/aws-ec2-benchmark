#!/bin/bash
# Redis Benchmark - Retry missing runs
# Identifies and runs only missing test cases

cd /home/ec2-user/benchmark/results/redis

BENCHMARK_TEMPLATE="/home/ec2-user/benchmark/benchmarks/redis/redis-benchmark.yaml"
MAX_CONCURRENT=20
NUM_RUNS=5

declare -A STARTED
declare -A COMPLETED

# Find missing runs
declare -A MISSING_RUNS

for dir in */; do
  instance="${dir%/}"
  for run in $(seq 1 $NUM_RUNS); do
    if [ ! -f "${instance}/run${run}.log" ]; then
      MISSING_RUNS["${instance}_${run}"]=1
    fi
  done
done

TOTAL_MISSING=${#MISSING_RUNS[@]}

if [ $TOTAL_MISSING -eq 0 ]; then
  echo "All runs complete! Nothing to retry."
  exit 0
fi

echo "===== Redis Benchmark - Retry Missing Runs ====="
echo "Missing runs: $TOTAL_MISSING"
echo ""

# Functions
check_server_ready() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  local ready=$(kubectl get pods -n benchmark -l "app=redis-server,instance-type=${instance}" -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
  [ "$ready" = "true" ]
}

start_benchmark() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="redis-benchmark-${safe_name}-run${run_num}"

  # Check if already exists
  if [ -f "${instance}/run${run_num}.log" ]; then
    return 1
  fi

  # Check if server is ready
  if ! check_server_ready "$instance"; then
    echo "  [WAIT] Server not ready: $instance"
    return 1
  fi

  echo "  [START] $instance run${run_num}"
  cat "$BENCHMARK_TEMPLATE" | \
      sed "s/JOB_NAME/${job_name}/g" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s/\${INSTANCE_TYPE}/${instance}/g" | \
      kubectl apply -f - 2>/dev/null || true

  STARTED["${instance}_${run_num}"]=1
}

collect_and_delete() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="redis-benchmark-${safe_name}-run${run_num}"

  echo "  [COLLECT] $instance run${run_num}"
  mkdir -p "$instance"
  kubectl logs -n benchmark "job/${job_name}" > "${instance}/run${run_num}.log" 2>/dev/null || true
  kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null

  # Verify no connection errors
  if grep -qi "connection refused\|Could not connect\|Error:\|Connection reset\|ERR " "${instance}/run${run_num}.log" 2>/dev/null; then
    echo "    [ERROR] Log has connection errors, removing"
    rm -f "${instance}/run${run_num}.log"
    return 1
  fi

  COMPLETED["${instance}_${run_num}"]=1
  unset STARTED["${instance}_${run_num}"]
  unset MISSING_RUNS["${instance}_${run_num}"]
}

# Main loop
while true; do
  # Check for completed jobs
  for key in "${!STARTED[@]}"; do
    instance=$(echo "$key" | cut -d'_' -f1)
    run_num=$(echo "$key" | cut -d'_' -f2)
    safe_name=$(echo "$instance" | tr '.' '-')
    job_name="redis-benchmark-${safe_name}-run${run_num}"

    status=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
    failed=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || echo "")

    if [ "$status" = "True" ]; then
      collect_and_delete "$instance" "$run_num"
    elif [ "$failed" = "True" ]; then
      echo "  [FAILED] $instance run${run_num}"
      kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null
      unset STARTED["${instance}_${run_num}"]
    fi
  done

  running=${#STARTED[@]}
  completed=${#COMPLETED[@]}
  remaining=${#MISSING_RUNS[@]}

  echo "[Status] Running: $running, Completed: $completed, Remaining: $remaining"

  # Start new jobs
  for key in "${!MISSING_RUNS[@]}"; do
    # Skip if already running or completed
    if [ -n "${STARTED[$key]}" ] || [ -n "${COMPLETED[$key]}" ]; then
      continue
    fi

    # Stop if at max concurrent
    if [ $running -ge $MAX_CONCURRENT ]; then
      break
    fi

    instance=$(echo "$key" | cut -d'_' -f1)
    run_num=$(echo "$key" | cut -d'_' -f2)

    if start_benchmark "$instance" "$run_num"; then
      ((running++)) || true
    fi
  done

  # Check if all done
  if [ $remaining -eq 0 ]; then
    echo ""
    echo "===== All retry runs completed! ====="
    break
  fi

  sleep 15
done

echo ""
echo "=== Summary ==="
find . -name "run*.log" | wc -l
echo "total log files"
