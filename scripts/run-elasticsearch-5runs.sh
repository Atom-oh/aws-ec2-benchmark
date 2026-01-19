#!/bin/bash
# Elasticsearch Cold Start Benchmark - 5 Runs per Instance
# Runs all 51 instances with 5 iterations each

cd /home/ec2-user/benchmark

BENCHMARK_TEMPLATE="benchmarks/elasticsearch/elasticsearch-coldstart.yaml"
RESULTS_DIR="results/elasticsearch"
MAX_CONCURRENT=20
NUM_RUNS=5

# All 51 instances
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
  mkdir -p "$RESULTS_DIR/$instance"
done

declare -A STARTED
declare -A COMPLETED

get_arch() {
  local instance=$1
  if [[ "$instance" =~ g\. || "$instance" =~ gd\. || "$instance" =~ gn\. ]]; then
    echo "arm64"
  else
    echo "amd64"
  fi
}

start_benchmark() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="es-coldstart-${safe_name}-run${run_num}"
  local arch=$(get_arch "$instance")

  # Check if result already exists
  if [ -f "$RESULTS_DIR/$instance/run${run_num}.log" ]; then
    return 1
  fi

  echo "  [START] $instance run${run_num}"
  cat "$BENCHMARK_TEMPLATE" | \
      sed "s/es-coldstart-INSTANCE_SAFE/${job_name}/g" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s/INSTANCE_TYPE/${instance}/g" | \
      sed "s/ARCH/${arch}/g" | \
      kubectl apply -f - 2>/dev/null || true

  STARTED["${instance}_${run_num}"]=1
}

collect_and_delete() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="es-coldstart-${safe_name}-run${run_num}"

  echo "  [COLLECT] $instance run${run_num}"
  kubectl logs -n benchmark "job/${job_name}" > "$RESULTS_DIR/$instance/run${run_num}.log" 2>/dev/null || true
  kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null

  # Verify log has content
  if [ ! -s "$RESULTS_DIR/$instance/run${run_num}.log" ]; then
    echo "    [WARN] Empty log for $instance run${run_num}"
    rm -f "$RESULTS_DIR/$instance/run${run_num}.log"
    return 1
  fi

  COMPLETED["${instance}_${run_num}"]=1
  unset STARTED["${instance}_${run_num}"]
}

total_jobs=$((${#ALL_INSTANCES[@]} * NUM_RUNS))

echo "===== Elasticsearch Cold Start - 5 Runs per Instance ====="
echo "Total instances: ${#ALL_INSTANCES[@]}"
echo "Runs per instance: $NUM_RUNS"
echo "Total jobs: $total_jobs"
echo "Max concurrent: $MAX_CONCURRENT"
echo "Results dir: $RESULTS_DIR"
echo ""

# Main loop
while true; do
  # Check for completed jobs
  for key in "${!STARTED[@]}"; do
    instance=$(echo "$key" | cut -d'_' -f1)
    run_num=$(echo "$key" | cut -d'_' -f2)
    safe_name=$(echo "$instance" | tr '.' '-')
    job_name="es-coldstart-${safe_name}-run${run_num}"

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
  echo "[$(date '+%H:%M:%S')] Running: $running, Completed: $completed/$total_jobs"

  # Start new jobs
  for instance in "${ALL_INSTANCES[@]}"; do
    for run_num in $(seq 1 $NUM_RUNS); do
      key="${instance}_${run_num}"

      # Skip if already running or completed
      if [ -n "${STARTED[$key]}" ] || [ -n "${COMPLETED[$key]}" ]; then
        continue
      fi

      # Skip if result exists
      if [ -f "$RESULTS_DIR/$instance/run${run_num}.log" ]; then
        COMPLETED[$key]=1
        continue
      fi

      # Stop if at max concurrent
      if [ $running -ge $MAX_CONCURRENT ]; then
        break 2
      fi

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

  sleep 30
done

# Summary
echo ""
echo "=== Results Summary ==="
for instance in "${ALL_INSTANCES[@]}"; do
  count=$(ls -1 "$RESULTS_DIR/$instance"/run*.log 2>/dev/null | wc -l)
  echo "$instance: $count runs"
done | head -20
echo "..."
echo "Total: $(find "$RESULTS_DIR" -name "run*.log" | wc -l) log files"
