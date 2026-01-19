#!/bin/bash
# Redis Benchmark - Batch execution with aggressive log collection
# Processes in batches and collects logs every 10 seconds

set -e
cd /home/ec2-user/benchmark

INSTANCES=(
  "c8i.xlarge" "c8i-flex.xlarge" "m8i.xlarge" "r8i.xlarge" "r8i-flex.xlarge"
  "c8g.xlarge" "m8g.xlarge" "r8g.xlarge"
  "c7i.xlarge" "c7i-flex.xlarge" "m7i.xlarge" "m7i-flex.xlarge" "r7i.xlarge"
  "c7g.xlarge" "c7gd.xlarge" "m7g.xlarge" "m7gd.xlarge" "r7g.xlarge" "r7gd.xlarge"
  "c6i.xlarge" "c6id.xlarge" "c6in.xlarge" "m6i.xlarge" "m6id.xlarge" "m6in.xlarge" "m6idn.xlarge" "r6i.xlarge" "r6id.xlarge"
  "c6g.xlarge" "c6gd.xlarge" "c6gn.xlarge" "m6g.xlarge" "m6gd.xlarge" "r6g.xlarge" "r6gd.xlarge"
  "c5.xlarge" "c5a.xlarge" "c5d.xlarge" "c5n.xlarge"
  "m5.xlarge" "m5a.xlarge" "m5ad.xlarge" "m5d.xlarge" "m5zn.xlarge"
  "r5.xlarge" "r5a.xlarge" "r5ad.xlarge" "r5b.xlarge" "r5d.xlarge" "r5dn.xlarge" "r5n.xlarge"
)

RUN=${1:-1}

echo "===== Redis Benchmark Run $RUN ====="
echo "Start: $(date)"

# Cleanup and deploy all jobs
echo ""
echo "=== Deploying jobs ==="
for INSTANCE in "${INSTANCES[@]}"; do
  SAFE=$(echo $INSTANCE | tr '.' '-')
  JOBNAME="redis-benchmark-${SAFE}-run${RUN}"
  mkdir -p "results/redis/${INSTANCE}"

  # Skip if already collected
  if [ -s "results/redis/${INSTANCE}/run${RUN}.log" ]; then
    continue
  fi

  # Check Redis server
  POD_STATUS=$(kubectl get pods -n benchmark -l "app=redis-server,instance-type=${INSTANCE}" --no-headers 2>/dev/null | awk '{print $3}' | head -1)
  if [ "$POD_STATUS" != "Running" ]; then
    continue
  fi

  # Delete and create job
  kubectl delete job $JOBNAME -n benchmark --ignore-not-found=true 2>/dev/null || true
  sed -e "s/JOB_NAME/${JOBNAME}/g" \
      -e "s/INSTANCE_SAFE/${SAFE}/g" \
      -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      benchmarks/redis/redis-benchmark.yaml | kubectl apply -f - >/dev/null 2>&1
  echo "  Deployed: $JOBNAME"
done

# Aggressive log collection loop
echo ""
echo "=== Collecting logs (every 10s) ==="
COLLECTED=0
TOTAL_JOBS=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "redis-benchmark.*-run${RUN}" | wc -l)
MAX_ITERATIONS=60  # 10 minutes max

for i in $(seq 1 $MAX_ITERATIONS); do
  # Collect logs from completed jobs
  for job in $(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "redis-benchmark.*-run${RUN}" | grep "1/1" | awk '{print $1}'); do
    SAFE=$(echo $job | sed 's/redis-benchmark-//' | sed "s/-run${RUN}//")
    INSTANCE=$(echo $SAFE | sed 's/-xlarge/.xlarge/')
    LOGFILE="results/redis/${INSTANCE}/run${RUN}.log"

    if [ ! -s "$LOGFILE" ]; then
      kubectl logs job/$job -n benchmark -c benchmark > "$LOGFILE" 2>/dev/null
      if [ -s "$LOGFILE" ]; then
        ((COLLECTED++))
        echo "  [$COLLECTED] Collected: $INSTANCE"
      fi
    fi
  done

  COMPLETED=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "redis-benchmark.*-run${RUN}" | grep "1/1" | wc -l)

  if [ "$COMPLETED" -ge "$TOTAL_JOBS" ] && [ "$COLLECTED" -ge "$TOTAL_JOBS" ]; then
    echo ""
    echo "All done!"
    break
  fi

  echo "  Progress: $COLLECTED collected, $COMPLETED/$TOTAL_JOBS completed"
  sleep 10
done

echo ""
echo "===== Run $RUN Complete ====="
echo "Collected: $COLLECTED logs"
echo "End: $(date)"
