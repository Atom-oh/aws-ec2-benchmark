#!/bin/bash
# Parse Elasticsearch Cold Start logs and generate CSV
# Usage: ./parse-es-results.sh

LOG_DIR="/home/ec2-user/benchmark/results/elasticsearch"
OUTPUT="/home/ec2-user/benchmark/results/elasticsearch-summary.csv"

echo "Instance Type,JVM Start (ms),Cluster Ready (ms),Cold Start (ms),Cold Start (s),Index Time (ms)" > "$OUTPUT"

COUNT=0

for LOGFILE in "$LOG_DIR"/*.log; do
  [ -f "$LOGFILE" ] || continue

  INSTANCE=$(basename "$LOGFILE" .log)

  # Parse metrics from log
  JVM_START=$(grep "^JVM_START_MS:" "$LOGFILE" | tail -1 | awk '{print $2}')
  CLUSTER_READY=$(grep "^CLUSTER_READY_MS:" "$LOGFILE" | tail -1 | awk '{print $2}')
  COLD_START_MS=$(grep "^COLD_START_MS:" "$LOGFILE" | tail -1 | awk '{print $2}')
  INDEX_TIME=$(grep "^INDEX_TIME_MS:" "$LOGFILE" | awk '{print $2}')

  # Skip if no cold start data
  if [ -z "$COLD_START_MS" ]; then
    echo "SKIP: $INSTANCE - no COLD_START_MS found"
    continue
  fi

  # Calculate seconds
  COLD_START_S=$(echo "scale=2; $COLD_START_MS/1000" | bc)

  echo "$INSTANCE,$JVM_START,$CLUSTER_READY,$COLD_START_MS,$COLD_START_S,$INDEX_TIME" >> "$OUTPUT"
  ((COUNT++))
done

echo ""
echo "============================================"
echo "Generated: $OUTPUT"
echo "Total instances: $COUNT"
echo "============================================"

# Show summary sorted by cold start time
echo ""
echo "=== Top 10 Fastest Cold Start ==="
tail -n +2 "$OUTPUT" | sort -t',' -k4 -n | head -10 | column -t -s','

echo ""
echo "=== Top 10 Slowest Cold Start ==="
tail -n +2 "$OUTPUT" | sort -t',' -k4 -rn | head -10 | column -t -s','
