#!/bin/bash
# Collect logs from completed Redis benchmarks and delete jobs

RESULTS_DIR="/home/ec2-user/benchmark/results/redis"

while true; do
  COLLECTED=0
  DELETED=0
  
  for POD in $(kubectl get pods -n benchmark -l benchmark=redis-benchmark --no-headers 2>/dev/null | grep Completed | awk '{print $1}'); do
    JOB_NAME=$(echo "$POD" | sed 's/-[a-z0-9]*$//')
    INSTANCE_RAW=$(echo "$JOB_NAME" | sed 's/redis-benchmark-//' | sed 's/-run[0-9]$//')
    INSTANCE=$(echo "$INSTANCE_RAW" | sed 's/-xlarge$/.xlarge/')
    RUN=$(echo "$JOB_NAME" | grep -oE 'run[0-9]+' | sed 's/run//')
    
    LOG_FILE="${RESULTS_DIR}/${INSTANCE}/run${RUN}.log"
    
    if [ ! -f "$LOG_FILE" ] || [ ! -s "$LOG_FILE" ]; then
      mkdir -p "${RESULTS_DIR}/${INSTANCE}" 2>/dev/null
      if kubectl logs -n benchmark "$POD" > "$LOG_FILE" 2>/dev/null; then
        COLLECTED=$((COLLECTED + 1))
      fi
    fi
    
    # Delete the job to release resources
    kubectl delete job "${JOB_NAME}" -n benchmark --ignore-not-found=true &>/dev/null
    DELETED=$((DELETED + 1))
  done
  
  # Count current logs
  TOTAL_LOGS=$(find "${RESULTS_DIR}" -name "run*.log" -size +0 | wc -l)
  
  echo "[$(date '+%H:%M:%S')] Collected: $COLLECTED, Deleted: $DELETED jobs, Total logs: $TOTAL_LOGS/255"
  
  # Check if all done
  if [ "$TOTAL_LOGS" -ge 255 ]; then
    echo "[$(date '+%H:%M:%S')] All benchmarks complete!"
    break
  fi
  
  sleep 60
done
