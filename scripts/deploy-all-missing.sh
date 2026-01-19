#!/bin/bash
# Deploy all missing benchmarks with proper tolerations and podAntiAffinity

BENCHMARK_DIR="/home/ec2-user/benchmark/benchmarks"

# Function to deploy a benchmark
deploy_benchmark() {
  local type="$1"      # redis, nginx, springboot
  local instance="$2"
  local safe_name=$(echo "$instance" | tr '.' '-')

  echo "[$(date +%H:%M:%S)] Deploying $type for $instance"

  # Deploy server first - use | as delimiter to avoid issues with //
  sed -e 's|\${INSTANCE_TYPE//./-}|'"${safe_name}"'|g' \
      -e 's|\${INSTANCE_TYPE}|'"${instance}"'|g' \
      "${BENCHMARK_DIR}/${type}/${type}-server.yaml" | kubectl apply -f - 2>&1

  # Deploy benchmark job
  sed -e 's|\${INSTANCE_TYPE//./-}|'"${safe_name}"'|g' \
      -e 's|\${INSTANCE_TYPE}|'"${instance}"'|g' \
      "${BENCHMARK_DIR}/${type}/${type}-benchmark.yaml" | kubectl apply -f - 2>&1

  echo "[$(date +%H:%M:%S)] Deployed $type for $instance"
}

# Read missing instances
REDIS_MISSING=$(cat /tmp/redis_missing.txt 2>/dev/null)
NGINX_MISSING=$(cat /tmp/nginx_missing.txt 2>/dev/null)
SPRINGBOOT_MISSING=$(cat /tmp/springboot_missing.txt 2>/dev/null)

echo "=== Starting Parallel Deployment ==="
echo "Redis: $(echo "$REDIS_MISSING" | wc -l) instances"
echo "Nginx: $(echo "$NGINX_MISSING" | wc -l) instances"
echo "Springboot: $(echo "$SPRINGBOOT_MISSING" | wc -l) instances"
echo ""

# Deploy all in parallel using background processes
# Deploy Redis
for inst in $REDIS_MISSING; do
  deploy_benchmark "redis" "$inst" &
done

# Deploy Nginx
for inst in $NGINX_MISSING; do
  deploy_benchmark "nginx" "$inst" &
done

# Deploy Springboot
for inst in $SPRINGBOOT_MISSING; do
  deploy_benchmark "springboot" "$inst" &
done

# Wait for all deployments to complete
wait

echo ""
echo "=== Deployment Complete ==="
sleep 3
echo "Pods:"
kubectl get pods -n benchmark --no-headers 2>/dev/null | wc -l
echo "Jobs:"
kubectl get jobs -n benchmark --no-headers 2>/dev/null | wc -l
echo "Deployments:"
kubectl get deployments -n benchmark --no-headers 2>/dev/null | wc -l
