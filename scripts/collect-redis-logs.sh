#!/bin/bash
# Collect Redis benchmark logs as jobs complete

cd /home/ec2-user/benchmark
mkdir -p results/redis-new

echo "=== Redis Log Collector Started ==="
echo "Start: $(date)"

while true; do
  COMPLETED=0
  TOTAL=0

  for job in $(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep redis-benchmark | awk '{print $1}'); do
    ((TOTAL++))
    INSTANCE=$(echo $job | sed 's/redis-benchmark-//' | sed 's/-xlarge/.xlarge/')
    LOGFILE="results/redis-new/${INSTANCE}.log"

    # Check if job completed
    if kubectl get job $job -n benchmark -o jsonpath='{.status.succeeded}' 2>/dev/null | grep -q "1"; then
      ((COMPLETED++))

      # Collect log if not already saved
      if [ ! -s "$LOGFILE" ]; then
        kubectl logs job/$job -n benchmark > "$LOGFILE" 2>/dev/null
        if [ -s "$LOGFILE" ]; then
          echo "Collected: $LOGFILE"
        fi
      fi
    fi
  done

  echo "Progress: $COMPLETED / $TOTAL completed ($(date +%H:%M:%S))"

  # Exit when all done
  if [ "$COMPLETED" -ge 51 ]; then
    echo "All Redis benchmarks completed!"
    break
  fi

  sleep 30
done

echo ""
echo "=== Collection Complete ==="
echo "End: $(date)"
ls -la results/redis-new/ | head -20
