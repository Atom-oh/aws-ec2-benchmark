#!/bin/bash
# Spring Boot Flex Instance Sustained Performance Test
# Tests flex instances with 10+ minute wrk to measure sustained (non-burst) performance

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BASE_DIR/results/springboot-flex"
BENCHMARK_DIR="$BASE_DIR/benchmarks/springboot"

NAMESPACE="benchmark"
WRK_DURATION="600"  # 10 minutes sustained test

# Flex instances only
FLEX_INSTANCES=(
    "c7i-flex.xlarge"
    "c8i-flex.xlarge"
    "m7i-flex.xlarge"
    "r8i-flex.xlarge"
)

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} $1"; }

mkdir -p "$RESULTS_DIR"

log "=== Spring Boot Flex Sustained Performance Test ==="
log "Testing ${#FLEX_INSTANCES[@]} flex instances with ${WRK_DURATION}s duration"

# Phase 1: Deploy Spring Boot servers for flex instances
log "Phase 1: Deploying Spring Boot servers..."

for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')

    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
        -e "s/ARCH/amd64/g" \
        "$BENCHMARK_DIR/springboot-server.yaml" | kubectl apply -f - 2>/dev/null || true

    log "Deployed: $INSTANCE"
done

log "Waiting for servers to be ready..."
sleep 60

# Wait for all pods to be ready
for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    kubectl wait --for=condition=ready pod -l app=springboot-server,instance-type="$INSTANCE" -n $NAMESPACE --timeout=300s 2>/dev/null || true
done

# Phase 2: Run sustained wrk tests
log "Phase 2: Running sustained wrk tests (${WRK_DURATION}s each)..."

for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    LOG_FILE="$RESULTS_DIR/${INSTANCE}-sustained.log"

    log "Testing: $INSTANCE (10 minutes)..."

    # Create wrk job with extended duration
    cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: wrk-flex-${SAFE_NAME}
  namespace: $NAMESPACE
spec:
  ttlSecondsAfterFinished: 3600
  backoffLimit: 0
  template:
    metadata:
      labels:
        benchmark: springboot-flex
        instance-type: "$INSTANCE"
    spec:
      restartPolicy: Never
      nodeSelector:
        node-type: benchmark-client
      tolerations:
        - key: "benchmark-client"
          operator: "Equal"
          value: "true"
          effect: "NoSchedule"
      containers:
        - name: wrk
          image: public.ecr.aws/docker/library/alpine:latest
          command: ["/bin/sh", "-c"]
          args:
            - |
              apk add --no-cache wrk curl

              HOST="springboot-server-${SAFE_NAME}"

              echo "===== Spring Boot Flex Sustained Test: $INSTANCE ====="
              echo "Timestamp: \$(date -Iseconds)"
              echo "Duration: ${WRK_DURATION}s (10 minutes)"
              echo ""

              # Wait for server
              echo "Waiting for Spring Boot server..."
              until curl -s http://\${HOST}:8080/actuator/health | grep -q "UP"; do
                sleep 5
              done
              echo "Server ready!"
              echo ""

              # Warm-up (30s)
              echo "=== Warm-up Phase (30s) ==="
              wrk -t2 -c50 -d30s http://\${HOST}:8080/ > /dev/null 2>&1
              echo "Warm-up complete"
              echo ""

              # Main sustained test (10 minutes)
              echo "=== Sustained Test - 2 threads, 100 connections, ${WRK_DURATION}s ==="
              wrk -t2 -c100 -d${WRK_DURATION}s --latency http://\${HOST}:8080/
              echo ""

              # Additional high-load test (5 minutes)
              echo "=== High Load Test - 2 threads, 200 connections, 300s ==="
              wrk -t2 -c200 -d300s --latency http://\${HOST}:8080/
              echo ""

              echo "===== Flex Sustained Test Complete ====="
          resources:
            requests:
              cpu: "2"
              memory: "2Gi"
EOF

done

# Wait for all jobs to complete
log "Waiting for all tests to complete (this will take ~15 minutes per instance)..."

for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    JOB_NAME="wrk-flex-${SAFE_NAME}"
    LOG_FILE="$RESULTS_DIR/${INSTANCE}-sustained.log"

    # Wait for job completion
    kubectl wait --for=condition=complete job/$JOB_NAME -n $NAMESPACE --timeout=1800s 2>/dev/null || true

    # Collect logs
    POD=$(kubectl get pods -n $NAMESPACE -l job-name=$JOB_NAME --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -n "$POD" ]; then
        kubectl logs -n $NAMESPACE "$POD" > "$LOG_FILE" 2>/dev/null
        log "Collected: $LOG_FILE"
    fi
done

# Phase 3: Cleanup
log "Phase 3: Cleanup..."

for INSTANCE in "${FLEX_INSTANCES[@]}"; do
    SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
    kubectl delete job "wrk-flex-${SAFE_NAME}" -n $NAMESPACE --ignore-not-found 2>/dev/null || true
    kubectl delete deployment "springboot-server-${SAFE_NAME}" -n $NAMESPACE --ignore-not-found 2>/dev/null || true
    kubectl delete service "springboot-server-${SAFE_NAME}" -n $NAMESPACE --ignore-not-found 2>/dev/null || true
done

# Summary
log "=== Summary ==="
echo "Results saved to: $RESULTS_DIR"
ls -la "$RESULTS_DIR"
