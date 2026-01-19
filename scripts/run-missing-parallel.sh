#!/bin/bash
# Run missing benchmarks in parallel
# Usage: ./run-missing-parallel.sh [redis|nginx|springboot|all]

set -e
BENCHMARK_DIR="/home/ec2-user/benchmark/benchmarks"
NAMESPACE="benchmark"
MODE="${1:-all}"

# Deploy using sed substitution
apply_template() {
  local TEMPLATE=$1
  local INSTANCE=$2
  local SAFE=$(echo "$INSTANCE" | tr '.' '-')

  sed -e "s/\${INSTANCE_TYPE}/${INSTANCE}/g" \
      -e "s/\${INSTANCE_TYPE\/\/\.\/\-}/${SAFE}/g" \
      "$TEMPLATE" | kubectl apply -f - 2>/dev/null
}

# Missing instances
REDIS_MISSING="c6gd.2xlarge c6gn.2xlarge c7gd.2xlarge m6gd.2xlarge m7gd.2xlarge r5dn.2xlarge r5n.2xlarge r6gd.2xlarge r7gd.2xlarge"

NGINX_MISSING="c6gd.2xlarge c6gn.2xlarge c7gd.2xlarge m5zn.2xlarge m6gd.2xlarge m6i.2xlarge m6id.2xlarge m6idn.2xlarge m6in.2xlarge m7gd.2xlarge m7i.2xlarge r5.2xlarge r5b.2xlarge r5d.2xlarge r5dn.2xlarge r5n.2xlarge r6gd.2xlarge r6i.2xlarge r6id.2xlarge r7gd.2xlarge r7i.2xlarge"

SPRINGBOOT_MISSING="c5a.2xlarge c5d.2xlarge c5n.2xlarge c6gd.2xlarge c6gn.2xlarge c6id.2xlarge c6in.2xlarge c7gd.2xlarge c7i.flex.2xlarge m5a.2xlarge m5ad.2xlarge m5d.2xlarge m5zn.2xlarge m6g.2xlarge m6gd.2xlarge m6id.2xlarge m6idn.2xlarge m6in.2xlarge m7gd.2xlarge m7i.2xlarge m7i-flex.2xlarge m8i.2xlarge r5.2xlarge r5a.2xlarge r5ad.2xlarge r5b.2xlarge r5d.2xlarge r5dn.2xlarge r5n.2xlarge r6g.2xlarge r6gd.2xlarge r6i.2xlarge r6id.2xlarge r7gd.2xlarge r7i.2xlarge r8i.2xlarge r8i-flex.2xlarge"

echo "============================================"
echo "Running Missing Benchmarks - Mode: $MODE"
echo "============================================"

deploy_redis_all() {
  echo "=== Deploying Redis Servers (9) ==="
  for i in $REDIS_MISSING; do
    echo "  Redis server: $i"
    apply_template "${BENCHMARK_DIR}/redis/redis-server.yaml" "$i" || true
  done
}

run_redis_benchmarks() {
  echo "=== Running Redis Benchmarks ==="
  for i in $REDIS_MISSING; do
    local SAFE=$(echo "$i" | tr '.' '-')
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/redis-server-${SAFE} --timeout=180s 2>/dev/null || true
  done
  sleep 5
  for i in $REDIS_MISSING; do
    echo "  Redis benchmark: $i"
    apply_template "${BENCHMARK_DIR}/redis/redis-benchmark.yaml" "$i" || true
  done
}

deploy_nginx_all() {
  echo "=== Deploying Nginx Servers (21) ==="
  for i in $NGINX_MISSING; do
    echo "  Nginx server: $i"
    apply_template "${BENCHMARK_DIR}/nginx/nginx-server.yaml" "$i" || true
  done
}

run_nginx_benchmarks() {
  echo "=== Running Nginx Benchmarks ==="
  for i in $NGINX_MISSING; do
    local SAFE=$(echo "$i" | tr '.' '-')
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/nginx-server-${SAFE} --timeout=180s 2>/dev/null || true
  done
  sleep 5
  for i in $NGINX_MISSING; do
    echo "  Nginx benchmark: $i"
    apply_template "${BENCHMARK_DIR}/nginx/nginx-benchmark.yaml" "$i" || true
  done
}

deploy_springboot_all() {
  echo "=== Deploying Springboot Servers (37) ==="
  for i in $SPRINGBOOT_MISSING; do
    echo "  Springboot server: $i"
    apply_template "${BENCHMARK_DIR}/springboot/springboot-server.yaml" "$i" || true
  done
}

run_springboot_benchmarks() {
  echo "=== Running Springboot Benchmarks ==="
  for i in $SPRINGBOOT_MISSING; do
    local SAFE=$(echo "$i" | tr '.' '-')
    kubectl wait --for=condition=available -n ${NAMESPACE} deployment/springboot-server-${SAFE} --timeout=180s 2>/dev/null || true
  done
  sleep 5
  for i in $SPRINGBOOT_MISSING; do
    echo "  Springboot benchmark: $i"
    apply_template "${BENCHMARK_DIR}/springboot/springboot-benchmark.yaml" "$i" || true
  done
}

case "$MODE" in
  redis)
    deploy_redis_all
    sleep 60
    run_redis_benchmarks
    ;;
  nginx)
    deploy_nginx_all
    sleep 60
    run_nginx_benchmarks
    ;;
  springboot)
    deploy_springboot_all
    sleep 60
    run_springboot_benchmarks
    ;;
  all)
    # Deploy all servers first (parallel)
    deploy_redis_all &
    deploy_nginx_all &
    deploy_springboot_all &
    wait

    echo "=== Waiting for servers to be ready (90s) ==="
    sleep 90

    # Run all benchmarks
    run_redis_benchmarks &
    run_nginx_benchmarks &
    run_springboot_benchmarks &
    wait
    ;;
esac

echo ""
echo "============================================"
echo "Deployment complete!"
echo "Monitor: kubectl get pods -n benchmark"
echo "Jobs: kubectl get jobs -n benchmark"
echo "============================================"
