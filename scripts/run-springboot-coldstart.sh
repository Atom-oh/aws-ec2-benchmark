#!/bin/bash
# Spring Boot Cold Start Benchmark
# 1. Deploy servers to all 51 instances
# 2. Wait for ready + trigger first HTTP request
# 3. Collect startup logs
# 4. Parse and generate CSV

# Don't use set -e - some commands may return non-zero

SERVER_TEMPLATE="/home/ec2-user/benchmark/benchmarks/springboot/springboot-server.yaml"
RESULTS_DIR="/home/ec2-user/benchmark/results/springboot"
LOGS_DIR="$RESULTS_DIR/server-logs"
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

mkdir -p "$RESULTS_DIR" "$LOGS_DIR"

# Track deployment status
declare -A DEPLOYED
declare -A READY
declare -A TRIGGERED
declare -A COLLECTED

log() {
  echo "[$(date '+%H:%M:%S')] $1"
}

# Deploy server for an instance
deploy_server() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')

  # Check if already deployed
  if kubectl get deployment -n benchmark "springboot-server-${safe_name}" &>/dev/null; then
    log "  [SKIP] Server already exists: $instance"
    DEPLOYED[$instance]=1
    return
  fi

  log "  [DEPLOY] $instance"
  sed -e "s|\${INSTANCE_TYPE//./-}|${safe_name}|g" \
      -e "s|\${INSTANCE_TYPE}|${instance}|g" \
      "$SERVER_TEMPLATE" | kubectl apply -f - 2>/dev/null

  DEPLOYED[$instance]=1
}

# Check if server is ready
check_ready() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  local deploy_name="springboot-server-${safe_name}"

  local ready=$(kubectl get deployment -n benchmark "$deploy_name" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  [ "$ready" = "1" ]
}

# Trigger first HTTP request (for Completed initialization)
trigger_first_request() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  local svc_name="springboot-server-${safe_name}"

  # Get pod name
  local pod=$(kubectl get pods -n benchmark -l "app=springboot-server,instance-type=$instance" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

  if [ -z "$pod" ]; then
    return 1
  fi

  # Send first HTTP request via kubectl exec
  kubectl exec -n benchmark "$pod" -- curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ 2>/dev/null || true
  TRIGGERED[$instance]=1
  log "  [TRIGGER] First HTTP request sent: $instance"
}

# Collect server logs
collect_logs() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')
  local deploy_name="springboot-server-${safe_name}"

  log "  [COLLECT] $instance"
  kubectl logs -n benchmark "deployment/${deploy_name}" > "$LOGS_DIR/${instance}.log" 2>/dev/null || true
  COLLECTED[$instance]=1
}

# Parse logs and generate CSV
generate_csv() {
  local output_file="$RESULTS_DIR/startup-times-full.csv"

  log "Generating CSV: $output_file"
  echo "instance_type,startup_seconds,process_seconds,starting_time,completed_time,coldstart_ms" > "$output_file"

  for logfile in "$LOGS_DIR"/*.log; do
    [ -f "$logfile" ] || continue

    local instance=$(basename "$logfile" .log)

    # Extract "Started DemoApplication in X.XXX seconds (process running for Y.YY)"
    local started_line=$(grep "Started DemoApplication in" "$logfile" 2>/dev/null | head -1)
    local startup_seconds=$(echo "$started_line" | grep -oP 'in \K[\d.]+(?= seconds)' || echo "")
    local process_seconds=$(echo "$started_line" | grep -oP 'running for \K[\d.]+' || echo "")

    # Extract timestamps
    # Starting DemoApplication (first log line with this text)
    local starting_time=$(grep "Starting DemoApplication" "$logfile" 2>/dev/null | head -1 | awk '{print $1}')

    # Completed initialization (DispatcherServlet lazy init)
    local completed_time=$(grep "Completed initialization" "$logfile" 2>/dev/null | head -1 | awk '{print $1}')

    # Calculate cold start time (ms) if both timestamps exist
    local coldstart_ms=""
    if [ -n "$starting_time" ] && [ -n "$completed_time" ]; then
      # Convert ISO timestamps to epoch milliseconds and calculate difference
      local start_epoch=$(date -d "$starting_time" +%s%3N 2>/dev/null || echo "")
      local end_epoch=$(date -d "$completed_time" +%s%3N 2>/dev/null || echo "")
      if [ -n "$start_epoch" ] && [ -n "$end_epoch" ]; then
        coldstart_ms=$((end_epoch - start_epoch))
      fi
    fi

    if [ -n "$startup_seconds" ]; then
      echo "$instance,$startup_seconds,$process_seconds,$starting_time,$completed_time,$coldstart_ms" >> "$output_file"
    fi
  done

  log "CSV generated with $(wc -l < "$output_file") lines (including header)"
}

# Cleanup servers
cleanup_servers() {
  log "Cleaning up all springboot-server deployments..."
  kubectl delete deployment -n benchmark -l app=springboot-server --ignore-not-found=true
  kubectl delete service -n benchmark -l app=springboot-server --ignore-not-found=true
}

# Main execution
main() {
  echo "===== Spring Boot Cold Start Benchmark ====="
  echo "Total instances: ${#ALL_INSTANCES[@]}"
  echo "Max concurrent: $MAX_CONCURRENT"
  echo "Results dir: $RESULTS_DIR"
  echo ""

  # Phase 1: Deploy servers (batched)
  log "Phase 1: Deploying servers..."
  local deploy_idx=0
  while [ $deploy_idx -lt ${#ALL_INSTANCES[@]} ]; do
    local batch_count=0
    while [ $batch_count -lt $MAX_CONCURRENT ] && [ $deploy_idx -lt ${#ALL_INSTANCES[@]} ]; do
      deploy_server "${ALL_INSTANCES[$deploy_idx]}"
      ((deploy_idx++))
      ((batch_count++))
    done
    log "Deployed batch: $deploy_idx/${#ALL_INSTANCES[@]}"
    sleep 5
  done

  # Phase 2: Wait for ready and trigger first request
  log "Phase 2: Waiting for servers to be ready..."
  local max_wait=600  # 10 minutes max
  local wait_time=0

  while [ ${#TRIGGERED[@]} -lt ${#ALL_INSTANCES[@]} ] && [ $wait_time -lt $max_wait ]; do
    for instance in "${ALL_INSTANCES[@]}"; do
      # Skip if already triggered
      [ -n "${TRIGGERED[$instance]}" ] && continue

      if check_ready "$instance"; then
        if [ -z "${READY[$instance]}" ]; then
          READY[$instance]=1
          log "  [READY] $instance"
          # Wait a moment for logs to be written, then trigger
          sleep 2
          trigger_first_request "$instance"
        fi
      fi
    done

    log "Status: Ready=${#READY[@]}, Triggered=${#TRIGGERED[@]}/${#ALL_INSTANCES[@]}"
    sleep 10
    ((wait_time+=10))
  done

  # Phase 3: Wait for Completed initialization logs
  log "Phase 3: Waiting for initialization completion..."
  sleep 10

  # Phase 4: Collect logs
  log "Phase 4: Collecting logs..."
  for instance in "${ALL_INSTANCES[@]}"; do
    collect_logs "$instance"
  done

  # Phase 5: Generate CSV
  log "Phase 5: Generating CSV..."
  generate_csv

  echo ""
  echo "===== Benchmark Complete ====="
  echo "Logs: $LOGS_DIR"
  echo "CSV: $RESULTS_DIR/startup-times-full.csv"
  echo ""

  # Auto cleanup after successful CSV generation
  log "Phase 6: Cleaning up deployments..."
  cleanup_servers

  log "Done!"
}

# Run
main "$@"
