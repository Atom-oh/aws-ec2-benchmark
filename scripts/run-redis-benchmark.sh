#!/bin/bash
# Redis Benchmark Runner
# Max 20 concurrent jobs, auto-collect results and delete completed jobs

BENCHMARK_TEMPLATE="/home/ec2-user/benchmark/benchmarks/redis/redis-benchmark.yaml"
SERVER_TEMPLATE="/home/ec2-user/benchmark/benchmarks/redis/redis-server.yaml"
RESULTS_DIR="/home/ec2-user/benchmark/results/redis"
MAX_CONCURRENT=20

# All available instance types (xlarge)
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

declare -A STARTED
declare -A COMPLETED

check_server_exists() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  kubectl get deployment -n benchmark "redis-server-${safe_name}" &>/dev/null
}

deploy_server() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')

  if check_server_exists "$instance"; then
    return
  fi

  echo "  [DEPLOY] redis-server-${safe_name}"
  sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
      -e "s|\${INSTANCE_TYPE}|${instance}|g" \
      "$SERVER_TEMPLATE" | kubectl apply -f - 2>/dev/null || true
}

start_benchmark() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')

  if [ -f "$RESULTS_DIR/${instance}.log" ]; then
    echo "  [SKIP] Result exists for $instance"
    COMPLETED[$instance]=1
    return
  fi

  if ! check_server_exists "$instance"; then
    deploy_server "$instance"
    echo "  [WAIT] Server deploying for $instance"
    return 1
  fi

  # Check if server pod is ready
  ready=$(kubectl get pods -n benchmark -l app=redis-server,instance-type="${instance}" -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
  if [ "$ready" != "true" ]; then
    echo "  [WAIT] Server not ready for $instance"
    return 1
  fi

  echo "  [START] $instance"
  cat "$BENCHMARK_TEMPLATE" | \
      sed "s/JOB_NAME/redis-benchmark-${safe_name}/g" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s/\${INSTANCE_TYPE}/${instance}/g" | \
      kubectl apply -f - 2>/dev/null || true

  STARTED[$instance]=1
}

collect_and_delete() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="redis-benchmark-${safe_name}"

  echo "  [COLLECT] $instance"
  kubectl logs -n benchmark "job/${job_name}" > "$RESULTS_DIR/${instance}.log" 2>/dev/null || true

  kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null

  COMPLETED[$instance]=1
  unset STARTED[$instance]
}

echo "===== Redis Benchmark Runner ====="
echo "Total instances: ${#ALL_INSTANCES[@]}"
echo "Max concurrent: $MAX_CONCURRENT"
echo "Results dir: $RESULTS_DIR"
echo ""

# Deploy all servers first
echo "=== Deploying Redis servers ==="
for instance in "${ALL_INSTANCES[@]}"; do
  deploy_server "$instance"
done
echo "Waiting for servers to be ready..."
sleep 30

# Main loop - iterate through all instances each round
while true; do
  # Check for completed jobs and collect results
  for instance in "${!STARTED[@]}"; do
    safe_name=$(echo "$instance" | tr '.' '-')
    job_name="redis-benchmark-${safe_name}"

    status=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
    failed=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || echo "")

    if [ "$status" = "True" ] || [ "$failed" = "True" ]; then
      collect_and_delete "$instance"
    fi
  done

  running=${#STARTED[@]}
  completed=${#COMPLETED[@]}

  echo "[Status] Running: $running, Completed: $completed/${#ALL_INSTANCES[@]}"

  # Try to start jobs for any instance not yet started or completed
  for instance in "${ALL_INSTANCES[@]}"; do
    # Skip if already running or completed
    if [ -n "${STARTED[$instance]}" ] || [ -n "${COMPLETED[$instance]}" ]; then
      continue
    fi

    # Stop if at max concurrent
    if [ $running -ge $MAX_CONCURRENT ]; then
      break
    fi

    # Try to start (returns 1 if server not ready)
    if start_benchmark "$instance"; then
      ((running++)) || true
    fi
  done

  if [ $completed -eq ${#ALL_INSTANCES[@]} ]; then
    echo ""
    echo "===== All benchmarks completed! ====="
    break
  fi

  sleep 15
done

echo ""
echo "=== Results ==="
ls -la "$RESULTS_DIR"/*.log 2>/dev/null | wc -l
echo "log files collected"
