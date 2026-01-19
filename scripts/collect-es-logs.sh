#!/bin/bash
# Collect Elasticsearch Cold Start logs from completed jobs
# Usage: ./collect-es-logs.sh

OUTPUT_DIR="/home/ec2-user/benchmark/results/elasticsearch"
mkdir -p "$OUTPUT_DIR"

echo "============================================"
echo "Collecting Elasticsearch Cold Start Logs"
echo "Output: $OUTPUT_DIR"
echo "============================================"

# Get all completed ES coldstart jobs
JOBS=$(kubectl get jobs -n benchmark -l benchmark=elasticsearch -o jsonpath='{.items[*].metadata.name}')

COLLECTED=0
FAILED=0

for JOB in $JOBS; do
  # Extract instance type from job name (es-coldstart-c8i-2xlarge -> c8i.2xlarge)
  INSTANCE=$(echo "$JOB" | sed 's/es-coldstart-//' | sed 's/-\([0-9]\)/.\1/')

  # Get pod name
  POD=$(kubectl get pods -n benchmark -l job-name="$JOB" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

  if [ -z "$POD" ]; then
    echo "SKIP: $JOB - no pod found"
    continue
  fi

  # Check job status
  STATUS=$(kubectl get job "$JOB" -n benchmark -o jsonpath='{.status.succeeded}' 2>/dev/null)

  if [ "$STATUS" = "1" ]; then
    LOGFILE="$OUTPUT_DIR/${INSTANCE}.log"
    kubectl logs -n benchmark "$POD" -c benchmark > "$LOGFILE" 2>/dev/null

    if [ -s "$LOGFILE" ]; then
      # Extract cold start time for quick verification
      COLD_START=$(grep "COLD_START_MS:" "$LOGFILE" | awk '{print $2}')
      echo "OK: $INSTANCE -> ${COLD_START}ms"
      ((COLLECTED++))
    else
      echo "EMPTY: $INSTANCE - log file empty"
      rm -f "$LOGFILE"
      ((FAILED++))
    fi
  else
    echo "PENDING: $JOB - not completed yet"
  fi
done

echo ""
echo "============================================"
echo "Collected: $COLLECTED logs"
echo "Failed: $FAILED"
echo "============================================"
