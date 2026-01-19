#!/bin/bash
# 벤치마크 5회 실행 스크립트
# Usage: ./run-5-times.sh <benchmark> <template> <results-dir>

BENCHMARK=$1
TEMPLATE=$2
RESULTS_DIR=$3
LABEL=${4:-$BENCHMARK}  # Job label for benchmark (default: benchmark name)

if [ -z "$BENCHMARK" ] || [ -z "$TEMPLATE" ] || [ -z "$RESULTS_DIR" ]; then
    echo "Usage: $0 <benchmark-name> <template.yaml> <results-dir> [label]"
    exit 1
fi

INSTANCES=$(cat /home/ec2-user/benchmark/config/instances-4vcpu.txt | grep -v "^#" | grep -v "^$" | cut -f1)
mkdir -p "$RESULTS_DIR"

echo "=== $BENCHMARK 5회 실행 ==="
echo "Template: $TEMPLATE"
echo "Results: $RESULTS_DIR"
echo ""

for RUN in 1 2 3 4 5; do
    echo "=========================================="
    echo "=== Run $RUN / 5 ==="
    echo "=========================================="

    # 이미 완료된 인스턴스 스킵
    DEPLOYED=0
    for instance in $INSTANCES; do
        dir="$RESULTS_DIR/$instance"
        if [ -s "${dir}/run${RUN}.log" ]; then
            continue  # 이미 수집됨
        fi

        SAFE_NAME=$(echo $instance | tr '.' '-')
        JOB_NAME="${BENCHMARK}-${SAFE_NAME}-run${RUN}"

        # Job 이름에 run 번호 추가
        sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
            -e "s/\${INSTANCE_TYPE}/${instance}/g" \
            -e "s/name: ${BENCHMARK}-/name: ${BENCHMARK}-/g" \
            "$TEMPLATE" | sed "s/name: ${BENCHMARK}-${SAFE_NAME}/name: ${JOB_NAME}/" | \
            kubectl apply -f - > /dev/null 2>&1

        echo "[Deploy] $JOB_NAME"
        ((DEPLOYED++))
    done

    echo ""
    echo "Deployed $DEPLOYED jobs for run $RUN"

    if [ "$DEPLOYED" -eq 0 ]; then
        echo "All instances already have run${RUN}.log - skipping"
        continue
    fi

    # 완료 대기 및 로그 수집
    echo "Waiting for completion..."
    while true; do
        total=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep -c "${BENCHMARK}.*run${RUN}")
        complete=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "${BENCHMARK}.*run${RUN}" | grep -c "1/1")

        # 완료된 Job 로그 수집
        for pod in $(kubectl get pods -n benchmark --no-headers 2>/dev/null | grep "${BENCHMARK}.*run${RUN}" | grep -E "Completed|Succeeded" | awk '{print $1}'); do
            job=$(echo $pod | sed 's/-[a-z0-9]*$//')
            instance=$(echo $job | sed "s/${BENCHMARK}-//" | sed "s/-run${RUN}//" | tr '-' '.')
            dir="$RESULTS_DIR/$instance"
            mkdir -p "$dir"
            if [ ! -s "${dir}/run${RUN}.log" ]; then
                kubectl logs -n benchmark "$pod" > "${dir}/run${RUN}.log" 2>/dev/null
                if [ -s "${dir}/run${RUN}.log" ]; then
                    echo "[Collected] $instance run${RUN}"
                fi
            fi
        done

        echo "$(date +%H:%M:%S) - $complete/$total complete"

        if [ "$complete" -eq "$total" ] && [ "$total" -gt 0 ]; then
            break
        fi
        sleep 30
    done

    # Job 정리
    echo "Cleaning up run $RUN jobs..."
    kubectl delete jobs -n benchmark -l benchmark=$LABEL --field-selector status.successful=1 --wait=false 2>/dev/null
    sleep 5

    echo ""
done

# 최종 결과
echo ""
echo "=== $BENCHMARK Complete ==="
total_logs=$(find "$RESULTS_DIR" -name "run*.log" -size +0 | wc -l)
complete_instances=0
for d in "$RESULTS_DIR"/*/; do
    if [ -d "$d" ]; then
        runs=$(ls "$d"/run*.log 2>/dev/null | wc -l)
        if [ "$runs" -ge 5 ]; then
            ((complete_instances++))
        fi
    fi
done
echo "Total logs: $total_logs / 255"
echo "Complete instances (5 runs): $complete_instances / 51"
