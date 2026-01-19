#!/bin/bash
# Redis Benchmark - Sequential execution with immediate log collection
# Runs 5 iterations per instance type

set -e
cd /home/ec2-user/benchmark

INSTANCES=(
  # Intel 8th gen
  "c8i.xlarge" "c8i-flex.xlarge" "m8i.xlarge" "r8i.xlarge" "r8i-flex.xlarge"
  # Graviton 4
  "c8g.xlarge" "m8g.xlarge" "r8g.xlarge"
  # Intel 7th gen
  "c7i.xlarge" "c7i-flex.xlarge" "m7i.xlarge" "m7i-flex.xlarge" "r7i.xlarge"
  # Graviton 3
  "c7g.xlarge" "c7gd.xlarge" "m7g.xlarge" "m7gd.xlarge" "r7g.xlarge" "r7gd.xlarge"
  # Intel 6th gen
  "c6i.xlarge" "c6id.xlarge" "c6in.xlarge" "m6i.xlarge" "m6id.xlarge" "m6in.xlarge" "m6idn.xlarge" "r6i.xlarge" "r6id.xlarge"
  # Graviton 2
  "c6g.xlarge" "c6gd.xlarge" "c6gn.xlarge" "m6g.xlarge" "m6gd.xlarge" "r6g.xlarge" "r6gd.xlarge"
  # Intel 5th gen
  "c5.xlarge" "c5a.xlarge" "c5d.xlarge" "c5n.xlarge"
  "m5.xlarge" "m5a.xlarge" "m5ad.xlarge" "m5d.xlarge" "m5zn.xlarge"
  "r5.xlarge" "r5a.xlarge" "r5ad.xlarge" "r5b.xlarge" "r5d.xlarge" "r5dn.xlarge" "r5n.xlarge"
)

BATCH_SIZE=${1:-10}  # Process this many instances in parallel per batch

echo "===== Redis Benchmark (5 runs each) ====="
echo "Start: $(date)"
echo "Instances: ${#INSTANCES[@]}"
echo "Batch size: $BATCH_SIZE"
echo ""

# Function to run benchmark for a single instance
run_instance() {
  local INSTANCE=$1
  local RUN=$2
  local SAFE=$(echo $INSTANCE | tr '.' '-')
  local JOBNAME="redis-benchmark-${SAFE}-run${RUN}"
  local LOGFILE="results/redis/${INSTANCE}/run${RUN}.log"

  mkdir -p "results/redis/${INSTANCE}"

  # Skip if log already exists
  if [ -s "$LOGFILE" ]; then
    echo "  [SKIP] $INSTANCE run${RUN} - already collected"
    return 0
  fi

  # Check if Redis server is running
  local POD_STATUS=$(kubectl get pods -n benchmark -l "app=redis-server,instance-type=${INSTANCE}" --no-headers 2>/dev/null | awk '{print $3}' | head -1)
  if [ "$POD_STATUS" != "Running" ]; then
    echo "  [SKIP] $INSTANCE - Redis server not running"
    return 1
  fi

  # Delete old job if exists
  kubectl delete job $JOBNAME -n benchmark --ignore-not-found=true 2>/dev/null
  sleep 1

  # Create job
  sed -e "s/JOB_NAME/${JOBNAME}/g" \
      -e "s/INSTANCE_SAFE/${SAFE}/g" \
      -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      benchmarks/redis/redis-benchmark.yaml | kubectl apply -f - >/dev/null 2>&1

  # Wait for completion (max 5 min)
  echo "  [RUN] $INSTANCE run${RUN}..."
  local TIMEOUT=300
  local ELAPSED=0
  while [ $ELAPSED -lt $TIMEOUT ]; do
    local STATUS=$(kubectl get job $JOBNAME -n benchmark -o jsonpath='{.status.succeeded}' 2>/dev/null)
    if [ "$STATUS" == "1" ]; then
      break
    fi
    sleep 5
    ((ELAPSED+=5))
  done

  # Collect log immediately
  kubectl logs job/$JOBNAME -n benchmark -c benchmark > "$LOGFILE" 2>/dev/null

  if [ -s "$LOGFILE" ]; then
    echo "  [OK] $INSTANCE run${RUN} - log collected"
    return 0
  else
    echo "  [FAIL] $INSTANCE run${RUN} - no log"
    return 1
  fi
}

# Run all 5 iterations
for RUN in 1 2 3 4 5; do
  echo ""
  echo "========== RUN $RUN / 5 =========="
  echo "Time: $(date)"

  COMPLETED=0
  for INSTANCE in "${INSTANCES[@]}"; do
    run_instance "$INSTANCE" "$RUN" && ((COMPLETED++))
  done

  echo ""
  echo "Run $RUN completed: $COMPLETED / ${#INSTANCES[@]}"
done

echo ""
echo "===== All Runs Complete ====="
echo "End: $(date)"
echo ""
echo "Results summary:"
for INSTANCE in "${INSTANCES[@]}"; do
  COUNT=$(ls results/redis/${INSTANCE}/run*.log 2>/dev/null | wc -l)
  echo "  $INSTANCE: $COUNT/5"
done | head -20
