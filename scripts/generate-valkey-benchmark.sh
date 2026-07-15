#!/bin/bash
# Valkey 벤치마크 실행: benchmarks/valkey/valkey-localhost-100m.yaml (Redis와 동일 방법론 —
# 로컬호스트 단일 Job, 서버/클라이언트 분리 없음) 을 인스턴스별 5회 반복 실행.
# 인스턴스 간 완전 병렬. Results: results/valkey/{instance}/run{N}.log
set -uo pipefail

# 공유 kubeconfig 환경 대비: 다른 동시 세션이 current-context를 바꿔도 영향받지 않도록 고정
# (CLAUDE.md Kafka 섹션 교훈).
kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
NAME="valkey"
RESULTS_DIR="$BASE_DIR/results/$NAME"
TEMPLATE="$BASE_DIR/benchmarks/valkey/valkey-localhost-100m.yaml"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"
NAMESPACE="benchmark"
RUNS=5
JOB_TIMEOUT=7200   # 세대/아키텍처별 실측 편차 큼(Redis 이력 기준 Graviton4 ~22분, 5세대 AMD 최대 ~93분) — 최악 케이스 + 여유

FORCE_RERUN=false; [ "${1:-}" == "--force" ] && FORCE_RERUN=true
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log(){ echo -e "[$(date '+%H:%M:%S')] $*"; }

mapfile -t INSTANCES < <(grep -vE '^\s*#|^\s*$' "$INSTANCE_FILE" | awk '{print $1}')
log "인스턴스 ${#INSTANCES[@]}개"

mkdir -p "$RESULTS_DIR"

# pod 조회 재시도(최대 5회) — job-name 라벨 조회가 API 순간 부하로 빈 값을 줄 때가 있어,
# 재시도 없이 바로 실패로 넘기면 "수집 완료" 로그는 찍히는데 실제로는 빈 로그가 남는 버그가 생김
# (Kafka 스크립트에서 실제로 겪은 문제, 동일 패턴 재사용).
find_pod(){ local job="$1" p; for t in 1 2 3 4 5; do
  p=$(kubectl get pods -n "$NAMESPACE" -l job-name="$job" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
  [ -n "$p" ] && { echo "$p"; return 0; }; sleep 2; done; return 1; }

run_instance(){
  local instance="$1" safe; safe=$(echo "$instance" | tr '.' '-')
  mkdir -p "$RESULTS_DIR/$instance"

  for RUN in $(seq 1 "$RUNS"); do
    local lf="$RESULTS_DIR/$instance/run${RUN}.log"
    if [ "$FORCE_RERUN" = false ] && [ -s "$lf" ] && grep -q "Benchmark Complete" "$lf" 2>/dev/null; then
      continue   # resumable: skip done runs
    fi
    local job="valkey-100m-${safe}-${RUN}"
    kubectl delete job "$job" -n "$NAMESPACE" --ignore-not-found >/dev/null 2>&1

    cat "$TEMPLATE" \
      | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/\${INSTANCE_TYPE}/${instance}/g" \
      | sed "s/RUN_NUM/${RUN}/g" \
      | kubectl apply -f - >/dev/null 2>&1

    if kubectl wait --for=condition=complete "job/$job" -n "$NAMESPACE" --timeout="${JOB_TIMEOUT}s" >/dev/null 2>&1; then
      local pod; pod=$(find_pod "$job")
      if [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" 2>/dev/null | tr '\r' '\n' > "$lf" && [ -s "$lf" ]; then
        log "${GREEN}수집${NC}: $instance run$RUN"
      else
        log "${RED}실패(로그 수집 불가, pod=${pod:-없음})${NC}: $instance run$RUN"
      fi
    else
      log "${RED}실패/타임아웃${NC}: $instance run$RUN"
      local pod; pod=$(find_pod "$job")
      [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" 2>/dev/null | tr '\r' '\n' > "$lf"
    fi
    kubectl delete job "$job" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  done
  log "[$instance] 완료"
}

# full-parallel: 인스턴스 간 완전 병렬 (NodePool CPU limit이 자연스럽게 스로틀)
for instance in "${INSTANCES[@]}"; do run_instance "$instance" & done
wait

TOTAL_LOGS=$(find "$RESULTS_DIR" -name "run*.log" -size +0 | wc -l)
EXPECTED=$((${#INSTANCES[@]} * RUNS))
log "${GREEN}전체 완료${NC}: $TOTAL_LOGS / $EXPECTED 로그"

for instance in "${INSTANCES[@]}"; do
  for RUN in $(seq 1 "$RUNS"); do
    lf="$RESULTS_DIR/$instance/run${RUN}.log"
    if [ ! -s "$lf" ]; then
      echo -e "${YELLOW}Missing${NC}: $instance/run${RUN}.log"
    elif ! grep -q "Benchmark Complete" "$lf" 2>/dev/null; then
      echo -e "${YELLOW}Incomplete (타임아웃 등으로 중간에 끊김)${NC}: $instance/run${RUN}.log"
    fi
  done
done
