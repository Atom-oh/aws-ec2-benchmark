#!/bin/bash
# Spring Boot wrk Benchmark - Multiple Runs
# Runs wrk benchmark 5 times per instance
# Saves to springboot/<instance>/wrk1.log format

# Don't use set -e
BENCHMARK_TEMPLATE="/home/ec2-user/benchmark/benchmarks/springboot/springboot-benchmark.yaml"
SERVER_TEMPLATE="/home/ec2-user/benchmark/benchmarks/springboot/springboot-server.yaml"
RESULTS_BASE="/home/ec2-user/benchmark/results/springboot"
MAX_CONCURRENT=20
NUM_RUNS=5

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

# Create result directories
for instance in "${ALL_INSTANCES[@]}"; do
  mkdir -p "$RESULTS_BASE/$instance"
done

declare -A STARTED
declare -A COMPLETED

check_server_exists() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  kubectl get deployment -n benchmark "springboot-server-${safe_name}" &>/dev/null
}

deploy_server() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')

  if check_server_exists "$instance"; then
    return
  fi

  echo "  [DEPLOY] springboot-server-${safe_name}"
  cat "$SERVER_TEMPLATE" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s/\${INSTANCE_TYPE}/${instance}/g" | \
      kubectl apply -f - 2>/dev/null || true
}

check_server_ready() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  local deploy_name="springboot-server-${safe_name}"
  local ready=$(kubectl get deployment -n benchmark "$deploy_name" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  [ "$ready" = "1" ]
}

start_benchmark() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="springboot-wrk-${safe_name}-run${run_num}"

  # Check if result already exists
  if [ -f "$RESULTS_BASE/$instance/wrk${run_num}.log" ]; then
    echo "  [SKIP] Result exists for $instance run${run_num}"
    return 1
  fi

  # Check if server is ready
  if ! check_server_ready "$instance"; then
    echo "  [WAIT] Server not ready for $instance"
    return 1
  fi

  echo "  [START] $instance run${run_num}"
  cat "$BENCHMARK_TEMPLATE" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s/\${INSTANCE_TYPE}/${instance}/g" | \
      grep -A1000 "^---$" | tail -n +2 | \
      sed "s/name: springboot-benchmark-${safe_name}/name: ${job_name}/g" | \
      kubectl apply -f - 2>/dev/null || true

  STARTED["${instance}_${run_num}"]=1
}

collect_and_delete() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="springboot-wrk-${safe_name}-run${run_num}"

  echo "  [COLLECT] $instance run${run_num}"
  kubectl logs -n benchmark "job/${job_name}" > "$RESULTS_BASE/$instance/wrk${run_num}.log" 2>/dev/null || true
  kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null

  COMPLETED["${instance}_${run_num}"]=1
  unset STARTED["${instance}_${run_num}"]
}

echo "===== Spring Boot wrk Benchmark - Multiple Runs ====="
echo "Total instances: ${#ALL_INSTANCES[@]}"
echo "Runs per instance: $NUM_RUNS"
echo "Max concurrent: $MAX_CONCURRENT"
echo "Results dir: $RESULTS_BASE/<instance>/wrk<N>.log"
echo ""

# Phase 1: Deploy all servers
echo "=== Phase 1: Deploying Spring Boot servers ==="
for instance in "${ALL_INSTANCES[@]}"; do
  deploy_server "$instance"
done
echo "Waiting for servers to be ready..."
sleep 30

# Wait for servers to be ready
echo "=== Phase 2: Waiting for servers to be ready ==="
max_wait=300
wait_time=0
while [ $wait_time -lt $max_wait ]; do
  ready_count=0
  for instance in "${ALL_INSTANCES[@]}"; do
    if check_server_ready "$instance"; then
      ((ready_count++)) || true
    fi
  done
  echo "[$(date '+%H:%M:%S')] Ready servers: $ready_count/${#ALL_INSTANCES[@]}"
  if [ $ready_count -eq ${#ALL_INSTANCES[@]} ]; then
    echo "All servers ready!"
    break
  fi
  sleep 15
  ((wait_time+=15)) || true
done

# Phase 3: Run benchmarks
total_jobs=$((${#ALL_INSTANCES[@]} * NUM_RUNS))
echo ""
echo "=== Phase 3: Running $NUM_RUNS iterations per instance ==="

while true; do
  # Check for completed jobs
  for key in "${!STARTED[@]}"; do
    instance=$(echo "$key" | cut -d'_' -f1)
    run_num=$(echo "$key" | cut -d'_' -f2)
    safe_name=$(echo "$instance" | tr '.' '-')
    job_name="springboot-wrk-${safe_name}-run${run_num}"

    status=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
    failed=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || echo "")

    if [ "$status" = "True" ] || [ "$failed" = "True" ]; then
      collect_and_delete "$instance" "$run_num"
    fi
  done

  running=${#STARTED[@]}
  completed=${#COMPLETED[@]}
  echo "[Status] Running: $running, Completed: $completed/$total_jobs"

  # Start new jobs
  for instance in "${ALL_INSTANCES[@]}"; do
    for run_num in $(seq 1 $NUM_RUNS); do
      key="${instance}_${run_num}"

      # Skip if already running or completed
      if [ -n "${STARTED[$key]}" ] || [ -n "${COMPLETED[$key]}" ]; then
        continue
      fi

      # Stop if at max concurrent
      if [ $running -ge $MAX_CONCURRENT ]; then
        break 2
      fi

      # Try to start
      if start_benchmark "$instance" "$run_num"; then
        ((running++)) || true
      fi
    done
  done

  # Check if all done
  if [ $completed -eq $total_jobs ]; then
    echo ""
    echo "===== All benchmarks completed! ====="
    break
  fi

  sleep 15
done

# Summary
echo ""
echo "=== Results Summary ==="
for instance in "${ALL_INSTANCES[@]}"; do
  count=$(ls -1 "$RESULTS_BASE/$instance"/wrk*.log 2>/dev/null | wc -l)
  echo "$instance: $count runs"
done | head -20
echo "..."
echo "Total: $(find "$RESULTS_BASE" -name "wrk*.log" | wc -l) log files"
