#!/bin/bash
# Re-run missing sysbench benchmarks

set -e
cd /home/ec2-user/benchmark

MAX_CONCURRENT=20
RESULTS_DIR="results"
TYPE=$1  # cpu or memory

if [[ -z "$TYPE" ]]; then
  echo "Usage: $0 <cpu|memory>"
  exit 1
fi

if [[ "$TYPE" == "cpu" ]]; then
  LIST_FILE="/tmp/cpu_rerun.txt"
elif [[ "$TYPE" == "memory" ]]; then
  LIST_FILE="/tmp/mem_rerun.txt"
fi

if [[ ! -f "$LIST_FILE" ]]; then
  echo "List file not found: $LIST_FILE"
  exit 1
fi

echo "===== Sysbench $TYPE Re-run ====="
echo "Total to re-run: $(wc -l < $LIST_FILE)"
echo ""

# Process each line
while read inst run; do
  [[ -z "$inst" ]] && continue

  SAFE_NAME=$(echo $inst | tr '.' '-')
  LOG_FILE="$RESULTS_DIR/sysbench-$TYPE/$inst/${run}.log"

  # Check if already has valid data
  if [[ -s "$LOG_FILE" ]]; then
    echo "  [SKIP] $inst $run - valid data exists"
    continue
  fi

  # Check concurrent jobs
  while true; do
    RUNNING=$(kubectl get jobs -n benchmark -l benchmark=sysbench -o json 2>/dev/null | jq '[.items[] | select(.status.active == 1)] | length')
    if [[ "$RUNNING" -lt "$MAX_CONCURRENT" ]]; then
      break
    fi
    sleep 5
  done

  # Deploy job
  echo "  [START] $inst $run"
  sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
      -e "s/\${INSTANCE_TYPE}/${inst}/g" \
      "benchmarks/system/sysbench-$TYPE.yaml" | kubectl apply -f - 2>&1 | grep -E "created|configured" || true

done < "$LIST_FILE"

echo ""
echo "All jobs deployed. Waiting for completion..."

# Wait for all jobs to complete
while true; do
  RUNNING=$(kubectl get jobs -n benchmark -l benchmark=sysbench -o json 2>/dev/null | jq '[.items[] | select(.status.active == 1)] | length')
  if [[ "$RUNNING" -eq 0 ]]; then
    break
  fi
  echo "  Running: $RUNNING jobs..."
  sleep 10
done

echo ""
echo "Collecting logs..."

# Collect logs from completed jobs
for job in $(kubectl get jobs -n benchmark -l benchmark=sysbench,test-type=$TYPE -o jsonpath='{.items[*].metadata.name}'); do
  inst=$(echo "$job" | sed "s/^sysbench-$TYPE-//" | tr '-' '.')

  POD=$(kubectl get pods -n benchmark -l job-name=$job --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
  STATUS=$(kubectl get job -n benchmark $job -o jsonpath='{.status.succeeded}' 2>/dev/null)

  if [[ "$STATUS" == "1" ]] && [[ -n "$POD" ]]; then
    mkdir -p "$RESULTS_DIR/sysbench-$TYPE/$inst"

    # Find the run number that needs this log
    for run in run1 run2 run3 run4 run5; do
      LOG_FILE="$RESULTS_DIR/sysbench-$TYPE/$inst/${run}.log"
      if [[ ! -s "$LOG_FILE" ]]; then
        echo "  [OK] $inst $run"
        kubectl logs -n benchmark "$POD" > "$LOG_FILE" 2>/dev/null
        break
      fi
    done
  fi

  # Clean up job
  kubectl delete job "$job" -n benchmark 2>/dev/null || true
done

echo ""
echo "===== Complete ====="
echo "Valid logs: $(find $RESULTS_DIR/sysbench-$TYPE -name "run*.log" ! -empty | wc -l)/255"
