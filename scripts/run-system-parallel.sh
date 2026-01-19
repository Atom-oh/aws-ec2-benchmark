#!/bin/bash
# 시스템 벤치마크 병렬 실행 스크립트
# stress-ng, fio-disk, iperf3를 5회씩 실행

RESULTS_BASE="/home/ec2-user/benchmark/results"
TEMPLATES="/home/ec2-user/benchmark/benchmarks/system"
INSTANCES=$(cat /home/ec2-user/benchmark/config/instances-4vcpu.txt | grep -v "^#" | grep -v "^$" | cut -f1)

# 로그 수집 함수
collect_logs() {
    local bench=$1
    local label=$2

    for pod in $(kubectl get pods -n benchmark --no-headers 2>/dev/null | grep "$bench" | grep -E "Completed|Succeeded" | awk '{print $1}'); do
        job=$(echo $pod | sed 's/-[a-z0-9]*$//')
        instance=$(echo $job | sed "s/${bench}-//" | sed 's/-run[0-9]$//' | tr '-' '.')
        run=$(echo $job | grep -oE 'run[0-9]+$' || echo "run1")
        dir="$RESULTS_BASE/$bench/$instance"
        mkdir -p "$dir"

        if [ ! -s "${dir}/${run}.log" ]; then
            kubectl logs -n benchmark "$pod" > "${dir}/${run}.log" 2>/dev/null
            if [ -s "${dir}/${run}.log" ]; then
                echo "[Collected] $bench $instance $run"
            fi
        fi
    done
}

# 완료된 Job 정리
cleanup_jobs() {
    local bench=$1
    for j in $(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "$bench" | grep "1/1" | awk '{print $1}'); do
        kubectl delete job -n benchmark "$j" --wait=false > /dev/null 2>&1
    done
}

# 특정 벤치마크의 부족한 run 배포
deploy_missing() {
    local bench=$1
    local template=$2
    local label=$3

    for instance in $INSTANCES; do
        SAFE_NAME=$(echo $instance | tr '.' '-')

        for run in 1 2 3 4 5; do
            # 디렉토리 이름 정규화 (flex 처리)
            dir_name=$(echo $instance | sed 's/-flex/.flex/')
            dir="$RESULTS_BASE/$bench/$dir_name"

            if [ -s "${dir}/run${run}.log" ]; then
                continue  # 이미 있음
            fi

            JOB_NAME="${bench}-${SAFE_NAME}-run${run}"

            # 이미 실행 중인지 확인
            if kubectl get job -n benchmark "$JOB_NAME" > /dev/null 2>&1; then
                continue
            fi

            # Job 배포
            sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
                -e "s/\${INSTANCE_TYPE}/${instance}/g" \
                -e "s/name: ${bench}-${SAFE_NAME}/name: ${JOB_NAME}/" \
                "$template" | kubectl apply -f - > /dev/null 2>&1

            echo "[Deploy] $JOB_NAME"
        done
    done
}

echo "=== 시스템 벤치마크 병렬 실행 ==="
echo "벤치마크: stress-ng, fio-disk, iperf3"
echo "목표: 각 51 인스턴스 x 5회 = 255"
echo ""

# 초기 배포
echo "=== Phase 1: 초기 배포 ==="
deploy_missing "stress-ng" "$TEMPLATES/stress-ng.yaml" "stress-ng"
deploy_missing "fio-disk" "$TEMPLATES/fio-disk.yaml" "fio"
deploy_missing "iperf3" "$TEMPLATES/iperf3-network.yaml" "iperf"

echo ""
echo "=== Phase 2: 모니터링 및 수집 ==="

while true; do
    echo ""
    echo "=== $(date +%H:%M:%S) ==="

    # 각 벤치마크 상태 확인
    for bench in stress-ng fio-disk iperf3; do
        jobs=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep -c "$bench" || echo 0)
        complete=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "$bench" | grep -c "1/1" || echo 0)
        logs=$(find "$RESULTS_BASE/$bench" -name "run*.log" -size +0 2>/dev/null | wc -l)
        echo "[$bench] Jobs: $jobs, Complete: $complete, Logs: $logs/255"

        # 로그 수집
        collect_logs "$bench" "$bench"

        # 완료된 Job 정리
        cleanup_jobs "$bench"
    done

    # 총 로그 수 확인
    total_stress=$(find "$RESULTS_BASE/stress-ng" -name "run*.log" -size +0 2>/dev/null | wc -l)
    total_fio=$(find "$RESULTS_BASE/fio-disk" -name "run*.log" -size +0 2>/dev/null | wc -l)
    total_iperf=$(find "$RESULTS_BASE/iperf3" -name "run*.log" -size +0 2>/dev/null | wc -l)

    # 부족한 run 추가 배포
    if [ "$total_stress" -lt 255 ]; then
        deploy_missing "stress-ng" "$TEMPLATES/stress-ng.yaml" "stress-ng" 2>/dev/null
    fi
    if [ "$total_fio" -lt 255 ]; then
        deploy_missing "fio-disk" "$TEMPLATES/fio-disk.yaml" "fio" 2>/dev/null
    fi
    if [ "$total_iperf" -lt 255 ]; then
        deploy_missing "iperf3" "$TEMPLATES/iperf3-network.yaml" "iperf" 2>/dev/null
    fi

    # 완료 체크
    if [ "$total_stress" -ge 255 ] && [ "$total_fio" -ge 255 ] && [ "$total_iperf" -ge 255 ]; then
        echo ""
        echo "=== 모든 벤치마크 완료! ==="
        break
    fi

    # 실행 중인 Job이 없고 아직 완료 안됐으면 재배포
    running=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep -E "stress-ng|fio-disk|iperf3" | wc -l)
    if [ "$running" -eq 0 ]; then
        echo "No jobs running, redeploying..."
        deploy_missing "stress-ng" "$TEMPLATES/stress-ng.yaml" "stress-ng"
        deploy_missing "fio-disk" "$TEMPLATES/fio-disk.yaml" "fio"
        deploy_missing "iperf3" "$TEMPLATES/iperf3-network.yaml" "iperf"
    fi

    sleep 60
done

echo ""
echo "=== 최종 결과 ==="
echo "stress-ng: $(find $RESULTS_BASE/stress-ng -name 'run*.log' -size +0 | wc -l) / 255"
echo "fio-disk: $(find $RESULTS_BASE/fio-disk -name 'run*.log' -size +0 | wc -l) / 255"
echo "iperf3: $(find $RESULTS_BASE/iperf3 -name 'run*.log' -size +0 | wc -l) / 255"
