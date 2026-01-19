#!/bin/bash
# Elasticsearch Cold Start Benchmark Runner v2
# Efficient: Immediate cleanup after log collection
# Supports multiple runs (run1-5)

cd /home/ec2-user/benchmark

BENCHMARK_TEMPLATE="benchmarks/elasticsearch/elasticsearch-coldstart.yaml"
RESULTS_DIR="results/elasticsearch"
MAX_CONCURRENT=20
RUN=${1:-1}

# All 51 instance types with their architectures
# Format: "instance:arch"
INSTANCES=(
  # Intel 8th gen (amd64)
  "c8i.xlarge:amd64" "c8i-flex.xlarge:amd64" "m8i.xlarge:amd64" "r8i.xlarge:amd64" "r8i-flex.xlarge:amd64"
  # Graviton 4 (arm64)
  "c8g.xlarge:arm64" "m8g.xlarge:arm64" "r8g.xlarge:arm64"
  # Intel 7th gen (amd64)
  "c7i.xlarge:amd64" "c7i-flex.xlarge:amd64" "m7i.xlarge:amd64" "m7i-flex.xlarge:amd64" "r7i.xlarge:amd64"
  # Graviton 3 (arm64)
  "c7g.xlarge:arm64" "c7gd.xlarge:arm64" "m7g.xlarge:arm64" "m7gd.xlarge:arm64" "r7g.xlarge:arm64" "r7gd.xlarge:arm64"
  # Intel 6th gen (amd64)
  "c6i.xlarge:amd64" "c6id.xlarge:amd64" "c6in.xlarge:amd64" "m6i.xlarge:amd64" "m6id.xlarge:amd64" "m6in.xlarge:amd64" "m6idn.xlarge:amd64" "r6i.xlarge:amd64" "r6id.xlarge:amd64"
  # Graviton 2 (arm64)
  "c6g.xlarge:arm64" "c6gd.xlarge:arm64" "c6gn.xlarge:arm64" "m6g.xlarge:arm64" "m6gd.xlarge:arm64" "r6g.xlarge:arm64" "r6gd.xlarge:arm64"
  # Intel 5th gen (amd64)
  "c5.xlarge:amd64" "c5a.xlarge:amd64" "c5d.xlarge:amd64" "c5n.xlarge:amd64"
  "m5.xlarge:amd64" "m5a.xlarge:amd64" "m5ad.xlarge:amd64" "m5d.xlarge:amd64" "m5zn.xlarge:amd64"
  "r5.xlarge:amd64" "r5a.xlarge:amd64" "r5ad.xlarge:amd64" "r5b.xlarge:amd64" "r5d.xlarge:amd64" "r5dn.xlarge:amd64" "r5n.xlarge:amd64"
)

mkdir -p "$RESULTS_DIR"

# Track running and completed instances
declare -A RUNNING
declare -A COMPLETED

# Deploy ES coldstart job
deploy_job() {
  local instance=$1
  local arch=$2
  local run=$3
  local safe=$(echo "$instance" | tr '.' '-')
  local jobname="es-coldstart-${safe}-run${run}"

  sed -e "s/es-coldstart-INSTANCE_SAFE/${jobname}/g" \
      -e "s/INSTANCE_SAFE/${safe}/g" \
      -e "s/INSTANCE_TYPE/${instance}/g" \
      -e "s/ARCH/${arch}/g" \
      "$BENCHMARK_TEMPLATE" | kubectl apply -f - 2>/dev/null
}

# Check if job is complete
is_job_complete() {
  local instance=$1
  local run=$2
  local safe=$(echo "$instance" | tr '.' '-')
  local jobname="es-coldstart-${safe}-run${run}"

  local status=$(kubectl get job -n benchmark "$jobname" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
  local failed=$(kubectl get job -n benchmark "$jobname" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null)

  [ "$status" = "True" ] || [ "$failed" = "True" ]
}

# Collect log and cleanup
collect_and_cleanup() {
  local instance=$1
  local run=$2
  local safe=$(echo "$instance" | tr '.' '-')
  local jobname="es-coldstart-${safe}-run${run}"

  # Create directory
  mkdir -p "${RESULTS_DIR}/${instance}"
  local logfile="${RESULTS_DIR}/${instance}/run${run}.log"

  # Collect log
  kubectl logs -n benchmark "job/${jobname}" -c benchmark > "$logfile" 2>/dev/null

  # Delete job
  kubectl delete job -n benchmark "$jobname" --ignore-not-found=true &>/dev/null

  if [ -s "$logfile" ]; then
    echo "  [OK] $instance run${run} - log collected, job cleaned"
    return 0
  else
    echo "  [FAIL] $instance run${run} - no log"
    return 1
  fi
}

# Start a new job
start_job() {
  local entry=$1
  local instance=${entry%:*}
  local arch=${entry#*:}
  local safe=$(echo "$instance" | tr '.' '-')

  # Check if result already exists
  if [ -s "${RESULTS_DIR}/${instance}/run${RUN}.log" ]; then
    echo "  [SKIP] $instance run${RUN} - result exists"
    COMPLETED[$instance]=1
    return
  fi

  echo "  [START] $instance ($arch)"
  deploy_job "$instance" "$arch" "$RUN"
  RUNNING[$instance]="$arch"
}

echo "===== Elasticsearch Cold Start Benchmark v2 ====="
echo "Run: $RUN"
echo "Total instances: ${#INSTANCES[@]}"
echo "Max concurrent: $MAX_CONCURRENT"
echo "Start: $(date)"
echo ""

instance_idx=0

while true; do
  # Check running jobs for completion
  for instance in "${!RUNNING[@]}"; do
    if is_job_complete "$instance" "$RUN"; then
      collect_and_cleanup "$instance" "$RUN"
      COMPLETED[$instance]=1
      unset RUNNING[$instance]
    fi
  done

  # Count status
  running=${#RUNNING[@]}
  completed=${#COMPLETED[@]}

  echo "[Status] Running: $running, Completed: $completed/${#INSTANCES[@]}"

  # Start new jobs if under limit
  while [ $running -lt $MAX_CONCURRENT ] && [ $instance_idx -lt ${#INSTANCES[@]} ]; do
    entry=${INSTANCES[$instance_idx]}
    instance=${entry%:*}
    ((instance_idx++))

    # Skip if already completed
    if [ -n "${COMPLETED[$instance]}" ]; then
      continue
    fi

    start_job "$entry"
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
