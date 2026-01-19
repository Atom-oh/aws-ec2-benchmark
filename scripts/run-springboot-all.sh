#!/bin/bash
# SpringBoot Benchmark - Cold Start + wrk (5 runs each)
# Fixed: One job per instance at a time (sequential per instance, parallel across instances)

cd /home/ec2-user/benchmark

COLDSTART_TEMPLATE="benchmarks/springboot/springboot-coldstart.yaml"
WRK_TEMPLATE="benchmarks/springboot/springboot-benchmark.yaml"
SERVER_TEMPLATE="benchmarks/springboot/springboot-server.yaml"
RESULTS_DIR="results/springboot"
MAX_CONCURRENT=40
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

get_arch() {
  local instance=$1
  if [[ "$instance" =~ g\. || "$instance" =~ gd\. || "$instance" =~ gn\. ]]; then
    echo "arm64"
  else
    echo "amd64"
  fi
}

# Track current run for each instance
declare -A COLD_CURRENT_RUN
declare -A WRK_CURRENT_RUN
declare -A COLD_RUNNING
declare -A WRK_RUNNING

# Initialize current runs
for instance in "${ALL_INSTANCES[@]}"; do
  # Find first incomplete run
  for run_num in $(seq 1 $NUM_RUNS); do
    if [ ! -f "$RESULTS_DIR/$instance/cold_start${run_num}.log" ]; then
      COLD_CURRENT_RUN[$instance]=$run_num
      break
    fi
  done
  [ -z "${COLD_CURRENT_RUN[$instance]}" ] && COLD_CURRENT_RUN[$instance]=$((NUM_RUNS + 1))

  for run_num in $(seq 1 $NUM_RUNS); do
    if [ ! -f "$RESULTS_DIR/$instance/wrk${run_num}.log" ]; then
      WRK_CURRENT_RUN[$instance]=$run_num
      break
    fi
  done
  [ -z "${WRK_CURRENT_RUN[$instance]}" ] && WRK_CURRENT_RUN[$instance]=$((NUM_RUNS + 1))
done

# Deploy servers for wrk
deploy_servers() {
  echo "=== Deploying SpringBoot servers ==="
  for instance in "${ALL_INSTANCES[@]}"; do
    safe_name=$(echo "$instance" | tr '.' '-')
    if ! kubectl get deployment -n benchmark "springboot-server-${safe_name}" &>/dev/null; then
      cat "$SERVER_TEMPLATE" | \
          sed "s/INSTANCE_SAFE/${safe_name}/g" | \
          sed "s/\${INSTANCE_TYPE}/${instance}/g" | \
          kubectl apply -f - 2>/dev/null || true
      echo "  [DEPLOY] springboot-server-${safe_name}"
    fi
  done
  echo "Waiting 60s for servers to start..."
  sleep 60
}

start_coldstart() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="springboot-coldstart-${safe_name}-run${run_num}"
  local arch=$(get_arch "$instance")

  echo "  [COLD] $instance run${run_num}"
  cat "$COLDSTART_TEMPLATE" | \
      sed "s/springboot-coldstart-INSTANCE_SAFE/${job_name}/g" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s/INSTANCE_TYPE/${instance}/g" | \
      sed "s/ARCH/${arch}/g" | \
      kubectl apply -f - 2>/dev/null || true

  COLD_RUNNING[$instance]=1
}

start_wrk() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="springboot-wrk-${safe_name}-run${run_num}"

  # Check if server is ready
  local ready=$(kubectl get deployment -n benchmark "springboot-server-${safe_name}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  if [ "$ready" != "1" ]; then
    return 1
  fi

  echo "  [WRK] $instance run${run_num}"
  cat "$WRK_TEMPLATE" | \
      sed "s/springboot-benchmark-INSTANCE_SAFE/${job_name}/g" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s/\${INSTANCE_TYPE}/${instance}/g" | \
      kubectl apply -f - 2>/dev/null || true

  WRK_RUNNING[$instance]=1
}

collect_coldstart() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="springboot-coldstart-${safe_name}-run${run_num}"
  local log_file="$RESULTS_DIR/$instance/cold_start${run_num}.log"

  echo "  [COLLECT] cold $instance run${run_num}"
  kubectl logs -n benchmark "job/${job_name}" -c benchmark > "$log_file" 2>/dev/null || true
  kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null

  if [ ! -s "$log_file" ]; then
    rm -f "$log_file"
    return 1
  fi
  return 0
}

collect_wrk() {
  local instance=$1
  local run_num=$2
  local safe_name=$(echo "$instance" | tr '.' '-')
  local job_name="springboot-wrk-${safe_name}-run${run_num}"
  local log_file="$RESULTS_DIR/$instance/wrk${run_num}.log"

  echo "  [COLLECT] wrk $instance run${run_num}"
  kubectl logs -n benchmark "job/${job_name}" -c benchmark > "$log_file" 2>/dev/null || true
  kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null

  if [ ! -s "$log_file" ]; then
    rm -f "$log_file"
    return 1
  fi
  return 0
}

count_completed() {
  local cold_done=0
  local wrk_done=0
  for instance in "${ALL_INSTANCES[@]}"; do
    cold_done=$((cold_done + $(ls -1 "$RESULTS_DIR/$instance"/cold_start*.log 2>/dev/null | wc -l)))
    wrk_done=$((wrk_done + $(ls -1 "$RESULTS_DIR/$instance"/wrk*.log 2>/dev/null | wc -l)))
  done
  echo "$cold_done $wrk_done"
}

total_cold=$((${#ALL_INSTANCES[@]} * NUM_RUNS))
total_wrk=$((${#ALL_INSTANCES[@]} * NUM_RUNS))

echo "===== SpringBoot Benchmark - Cold Start + wrk ====="
echo "Total instances: ${#ALL_INSTANCES[@]}"
echo "Runs per instance: $NUM_RUNS"
echo "Cold start jobs: $total_cold"
echo "wrk jobs: $total_wrk"
echo "Max concurrent: $MAX_CONCURRENT"
echo ""

# Deploy servers first
deploy_servers

# Main loop
while true; do
  # Check for completed coldstart jobs
  for instance in "${ALL_INSTANCES[@]}"; do
    if [ -n "${COLD_RUNNING[$instance]}" ]; then
      run_num=${COLD_CURRENT_RUN[$instance]}
      safe_name=$(echo "$instance" | tr '.' '-')
      job_name="springboot-coldstart-${safe_name}-run${run_num}"

      status=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
      failed=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || echo "")

      if [ "$status" = "True" ]; then
        if collect_coldstart "$instance" "$run_num"; then
          COLD_CURRENT_RUN[$instance]=$((run_num + 1))
        fi
        unset COLD_RUNNING[$instance]
      elif [ "$failed" = "True" ]; then
        echo "  [FAILED] cold $instance run${run_num}"
        kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null
        unset COLD_RUNNING[$instance]
      fi
    fi
  done

  # Check for completed wrk jobs
  for instance in "${ALL_INSTANCES[@]}"; do
    if [ -n "${WRK_RUNNING[$instance]}" ]; then
      run_num=${WRK_CURRENT_RUN[$instance]}
      safe_name=$(echo "$instance" | tr '.' '-')
      job_name="springboot-wrk-${safe_name}-run${run_num}"

      status=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
      failed=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || echo "")

      if [ "$status" = "True" ]; then
        if collect_wrk "$instance" "$run_num"; then
          WRK_CURRENT_RUN[$instance]=$((run_num + 1))
        fi
        unset WRK_RUNNING[$instance]
      elif [ "$failed" = "True" ]; then
        echo "  [FAILED] wrk $instance run${run_num}"
        kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null
        unset WRK_RUNNING[$instance]
      fi
    fi
  done

  # Count running jobs
  cold_running=${#COLD_RUNNING[@]}
  wrk_running=${#WRK_RUNNING[@]}
  total_running=$((cold_running + wrk_running))

  # Count completed
  read cold_completed wrk_completed <<< $(count_completed)

  echo "[$(date '+%H:%M:%S')] Cold: $cold_completed/$total_cold | wrk: $wrk_completed/$total_wrk | Running: $total_running"

  # Start new jobs (one per instance)
  for instance in "${ALL_INSTANCES[@]}"; do
    # Check concurrent limit
    if [ $total_running -ge $MAX_CONCURRENT ]; then
      break
    fi

    # Start coldstart if not running and not completed
    if [ -z "${COLD_RUNNING[$instance]}" ]; then
      run_num=${COLD_CURRENT_RUN[$instance]}
      if [ "$run_num" -le "$NUM_RUNS" ]; then
        if [ ! -f "$RESULTS_DIR/$instance/cold_start${run_num}.log" ]; then
          start_coldstart "$instance" "$run_num"
          ((total_running++)) || true
        else
          COLD_CURRENT_RUN[$instance]=$((run_num + 1))
        fi
      fi
    fi

    # Check concurrent limit again
    if [ $total_running -ge $MAX_CONCURRENT ]; then
      break
    fi

    # Start wrk if not running and not completed
    if [ -z "${WRK_RUNNING[$instance]}" ]; then
      run_num=${WRK_CURRENT_RUN[$instance]}
      if [ "$run_num" -le "$NUM_RUNS" ]; then
        if [ ! -f "$RESULTS_DIR/$instance/wrk${run_num}.log" ]; then
          if start_wrk "$instance" "$run_num"; then
            ((total_running++)) || true
          fi
        else
          WRK_CURRENT_RUN[$instance]=$((run_num + 1))
        fi
      fi
    fi
  done

  # Check if all done
  if [ $cold_completed -eq $total_cold ] && [ $wrk_completed -eq $total_wrk ]; then
    echo ""
    echo "===== All benchmarks completed! ====="
    break
  fi

  sleep 20
done

# Summary
echo ""
echo "=== Results Summary ==="
for instance in "${ALL_INSTANCES[@]}"; do
  cold_count=$(ls -1 "$RESULTS_DIR/$instance"/cold_start*.log 2>/dev/null | wc -l)
  wrk_count=$(ls -1 "$RESULTS_DIR/$instance"/wrk*.log 2>/dev/null | wc -l)
  echo "$instance: cold=$cold_count, wrk=$wrk_count"
done | head -20
echo "..."
echo "Cold start logs: $(find "$RESULTS_DIR" -name "cold_start*.log" | wc -l)"
echo "wrk logs: $(find "$RESULTS_DIR" -name "wrk*.log" | wc -l)"
