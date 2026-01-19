#!/bin/bash
# Re-run empty Elasticsearch benchmarks

cd /home/ec2-user/benchmark

# Empty logs to re-run
EMPTY_RUNS=(
    "c5d.xlarge:1"
    "c5d.xlarge:4"
    "c7g.xlarge:1"
    "m5.xlarge:2"
    "m5ad.xlarge:1"
    "m6g.xlarge:1"
    "m6id.xlarge:1"
    "m7g.xlarge:1"
    "m7i-flex.xlarge:1"
    "m8g.xlarge:1"
    "r5a.xlarge:1"
    "r6g.xlarge:1"
    "r7g.xlarge:1"
    "r8g.xlarge:1"
)

get_arch() {
    local instance=$1
    if [[ "$instance" =~ ^[cmr][6-8]g ]]; then
        echo "arm64"
    else
        echo "amd64"
    fi
}

for entry in "${EMPTY_RUNS[@]}"; do
    INSTANCE="${entry%%:*}"
    RUN="${entry##*:}"
    SAFE_NAME=$(echo $INSTANCE | tr '.' '-')
    ARCH=$(get_arch $INSTANCE)

    echo "=== $INSTANCE run$RUN (arch: $ARCH) ==="

    # Delete existing job if any
    kubectl delete job -n benchmark "es-coldstart-${SAFE_NAME}" --ignore-not-found 2>/dev/null
    sleep 2

    # Deploy new job
    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
        -e "s/ARCH/${ARCH}/g" \
        benchmarks/elasticsearch/elasticsearch-coldstart.yaml | kubectl apply -f -

    echo "  Waiting for job to complete..."
    # Wait for completion (max 10 minutes)
    for i in {1..60}; do
        STATUS=$(kubectl get job -n benchmark "es-coldstart-${SAFE_NAME}" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
        FAILED=$(kubectl get job -n benchmark "es-coldstart-${SAFE_NAME}" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null)

        if [ "$STATUS" = "True" ]; then
            echo "  Job completed!"
            break
        fi
        if [ "$FAILED" = "True" ]; then
            echo "  Job failed!"
            break
        fi
        sleep 10
    done

    # Collect log
    POD=$(kubectl get pods -n benchmark -l job-name="es-coldstart-${SAFE_NAME}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -n "$POD" ]; then
        LOG_DIR="results/elasticsearch/${INSTANCE}"
        mkdir -p "$LOG_DIR"
        kubectl logs -n benchmark "$POD" > "${LOG_DIR}/run${RUN}.log" 2>/dev/null
        SIZE=$(stat -c%s "${LOG_DIR}/run${RUN}.log" 2>/dev/null || echo 0)
        echo "  Log saved: ${LOG_DIR}/run${RUN}.log ($SIZE bytes)"
    fi

    # Cleanup
    kubectl delete job -n benchmark "es-coldstart-${SAFE_NAME}" --ignore-not-found 2>/dev/null

    echo ""
done

echo "=== All ES re-runs completed ==="
