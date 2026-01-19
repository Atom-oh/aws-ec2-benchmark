#!/bin/bash
# Run missing benchmarks in parallel - with tolerations and anti-affinity
# Usage: ./run-missing-parallel-v2.sh [redis|nginx|springboot|all]

set -e
BENCHMARK_DIR="/home/ec2-user/benchmark/benchmarks"
NAMESPACE="benchmark"
MODE="${1:-all}"

# Deploy with toleration and anti-affinity injected
apply_template() {
  local TEMPLATE=$1
  local INSTANCE=$2
  local SAFE=$(echo "$INSTANCE" | tr '.' '-')
  local BENCHMARK_TYPE=$3  # redis, nginx, springboot

  # Create temp file with modifications
  sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      -e "s/\${INSTANCE_TYPE\/\/\.\/\-}/${SAFE}/g" \
      "$TEMPLATE" | \
  sed '/nodeSelector:/a\
      tolerations:\
        - key: "benchmark"\
          operator: "Equal"\
          value: "true"\
          effect: "NoSchedule"\
      affinity:\
        podAntiAffinity:\
          requiredDuringSchedulingIgnoredDuringExecution:\
            - labelSelector:\
                matchExpressions:\
                  - key: benchmark\
                    operator: In\
                    values:\
                      - redis\
                      - nginx\
                      - springboot\
              topologyKey: "kubernetes.io/hostname"' | \
  kubectl apply -f - 2>&1 || true
}

# Missing instances
REDIS_MISSING="c6gd.2xlarge c6gn.2xlarge c7gd.2xlarge m6gd.2xlarge m7gd.2xlarge r5dn.2xlarge r5n.2xlarge r6gd.2xlarge r7gd.2xlarge"

NGINX_MISSING="c6gd.2xlarge c6gn.2xlarge c7gd.2xlarge m5zn.2xlarge m6gd.2xlarge m6i.2xlarge m6id.2xlarge m6idn.2xlarge m6in.2xlarge m7gd.2xlarge m7i.2xlarge r5.2xlarge r5b.2xlarge r5d.2xlarge r5dn.2xlarge r5n.2xlarge r6gd.2xlarge r6i.2xlarge r6id.2xlarge r7gd.2xlarge r7i.2xlarge"

SPRINGBOOT_MISSING="c5a.2xlarge c5d.2xlarge c5n.2xlarge c6gd.2xlarge c6gn.2xlarge c6id.2xlarge c6in.2xlarge c7gd.2xlarge c7i.flex.2xlarge m5a.2xlarge m5ad.2xlarge m5d.2xlarge m5zn.2xlarge m6g.2xlarge m6gd.2xlarge m6id.2xlarge m6idn.2xlarge m6in.2xlarge m7gd.2xlarge m7i.2xlarge m7i-flex.2xlarge m8i.2xlarge r5.2xlarge r5a.2xlarge r5ad.2xlarge r5b.2xlarge r5d.2xlarge r5dn.2xlarge r5n.2xlarge r6g.2xlarge r6gd.2xlarge r6i.2xlarge r6id.2xlarge r7gd.2xlarge r7i.2xlarge r8i.2xlarge r8i-flex.2xlarge"

echo "============================================"
echo "Running Missing Benchmarks - Mode: $MODE"
echo "With tolerations and podAntiAffinity"
echo "============================================"

deploy_and_run_redis() {
  echo "=== Redis: Deploy servers and run benchmarks (9) ==="
  for i in $REDIS_MISSING; do
    echo "  Redis: $i"
    apply_template "${BENCHMARK_DIR}/redis/redis-server.yaml" "$i" "redis"
  done

  echo "  Waiting for Redis servers..."
  sleep 60

  for i in $REDIS_MISSING; do
    local SAFE=$(echo "$i" | tr '.' '-')
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/redis-server-${SAFE} --timeout=180s 2>/dev/null || true
    apply_template "${BENCHMARK_DIR}/redis/redis-benchmark.yaml" "$i" "redis"
  done
}

deploy_and_run_nginx() {
  echo "=== Nginx: Deploy servers and run benchmarks (21) ==="
  for i in $NGINX_MISSING; do
    echo "  Nginx: $i"
    apply_template "${BENCHMARK_DIR}/nginx/nginx-server.yaml" "$i" "nginx"
  done

  echo "  Waiting for Nginx servers..."
  sleep 60

  for i in $NGINX_MISSING; do
    local SAFE=$(echo "$i" | tr '.' '-')
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/nginx-server-${SAFE} --timeout=180s 2>/dev/null || true
    apply_template "${BENCHMARK_DIR}/nginx/nginx-benchmark.yaml" "$i" "nginx"
  done
}

deploy_and_run_springboot() {
  echo "=== Springboot: Deploy servers and run benchmarks (37) ==="
  for i in $SPRINGBOOT_MISSING; do
    echo "  Springboot: $i"
    apply_template "${BENCHMARK_DIR}/springboot/springboot-server.yaml" "$i" "springboot"
  done

  echo "  Waiting for Springboot servers..."
  sleep 90

  for i in $SPRINGBOOT_MISSING; do
    local SAFE=$(echo "$i" | tr '.' '-')
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/springboot-server-${SAFE} --timeout=180s 2>/dev/null || true
    apply_template "${BENCHMARK_DIR}/springboot/springboot-benchmark.yaml" "$i" "springboot"
  done
}

case "$MODE" in
  redis)
    deploy_and_run_redis
    ;;
  nginx)
    deploy_and_run_nginx
    ;;
  springboot)
    deploy_and_run_springboot
    ;;
  all)
    # Run all three in parallel
    deploy_and_run_redis &
    deploy_and_run_nginx &
    deploy_and_run_springboot &
    wait
    ;;
esac

echo ""
echo "============================================"
echo "Deployment complete!"
echo "Monitor: kubectl get pods -n benchmark"
echo "Jobs: kubectl get jobs -n benchmark"
echo "============================================"
