#!/bin/bash
while true; do
  echo "========== $(date '+%H:%M:%S') =========="
  echo "=== Jobs ==="
  kubectl get jobs -n benchmark --no-headers 2>/dev/null | head -10
  echo ""
  echo "=== Progress ==="
  for bench in sysbench redis nginx elasticsearch springboot; do
    count=$(find /home/ec2-user/benchmark/results/$bench -name "run*.log" -size +0 2>/dev/null | wc -l)
    last=$(tail -1 /home/ec2-user/benchmark/results/$bench.log 2>/dev/null | cut -c1-60)
    printf "%-12s: %2s/10  %s\n" "$bench" "$count" "$last"
  done
  echo ""
  sleep 60
done
