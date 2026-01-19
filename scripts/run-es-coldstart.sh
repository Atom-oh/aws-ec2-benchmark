#!/bin/bash
# Elasticsearch Cold Start Benchmark - All 51 Instances
# Usage: ./run-es-coldstart.sh [intel|graviton|all]

set -e

TEMPLATE="/tmp/elasticsearch-coldstart-v7.yaml"
MODE="${1:-all}"

# Intel/AMD instances (amd64) - 33개
INTEL_INSTANCES=(
  # C5 series
  "c5.2xlarge" "c5a.2xlarge" "c5d.2xlarge" "c5n.2xlarge"
  # C6i series
  "c6i.2xlarge" "c6id.2xlarge" "c6in.2xlarge"
  # C7i series
  "c7i.2xlarge" "c7i.flex.2xlarge"
  # C8i series
  "c8i.2xlarge" "c8i.flex.2xlarge"
  # M5 series
  "m5.2xlarge" "m5a.2xlarge" "m5ad.2xlarge" "m5d.2xlarge" "m5zn.2xlarge"
  # M6i series
  "m6i.2xlarge" "m6id.2xlarge" "m6idn.2xlarge" "m6in.2xlarge"
  # M7i series
  "m7i.2xlarge" "m7i-flex.2xlarge"
  # M8i series
  "m8i.2xlarge"
  # R5 series
  "r5.2xlarge" "r5a.2xlarge" "r5ad.2xlarge" "r5b.2xlarge" "r5d.2xlarge" "r5dn.2xlarge" "r5n.2xlarge"
  # R6i series
  "r6i.2xlarge" "r6id.2xlarge"
  # R7i series
  "r7i.2xlarge"
  # R8i series
  "r8i.2xlarge" "r8i-flex.2xlarge"
)

# Graviton instances (arm64) - 18개
GRAVITON_INSTANCES=(
  # C6g series
  "c6g.2xlarge" "c6gd.2xlarge" "c6gn.2xlarge"
  # C7g series
  "c7g.2xlarge" "c7gd.2xlarge"
  # C8g series
  "c8g.2xlarge"
  # M6g series
  "m6g.2xlarge" "m6gd.2xlarge"
  # M7g series
  "m7g.2xlarge" "m7gd.2xlarge"
  # M8g series
  "m8g.2xlarge"
  # R6g series
  "r6g.2xlarge" "r6gd.2xlarge"
  # R7g series
  "r7g.2xlarge" "r7gd.2xlarge"
  # R8g series
  "r8g.2xlarge"
)

deploy_job() {
  local INSTANCE=$1
  local ARCH=$2

  # Convert instance name to safe k8s name (replace . with -)
  local SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')

  echo "Deploying: $INSTANCE (arch: $ARCH, job: es-coldstart-$SAFE_NAME)"

  sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
      -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
      -e "s/ARCH/${ARCH}/g" \
      "$TEMPLATE" | kubectl apply -f -
}

echo "============================================"
echo "Elasticsearch Cold Start Benchmark"
echo "Template: $TEMPLATE"
echo "Mode: $MODE"
echo "============================================"

case "$MODE" in
  intel)
    echo "Deploying Intel/AMD instances (${#INTEL_INSTANCES[@]} total)"
    for INSTANCE in "${INTEL_INSTANCES[@]}"; do
      deploy_job "$INSTANCE" "amd64"
    done
    ;;
  graviton)
    echo "Deploying Graviton instances (${#GRAVITON_INSTANCES[@]} total)"
    for INSTANCE in "${GRAVITON_INSTANCES[@]}"; do
      deploy_job "$INSTANCE" "arm64"
    done
    ;;
  all)
    echo "Deploying ALL instances ($(( ${#INTEL_INSTANCES[@]} + ${#GRAVITON_INSTANCES[@]} )) total)"
    echo ""
    echo "--- Intel/AMD (amd64) ---"
    for INSTANCE in "${INTEL_INSTANCES[@]}"; do
      deploy_job "$INSTANCE" "amd64"
    done
    echo ""
    echo "--- Graviton (arm64) ---"
    for INSTANCE in "${GRAVITON_INSTANCES[@]}"; do
      deploy_job "$INSTANCE" "arm64"
    done
    ;;
  *)
    echo "Usage: $0 [intel|graviton|all]"
    exit 1
    ;;
esac

echo ""
echo "============================================"
echo "Deployment complete!"
echo "Monitor with: kubectl get jobs -n benchmark -l benchmark=elasticsearch"
echo "============================================"
