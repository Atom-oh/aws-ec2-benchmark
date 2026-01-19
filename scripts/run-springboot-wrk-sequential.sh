#!/bin/bash
# SpringBoot wrk Benchmark - Sequential per instance
# Each instance's 5 runs are executed sequentially (no load overlap)
# Different instances can run in parallel

cd /home/ec2-user/benchmark

WRK_TEMPLATE="benchmarks/springboot/springboot-benchmark.yaml"
RESULTS_DIR="results/springboot"
MAX_CONCURRENT_INSTANCES=12  # Max different instances running at once
NUM_RUNS=5

# Graviton instances that need wrk tests
GRAVITON_INSTANCES=(
  c7gd.xlarge c8g.xlarge
  m6g.xlarge m6gd.xlarge m7g.xlarge m7gd.xlarge m8g.xlarge
  r6g.xlarge r6gd.xlarge r7g.xlarge r7gd.xlarge r8g.xlarge
)

run_instance_wrk_sequential() {
  local instance=$1
  local safe_name=$(echo "$instance" | tr '.' '-')

  for run in $(seq 1 $NUM_RUNS); do
    log_file="$RESULTS_DIR/$instance/wrk${run}.log"

    # Skip if already completed
    if [ -f "$log_file" ] && grep -q "Requests/sec" "$log_file" 2>/dev/null; then
      echo "[SKIP] $instance run$run (already completed)"
      continue
    fi

    job_name="springboot-wrk-${safe_name}-run${run}"

    echo "[START] $instance run$run"

    # Create job
    cat "$WRK_TEMPLATE" | \
      sed "s/springboot-benchmark-INSTANCE_SAFE/${job_name}/g" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s/\${INSTANCE_TYPE}/${instance}/g" | \
      kubectl apply -f - 2>/dev/null

    # Wait for completion (timeout 10 minutes)
    local timeout=600
    local start_time=$(date +%s)

    while true; do
      local status=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
      local failed=$(kubectl get job -n benchmark "$job_name" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || echo "")

      if [ "$status" = "True" ]; then
        # Collect log
        kubectl logs -n benchmark "job/${job_name}" -c benchmark > "$log_file" 2>/dev/null
        kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null

        if grep -q "Requests/sec" "$log_file" 2>/dev/null; then
          echo "[DONE] $instance run$run"
        else
          echo "[INVALID] $instance run$run - retrying"
          rm -f "$log_file"
          # Don't break, let it retry in next loop iteration
        fi
        break
      elif [ "$failed" = "True" ]; then
        echo "[FAILED] $instance run$run"
        kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null
        break
      fi

      local elapsed=$(($(date +%s) - start_time))
      if [ $elapsed -gt $timeout ]; then
        echo "[TIMEOUT] $instance run$run"
        kubectl delete job -n benchmark "$job_name" --ignore-not-found=true &>/dev/null
        break
      fi

      sleep 5
    done

    # Short pause between runs
    sleep 2
  done

  echo "[COMPLETE] $instance all runs finished"
}

echo "===== SpringBoot wrk Sequential Benchmark ====="
echo "Instances: ${#GRAVITON_INSTANCES[@]}"
echo "Runs per instance: $NUM_RUNS"
echo "Max concurrent instances: $MAX_CONCURRENT_INSTANCES"
echo ""

# Run instances in parallel (but each instance's runs are sequential)
running_pids=()
for instance in "${GRAVITON_INSTANCES[@]}"; do
  # Check if already complete
  completed=$(ls "$RESULTS_DIR/$instance"/wrk*.log 2>/dev/null | wc -l)
  if [ "$completed" -ge "$NUM_RUNS" ]; then
    echo "[SKIP] $instance (all $NUM_RUNS runs completed)"
    continue
  fi

  # Wait if too many concurrent
  while [ ${#running_pids[@]} -ge $MAX_CONCURRENT_INSTANCES ]; do
    new_pids=()
    for pid in "${running_pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        new_pids+=("$pid")
      fi
    done
    running_pids=("${new_pids[@]}")
    sleep 5
  done

  # Start instance in background
  run_instance_wrk_sequential "$instance" &
  running_pids+=($!)
  echo "[QUEUED] $instance (pid: ${running_pids[-1]})"
  sleep 2
done

# Wait for all to complete
echo ""
echo "Waiting for all instances to complete..."
for pid in "${running_pids[@]}"; do
  wait "$pid" 2>/dev/null
done

echo ""
echo "===== All SpringBoot wrk benchmarks complete ====="
