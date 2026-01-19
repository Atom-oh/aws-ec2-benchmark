#!/bin/bash
# Redis Benchmark - 5 runs per instance for statistical validity
# Uses existing Redis servers

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

RUN=${1:-1}

echo "===== Redis Benchmark Run $RUN ====="
echo "Start: $(date)"
echo "Instances: ${#INSTANCES[@]}"

# Cleanup old jobs for this run
echo ""
echo "=== Cleaning up old jobs ==="
for INSTANCE in "${INSTANCES[@]}"; do
  SAFE=$(echo $INSTANCE | tr '.' '-')
  kubectl delete job redis-benchmark-${SAFE}-run${RUN} -n benchmark --ignore-not-found=true 2>/dev/null
done

sleep 5

# Deploy all benchmark jobs
echo ""
echo "=== Deploying benchmark jobs ==="
for INSTANCE in "${INSTANCES[@]}"; do
  SAFE=$(echo $INSTANCE | tr '.' '-')

  # Check if Redis server is running
  POD_STATUS=$(kubectl get pods -n benchmark -l "app=redis-server,instance-type=${INSTANCE}" --no-headers 2>/dev/null | awk '{print $3}' | head -1)

  if [ "$POD_STATUS" != "Running" ]; then
    echo "  [SKIP] $INSTANCE - Redis server not running"
    continue
  fi

  # Create job with run number suffix
  JOBNAME="redis-benchmark-${SAFE}-run${RUN}"
  sed -e "s/JOB_NAME/${JOBNAME}/g" \
      -e "s/INSTANCE_SAFE/${SAFE}/g" \
      -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      benchmarks/redis/redis-benchmark.yaml | kubectl apply -f - >/dev/null 2>&1

  echo "  [DEPLOY] redis-benchmark-${SAFE}-run${RUN}"
done

# Wait and collect logs
echo ""
echo "=== Waiting for jobs to complete ==="
MAX_WAIT=600  # 10 minutes
WAIT=0
COLLECTED=0

while [ $WAIT -lt $MAX_WAIT ]; do
  COMPLETED=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "redis-benchmark.*-run${RUN}" | grep "1/1" | wc -l)
  TOTAL=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "redis-benchmark.*-run${RUN}" | wc -l)

  echo "Progress: $COMPLETED / $TOTAL completed (wait: ${WAIT}s)"

  # Collect logs for completed jobs
  for job in $(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "redis-benchmark.*-run${RUN}" | grep "1/1" | awk '{print $1}'); do
    SAFE=$(echo $job | sed "s/redis-benchmark-//" | sed "s/-run${RUN}//")
    INSTANCE=$(echo $SAFE | sed 's/-xlarge/.xlarge/')

    mkdir -p "results/redis/${INSTANCE}"
    LOGFILE="results/redis/${INSTANCE}/run${RUN}.log"

    if [ ! -s "$LOGFILE" ]; then
      POD=$(kubectl get pods -n benchmark -l job-name=$job --no-headers 2>/dev/null | head -1 | awk '{print $1}')
      if [ -n "$POD" ]; then
        kubectl logs $POD -n benchmark -c benchmark > "$LOGFILE" 2>/dev/null
        if [ -s "$LOGFILE" ]; then
          ((COLLECTED++))
          echo "  Collected: ${INSTANCE}/run${RUN}.log"
        fi
      fi
    fi
  done

  if [ "$COMPLETED" -ge 51 ]; then
    echo "All jobs completed!"
    break
  fi

  sleep 30
  ((WAIT+=30))
done

echo ""
echo "===== Run $RUN Complete ====="
echo "Collected: $COLLECTED logs"
echo "End: $(date)"
