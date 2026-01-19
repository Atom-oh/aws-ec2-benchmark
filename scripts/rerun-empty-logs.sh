#!/bin/bash
# Re-run empty sysbench logs with proper log collection

set -e
cd /home/ec2-user/benchmark

MAX_CONCURRENT=20
RESULTS_DIR="results"

echo "===== Sysbench Empty Log Re-run ====="
echo "CPU to run: $(wc -l < /tmp/cpu_rerun.txt)"
echo "Memory to run: $(wc -l < /tmp/mem_rerun.txt)"
echo ""

# Function to wait for job slot
wait_for_slot() {
  while true; do
    RUNNING=$(kubectl get jobs -n benchmark -l benchmark=sysbench -o json 2>/dev/null | jq '[.items[] | select(.status.active == 1)] | length' 2>/dev/null || echo 0)
    if [[ "$RUNNING" -lt "$MAX_CONCURRENT" ]]; then
      break
    fi
    sleep 5
  done
}

# Deploy CPU jobs
echo "=== Deploying CPU jobs ==="
while read inst run; do
  [[ -z "$inst" ]] && continue
  SAFE_NAME=$(echo $inst | tr '.' '-')
  wait_for_slot
  echo "  [START] $inst $run"
  sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
      -e "s/\${INSTANCE_TYPE}/${inst}/g" \
      benchmarks/system/sysbench-cpu.yaml | kubectl apply -f - 2>&1 | grep -q "created" || true
done < /tmp/cpu_rerun.txt

# Deploy Memory jobs
echo ""
echo "=== Deploying Memory jobs ==="
while read inst run; do
  [[ -z "$inst" ]] && continue
  SAFE_NAME=$(echo $inst | tr '.' '-')
  wait_for_slot
  echo "  [START] $inst $run"
  sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
      -e "s/\${INSTANCE_TYPE}/${inst}/g" \
      benchmarks/system/sysbench-memory.yaml | kubectl apply -f - 2>&1 | grep -q "created" || true
done < /tmp/mem_rerun.txt

echo ""
echo "All jobs deployed."
