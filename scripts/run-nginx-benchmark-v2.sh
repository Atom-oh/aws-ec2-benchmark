#!/bin/bash
# Nginx Benchmark Runner v2
# Efficient: Server+Benchmark pair deployment with immediate cleanup
# Supports multiple runs (run1-5)

cd /home/ec2-user/benchmark

SERVER_TEMPLATE="benchmarks/nginx/nginx-server.yaml"
BENCHMARK_TEMPLATE="benchmarks/nginx/nginx-benchmark.yaml"
RESULTS_DIR="results/nginx"
MAX_CONCURRENT=20
RUN=${1:-1}

# All 51 instance types
INSTANCES=(
  # Intel 8th gen
  c8i.xlarge c8i-flex.xlarge m8i.xlarge r8i.xlarge r8i-flex.xlarge
  # Graviton 4
  c8g.xlarge m8g.xlarge r8g.xlarge
  # Intel 7th gen
  c7i.xlarge c7i-flex.xlarge m7i.xlarge m7i-flex.xlarge r7i.xlarge
  # Graviton 3
  c7g.xlarge c7gd.xlarge m7g.xlarge m7gd.xlarge r7g.xlarge r7gd.xlarge
  # Intel 6th gen
  c6i.xlarge c6id.xlarge c6in.xlarge m6i.xlarge m6id.xlarge m6in.xlarge m6idn.xlarge r6i.xlarge r6id.xlarge
  # Graviton 2
  c6g.xlarge c6gd.xlarge c6gn.xlarge m6g.xlarge m6gd.xlarge r6g.xlarge r6gd.xlarge
  # Intel 5th gen
  c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge
  m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge
  r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge
)

mkdir -p "$RESULTS_DIR"

# Track running and completed instances
declare -A RUNNING
declare -A COMPLETED

# Ensure service exists (webhook may block creation)
ensure_service() {
  local instance=$1
  local safe=$(echo "$instance" | tr '.' '-')

  if ! kubectl get svc -n benchmark "nginx-server-${safe}" &>/dev/null; then
    cat <<EOF | kubectl apply -f - 2>/dev/null
apiVersion: v1
kind: Service
metadata:
  name: nginx-server-${safe}
  namespace: benchmark
  labels:
    app: nginx-server
spec:
  selector:
    app: nginx-server
    instance-type: "${instance}"
  ports:
  - port: 80
    targetPort: 80
EOF
  fi
}

# Deploy Nginx server
deploy_server() {
  local instance=$1
  local safe=$(echo "$instance" | tr '.' '-')

  sed -e "s/INSTANCE_SAFE/${safe}/g" \
      -e "s/\${INSTANCE_TYPE}/${instance}/g" \
      "$SERVER_TEMPLATE" | kubectl apply -f - 2>/dev/null

  ensure_service "$instance"
}

# Check if server is ready
is_server_ready() {
  local instance=$1
  local ready=$(kubectl get pods -n benchmark -l "app=nginx-server,instance-type=${instance}" -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
  [ "$ready" = "true" ]
}

# Deploy benchmark job
deploy_benchmark() {
  local instance=$1
  local run=$2
  local safe=$(echo "$instance" | tr '.' '-')
  local jobname="nginx-benchmark-${safe}-run${run}"

  sed -e "s/nginx-benchmark-INSTANCE_SAFE/${jobname}/g" \
      -e "s/INSTANCE_SAFE/${safe}/g" \
      -e "s/\${INSTANCE_TYPE}/${instance}/g" \
      "$BENCHMARK_TEMPLATE" | kubectl apply -f - 2>/dev/null
}

# Check if benchmark is complete
is_benchmark_complete() {
  local instance=$1
  local run=$2
  local safe=$(echo "$instance" | tr '.' '-')
  local jobname="nginx-benchmark-${safe}-run${run}"

  local status=$(kubectl get job -n benchmark "$jobname" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
  local failed=$(kubectl get job -n benchmark "$jobname" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null)

  [ "$status" = "True" ] || [ "$failed" = "True" ]
}

# Collect log and cleanup everything
collect_and_cleanup() {
  local instance=$1
  local run=$2
  local safe=$(echo "$instance" | tr '.' '-')
  local jobname="nginx-benchmark-${safe}-run${run}"

  # Create directory
  mkdir -p "${RESULTS_DIR}/${instance}"
  local logfile="${RESULTS_DIR}/${instance}/run${run}.log"

  # Collect log
  kubectl logs -n benchmark "job/${jobname}" -c benchmark > "$logfile" 2>/dev/null

  # Delete benchmark job
  kubectl delete job -n benchmark "$jobname" --ignore-not-found=true &>/dev/null

  # Delete server deployment and service
  kubectl delete deployment -n benchmark "nginx-server-${safe}" --ignore-not-found=true &>/dev/null
  kubectl delete service -n benchmark "nginx-server-${safe}" --ignore-not-found=true &>/dev/null

  if [ -s "$logfile" ]; then
    echo "  [OK] $instance run${run} - log collected, resources cleaned"
    return 0
  else
    echo "  [FAIL] $instance run${run} - no log"
    return 1
  fi
}

# Start a new instance (server + benchmark)
start_instance() {
  local instance=$1
  local safe=$(echo "$instance" | tr '.' '-')

  # Check if result already exists
  if [ -s "${RESULTS_DIR}/${instance}/run${RUN}.log" ]; then
    echo "  [SKIP] $instance run${RUN} - result exists"
    COMPLETED[$instance]=1
    return
  fi

  echo "  [START] $instance"

  # Deploy server
  deploy_server "$instance"
  RUNNING[$instance]="server"
}

echo "===== Nginx Benchmark Runner v2 ====="
echo "Run: $RUN"
echo "Total instances: ${#INSTANCES[@]}"
echo "Max concurrent: $MAX_CONCURRENT"
echo "Start: $(date)"
echo ""

instance_idx=0

while true; do
  # Phase 1: Check running servers that are now ready -> start benchmark
  for instance in "${!RUNNING[@]}"; do
    if [ "${RUNNING[$instance]}" = "server" ]; then
      if is_server_ready "$instance"; then
        echo "  [READY] $instance - starting benchmark"
        deploy_benchmark "$instance" "$RUN"
        RUNNING[$instance]="benchmark"
      fi
    fi
  done

  # Phase 2: Check running benchmarks that are complete -> collect & cleanup
  for instance in "${!RUNNING[@]}"; do
    if [ "${RUNNING[$instance]}" = "benchmark" ]; then
      if is_benchmark_complete "$instance" "$RUN"; then
        collect_and_cleanup "$instance" "$RUN"
        COMPLETED[$instance]=1
        unset RUNNING[$instance]
      fi
    fi
  done

  # Count status
  running=${#RUNNING[@]}
  completed=${#COMPLETED[@]}

  echo "[Status] Running: $running, Completed: $completed/${#INSTANCES[@]}"

  # Phase 3: Start new instances if under limit
  while [ $running -lt $MAX_CONCURRENT ] && [ $instance_idx -lt ${#INSTANCES[@]} ]; do
    instance=${INSTANCES[$instance_idx]}
    ((instance_idx++))

    # Skip if already completed
    if [ -n "${COMPLETED[$instance]}" ]; then
      continue
    fi

    start_instance "$instance"
    ((running++)) || true
  done

  # Check if all done
  if [ $completed -eq ${#INSTANCES[@]} ]; then
    echo ""
    echo "===== All benchmarks completed! ====="
    break
  fi

  sleep 10
done

echo ""
echo "End: $(date)"
echo ""
echo "=== Results ==="
ls -la "${RESULTS_DIR}"/*/run${RUN}.log 2>/dev/null | wc -l
echo "log files collected for run${RUN}"
