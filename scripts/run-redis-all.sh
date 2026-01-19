#!/bin/bash
# Redis Benchmark - All 51 Instance Types
# Deploys Redis servers and benchmark jobs in parallel

set -e

cd /home/ec2-user/benchmark

# Instance list
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

echo "===== Redis Benchmark - ${#INSTANCES[@]} Instances ====="
echo "Start: $(date)"

# Ensure results directory exists
mkdir -p results/redis-new

# Step 1: Deploy all Redis servers in parallel
echo ""
echo "=== Step 1: Deploying Redis Servers ==="
for INSTANCE in "${INSTANCES[@]}"; do
  SAFE=$(echo $INSTANCE | tr '.' '-')

  # Check if already exists
  if kubectl get deployment redis-server-${SAFE} -n benchmark &>/dev/null; then
    echo "  [SKIP] redis-server-${SAFE} already exists"
    continue
  fi

  # Deploy Redis server
  sed -e "s/INSTANCE_SAFE/${SAFE}/g" \
      -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      benchmarks/redis/redis-server.yaml | kubectl apply -f - 2>/dev/null

  echo "  [DEPLOY] redis-server-${SAFE}"
done

echo ""
echo "Waiting 60s for Redis servers to start..."
sleep 60

# Step 2: Check Redis server status
echo ""
echo "=== Step 2: Checking Redis Server Status ==="
READY_COUNT=0
for INSTANCE in "${INSTANCES[@]}"; do
  SAFE=$(echo $INSTANCE | tr '.' '-')
  STATUS=$(kubectl get pods -n benchmark -l app=redis-server,instance-type=${INSTANCE} --no-headers 2>/dev/null | awk '{print $3}' | head -1)
  if [ "$STATUS" == "Running" ]; then
    ((READY_COUNT++))
    echo "  [READY] redis-server-${SAFE}"
  else
    echo "  [WAIT]  redis-server-${SAFE}: $STATUS"
  fi
done
echo "Ready: $READY_COUNT / ${#INSTANCES[@]}"

# Step 3: Deploy benchmark jobs for ready servers
echo ""
echo "=== Step 3: Deploying Benchmark Jobs ==="
for INSTANCE in "${INSTANCES[@]}"; do
  SAFE=$(echo $INSTANCE | tr '.' '-')

  # Check if Redis server is running
  STATUS=$(kubectl get pods -n benchmark -l app=redis-server,instance-type=${INSTANCE} --no-headers 2>/dev/null | awk '{print $3}' | head -1)
  if [ "$STATUS" != "Running" ]; then
    echo "  [SKIP] Waiting for redis-server-${SAFE}"
    continue
  fi

  # Check if benchmark job already exists
  if kubectl get job redis-benchmark-${SAFE} -n benchmark &>/dev/null; then
    echo "  [SKIP] redis-benchmark-${SAFE} already exists"
    continue
  fi

  # Deploy benchmark job
  sed -e "s/INSTANCE_SAFE/${SAFE}/g" \
      -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      benchmarks/redis/redis-benchmark.yaml | kubectl apply -f - 2>/dev/null

  echo "  [DEPLOY] redis-benchmark-${SAFE}"
done

echo ""
echo "===== Deployment Complete ====="
echo "Check status: kubectl get pods -n benchmark -l benchmark=redis-benchmark"
echo "End: $(date)"
