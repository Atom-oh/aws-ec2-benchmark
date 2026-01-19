#!/bin/bash
# iperf3 Network Benchmark Orchestrator
# Usage: ./run-iperf3.sh [run_number]

RUN=${1:-1}
RESULTS_DIR="/home/ec2-user/benchmark/results/iperf3"
TEMPLATE="/home/ec2-user/benchmark/benchmarks/system/iperf3-network.yaml"
INSTANCE_FILE="/home/ec2-user/benchmark/config/instances-4vcpu.txt"

echo "=== iperf3 Benchmark Run $RUN ==="
echo "Started at: $(date)"

# Phase 1: Deploy all servers
echo ""
echo "=== Phase 1: Deploying iperf3 servers ==="

while IFS=$'\t' read -r instance arch mem || [[ -n "$instance" ]]; do
    [[ -z "$instance" || "$instance" == \#* ]] && continue

    SAFE_NAME=$(echo "$instance" | tr '.' '-')
    SERVER_NAME="iperf3-server-${SAFE_NAME}"

    # Check if server already exists
    if kubectl get deployment -n benchmark "$SERVER_NAME" &>/dev/null; then
        echo "[$instance] Server already exists"
        continue
    fi

    echo "[$instance] Deploying server..."

    # Extract and apply only Service + Deployment (not the Job)
    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/\${INSTANCE_TYPE}/${instance}/g" \
        "$TEMPLATE" | awk '/^---$/{n++} n<2{print}' | kubectl apply -f - 2>/dev/null

done < "$INSTANCE_FILE"

echo ""
echo "Waiting 60s for servers to start..."
sleep 60

# Phase 2: Deploy client jobs
echo ""
echo "=== Phase 2: Deploying iperf3 clients (run $RUN) ==="

deployed=0
while IFS=$'\t' read -r instance arch mem || [[ -n "$instance" ]]; do
    [[ -z "$instance" || "$instance" == \#* ]] && continue

    SAFE_NAME=$(echo "$instance" | tr '.' '-')
    DIR="$RESULTS_DIR/${SAFE_NAME}"
    mkdir -p "$DIR"

    # Skip if already have this run
    if [[ -f "$DIR/run${RUN}.log" ]] && [[ -s "$DIR/run${RUN}.log" ]]; then
        echo "[$instance] run${RUN} already exists, skipping"
        continue
    fi

    # Get server pod IP
    SERVER_POD=$(kubectl get pods -n benchmark -l "app=iperf3-server,instance-type=${instance}" --no-headers 2>/dev/null | grep Running | head -1 | awk '{print $1}')

    if [[ -z "$SERVER_POD" ]]; then
        echo "[$instance] Server not ready, skipping"
        continue
    fi

    SERVER_IP=$(kubectl get pod -n benchmark "$SERVER_POD" -o jsonpath='{.status.podIP}' 2>/dev/null)

    if [[ -z "$SERVER_IP" ]]; then
        echo "[$instance] Cannot get server IP, skipping"
        continue
    fi

    JOB_NAME="iperf3-benchmark-${SAFE_NAME}-run${RUN}"

    # Check if job already exists
    if kubectl get job -n benchmark "$JOB_NAME" &>/dev/null; then
        echo "[$instance] Job already exists"
        continue
    fi

    echo "[$instance] Deploying client -> $SERVER_IP"

    # Extract and apply only the Job part, with server IP
    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/\${INSTANCE_TYPE}/${instance}/g" \
        -e "s/IPERF_SERVER_IP/${SERVER_IP}/g" \
        "$TEMPLATE" | awk '/^---$/{n++} n>=2{print}' | \
        sed "s/name: iperf3-benchmark-${SAFE_NAME}/name: ${JOB_NAME}/" | \
        kubectl apply -f - 2>/dev/null

    ((deployed++))

    # Rate limit to avoid overwhelming API server
    if (( deployed % 10 == 0 )); then
        echo "Deployed $deployed jobs, pausing 5s..."
        sleep 5
    fi

done < "$INSTANCE_FILE"

echo ""
echo "=== Deployment Complete ==="
echo "Deployed: $deployed client jobs"
echo "Monitor with: kubectl get pods -n benchmark | grep iperf"
