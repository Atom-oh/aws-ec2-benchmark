#!/bin/bash
# 벤치마크 실행 및 로그 수집 스크립트
# 각 Job이 완료되면 즉시 로그를 수집

BENCHMARK=$1  # e.g., sysbench-memory, sysbench-cpu, stress-ng, fio-disk
TEMPLATE=$2   # YAML 템플릿 경로
RESULTS_DIR=$3  # 결과 저장 디렉토리
MAX_CONCURRENT=${4:-15}  # 최대 동시 실행 수

if [ -z "$BENCHMARK" ] || [ -z "$TEMPLATE" ] || [ -z "$RESULTS_DIR" ]; then
    echo "Usage: $0 <benchmark-name> <template.yaml> <results-dir> [max-concurrent]"
    exit 1
fi

# 인스턴스 목록 (첫 번째 컬럼만)
INSTANCES=$(cat /home/ec2-user/benchmark/config/instances-4vcpu.txt | grep -v "^#" | grep -v "^$" | cut -f1)
TOTAL=$(echo "$INSTANCES" | wc -l)

echo "=== Starting $BENCHMARK ==="
echo "Total instances: $TOTAL"
echo "Max concurrent: $MAX_CONCURRENT"
echo ""

mkdir -p "$RESULTS_DIR"

# 로그 수집 함수
collect_logs() {
    local job_name=$1
    local instance=$2
    local run=$3
    local dir="$RESULTS_DIR/$instance"
    mkdir -p "$dir"

    # Pod 이름 찾기
    local pod=$(kubectl get pods -n benchmark -l job-name=$job_name --no-headers 2>/dev/null | awk '{print $1}' | head -1)
    if [ -n "$pod" ]; then
        kubectl logs -n benchmark "$pod" > "${dir}/${run}.log" 2>/dev/null
        if [ -s "${dir}/${run}.log" ]; then
            echo "[Collected] $instance $run"
            return 0
        fi
    fi
    return 1
}

# 완료된 Job들의 로그 수집
collect_completed() {
    for job in $(kubectl get jobs -n benchmark -l benchmark=${BENCHMARK%%_*} --no-headers 2>/dev/null | grep "1/1" | awk '{print $1}'); do
        instance=$(echo $job | sed "s/${BENCHMARK}-//" | tr '-' '.')
        run="run1"
        dir="$RESULTS_DIR/$instance"
        if [ ! -f "${dir}/${run}.log" ]; then
            collect_logs "$job" "$instance" "$run"
        fi
    done
}

# 배치 배포 및 대기
deployed=0
for instance in $INSTANCES; do
    SAFE_NAME=$(echo $instance | tr '.' '-')
    JOB_NAME="${BENCHMARK}-${SAFE_NAME}"

    # Job 배포
    sed -e "s/INSTANCE_SAFE/${SAFE_NAME}/g" \
        -e "s/\${INSTANCE_TYPE}/${instance}/g" \
        "$TEMPLATE" | kubectl apply -f - > /dev/null 2>&1

    echo "[Deploy] $instance"
    ((deployed++))

    # MAX_CONCURRENT 도달 시 완료 대기
    if [ $deployed -ge $MAX_CONCURRENT ]; then
        echo ""
        echo "Waiting for batch to complete..."
        while true; do
            running=$(kubectl get jobs -n benchmark -l benchmark=${BENCHMARK%%_*} --no-headers 2>/dev/null | grep -c "Running")
            complete=$(kubectl get jobs -n benchmark -l benchmark=${BENCHMARK%%_*} --no-headers 2>/dev/null | grep -c "1/1")

            # 완료된 Job 로그 수집
            collect_completed

            if [ "$running" -lt $((MAX_CONCURRENT / 2)) ]; then
                break
            fi
            sleep 10
        done
        echo "Continuing deployment..."
        echo ""
    fi
done

# 모든 Job 완료 대기
echo ""
echo "=== Waiting for all jobs to complete ==="
while true; do
    total_jobs=$(kubectl get jobs -n benchmark -l benchmark=${BENCHMARK%%_*} --no-headers 2>/dev/null | wc -l)
    complete=$(kubectl get jobs -n benchmark -l benchmark=${BENCHMARK%%_*} --no-headers 2>/dev/null | grep -c "1/1")
    running=$(kubectl get jobs -n benchmark -l benchmark=${BENCHMARK%%_*} --no-headers 2>/dev/null | grep -c "Running")

    echo "$(date +%H:%M:%S) - $complete/$total_jobs complete ($running running)"

    # 완료된 Job 로그 수집
    collect_completed

    if [ "$complete" -eq "$total_jobs" ] && [ "$total_jobs" -gt 0 ]; then
        break
    fi
    sleep 15
done

# 최종 로그 수집
echo ""
echo "=== Final log collection ==="
collect_completed

# 결과 확인
collected=$(find "$RESULTS_DIR" -name "*.log" -type f | wc -l)
echo ""
echo "=== $BENCHMARK Complete ==="
echo "Collected: $collected logs"
echo "Results: $RESULTS_DIR"
