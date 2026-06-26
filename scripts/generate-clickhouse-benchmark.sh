#!/bin/bash
# ClickHouse ClickBench 벤치마크 스크립트
# - 각 인스턴스: 5세트 순차 (set1~set5), 세트마다 스냅샷 복구 PVC + Job
# - 인스턴스 간: 배치(기본 12개) 병렬 — EBS 스냅샷 복구/lazy-load/API 부하 관리
# - 결과: results/clickhouse/<instance>/setN.log  (포맷: 설계 §10)
# - 데이터: VolumeSnapshot `clickhouse-hits` (snap-024c86faa00cd0448, ClickHouse 24.8.14.39)
#
# Usage:
#   ./generate-clickhouse-benchmark.sh            # 전체 (ConfigMap + 51 인스턴스 × 5세트)
#   ./generate-clickhouse-benchmark.sh --force    # 기존 로그 무시하고 재실행
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BASE_DIR/results/clickhouse"
BENCHMARK_DIR="$BASE_DIR/benchmarks/clickhouse"
QUERIES_DIR="$BENCHMARK_DIR/queries"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"

NAMESPACE="benchmark"
SETS=5
# 인스턴스 간 완전 병렬 (스냅샷 독립 복구). benchmark-server NodePool CPU limit=480(120노드)이라
# 51개(204 CPU) 동시 실행 여유. 스케줄 불가 인스턴스는 wait_schedulable이 빠르게 skip.
CLICKHOUSE_VERSION="24.8.14.39"
JOB_TIMEOUT=2400         # 세트당 최대 대기 (초)
TEMPLATE="$BENCHMARK_DIR/clickhouse-clickbench.yaml"

FORCE_RERUN=false
[ "${1:-}" == "--force" ] && FORCE_RERUN=true

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log() { echo -e "[$(date '+%H:%M:%S')] $*"; }

# arch: instances-4vcpu.txt 2번째 컬럼(x86_64/arm64) → amd64/arm64
# awk 사용 (grep -P 비호환 환경 대비, 공백/탭 모두 허용)
get_arch() {
    local a
    a=$(awk -v i="$1" '$1==i {print $2}' "$INSTANCE_FILE")
    [ "$a" == "arm64" ] && echo "arm64" || echo "amd64"
}

# 인스턴스 목록 (주석/빈 줄 제외, 1번째 컬럼)
mapfile -t INSTANCES < <(grep -vE '^\s*#|^\s*$' "$INSTANCE_FILE" | awk '{print $1}')
log "인스턴스 ${#INSTANCES[@]}개 로드"

# 1) snap-024 VolumeSnapshot(clickhouse-hits-024) 보장 + readyToUse 확인
log "VolumeSnapshot clickhouse-hits-024 적용/확인..."
kubectl apply -f "$BENCHMARK_DIR/clickhouse-snapshot.yaml" >/dev/null 2>&1 || true
for i in $(seq 1 60); do
    ready=$(kubectl get volumesnapshot clickhouse-hits-024 -n "$NAMESPACE" -o jsonpath='{.status.readyToUse}' 2>/dev/null)
    [ "$ready" == "true" ] && break
    sleep 2
done
if [ "$(kubectl get volumesnapshot clickhouse-hits-024 -n "$NAMESPACE" -o jsonpath='{.status.readyToUse}' 2>/dev/null)" != "true" ]; then
    log "${RED}오류: VolumeSnapshot clickhouse-hits-024 가 ready 아님. 중단.${NC}"; exit 1
fi

# 2) 쿼리 ConfigMap 생성 (멱등)
log "쿼리 ConfigMap 생성/갱신..."
kubectl create configmap clickhouse-queries -n "$NAMESPACE" \
    --from-file="$QUERIES_DIR/queries.sql" \
    --from-file="$QUERIES_DIR/insert.sql" \
    --from-file="$QUERIES_DIR/join.sql" \
    --dry-run=client -o yaml | kubectl apply -f -

# 스케줄 가능 여부 확인: pod이 SCHED_WAIT 내에 Running/Succeeded 도달하면 0, 아니면 1(스케줄 불가)
SCHED_WAIT=300   # 5분 내 노드 미배정 시 프로비저닝 불가로 판단 (예: c7i-flex 2a/2c 미제공)
wait_schedulable() {
    local job="$1" t phase
    for t in $(seq 1 $((SCHED_WAIT / 5))); do
        phase=$(kubectl get pods -n "$NAMESPACE" -l job-name="${job}" --no-headers -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
        [ "$phase" = "Running" ] || [ "$phase" = "Succeeded" ] && return 0
        sleep 5
    done
    return 1
}

# 한 인스턴스의 5세트 순차 실행 (스냅샷 독립 복구이므로 인스턴스 간 완전 병렬)
run_instance() {
    local instance="$1"
    local safe_name arch
    safe_name=$(echo "$instance" | tr '.' '-')
    arch=$(get_arch "$instance")
    mkdir -p "$RESULTS_DIR/$instance"

    for SET in $(seq 1 "$SETS"); do
        local log_file="$RESULTS_DIR/$instance/set${SET}.log"
        if [ "$FORCE_RERUN" = false ] && [ -s "$log_file" ]; then
            continue
        fi
        local job="clickhouse-clickbench-${safe_name}-run${SET}"
        local pvc="clickhouse-data-${safe_name}-run${SET}"

        # 배포 (chained-pipe sed — CLAUDE.md 규칙)
        cat "$TEMPLATE" | \
            sed "s/INSTANCE_SAFE/${safe_name}/g" | \
            sed "s/INSTANCE_TYPE/${instance}/g" | \
            sed "s/RUN_NUMBER/${SET}/g" | \
            sed "s/CLICKHOUSE_VERSION/${CLICKHOUSE_VERSION}/g" | \
            sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g" | \
            kubectl apply -f - >/dev/null 2>&1

        # 스케줄 불가(프로비저닝 불가) 인스턴스는 빠르게 skip — 다른 인스턴스 블로킹 방지
        if ! wait_schedulable "$job"; then
            log "${YELLOW}스케줄 불가(프로비저닝 불가) — skip${NC}: $instance (남은 세트 생략)"
            kubectl delete job "$job" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
            kubectl delete pvc "$pvc" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
            return
        fi

        # 완료 대기
        if kubectl wait --for=condition=complete "job/${job}" -n "$NAMESPACE" --timeout="${JOB_TIMEOUT}s" >/dev/null 2>&1; then
            local pod
            pod=$(kubectl get pods -n "$NAMESPACE" -l job-name="${job}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
            [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" > "$log_file" 2>/dev/null
            log "${GREEN}수집${NC}: $instance set$SET"
        else
            log "${RED}실패/타임아웃${NC}: $instance set$SET"
            local pod
            pod=$(kubectl get pods -n "$NAMESPACE" -l job-name="${job}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
            [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" > "$log_file" 2>/dev/null
        fi

        # 정리 (다음 세트를 위해 Job + PVC 삭제)
        kubectl delete job "$job" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
        kubectl delete pvc "$pvc" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
    done
    log "[$instance] 5세트 완료"
}

# 3) 전체 동시 실행 (스냅샷 독립 복구 → 직렬 배치 불필요).
#    동시 실행 수는 Karpenter NodePool CPU limit(160=40노드)이 자연 throttle.
#    스케줄 불가 인스턴스는 wait_schedulable이 빠르게 skip하므로 healthy 인스턴스를 막지 않음.
for instance in "${INSTANCES[@]}"; do
    run_instance "$instance" &
done
wait

collected=$(find "$RESULTS_DIR" -name "set*.log" -size +0 2>/dev/null | wc -l)
log "${GREEN}전체 완료${NC}: $collected 로그 수집 (기대 $((${#INSTANCES[@]} * SETS)))"
