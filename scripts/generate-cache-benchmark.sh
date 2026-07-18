#!/bin/bash
# Redis/Valkey 계열 캐시 벤치마크 범용 실행기. Redis vs Valkey 재측정(2026-07) —
# io-threads 유무 4가지 변형(redis/redis-io4/valkey/valkey-io4)을 이 스크립트 하나로 돈다.
#
# 사용: generate-cache-benchmark.sh <name> <template.yaml> [runs]
#   name: results/<name>/ 하위에 로그 저장, 템플릿 job 이름 접두사와 일치해야 함
#   template.yaml: benchmarks/<name>/<name>-localhost-100m.yaml 형태 경로
#   runs: 반복 횟수(기본 3 — redis-benchmark 자체 내부 CV가 2~3%로 낮아 3회로도 통계적으로 유효)
set -uo pipefail

kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

NAME="${1:?usage: generate-cache-benchmark.sh <name> <template.yaml> [runs]}"
TEMPLATE="${2:?usage: generate-cache-benchmark.sh <name> <template.yaml> [runs]}"
RUNS="${3:-3}"

RESULTS_DIR="$BASE_DIR/results/$NAME"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"
NAMESPACE="benchmark"
JOB_TIMEOUT=7200   # 세대/아키텍처별 실측 편차 큼(Graviton4 ~22분, 5세대 AMD 최대 ~93분) — 최악 케이스 + 여유

FORCE_RERUN=false
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log(){ echo -e "[$(date '+%H:%M:%S')] [$NAME] $*"; }

mapfile -t INSTANCES < <(grep -vE '^\s*#|^\s*$' "$INSTANCE_FILE" | awk '{print $1}')
log "인스턴스 ${#INSTANCES[@]}개, ${RUNS}회 반복"

mkdir -p "$RESULTS_DIR"

find_pod(){ local job="$1" p; for t in 1 2 3 4 5; do
  p=$(kubectl get pods -n "$NAMESPACE" -l job-name="$job" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
  [ -n "$p" ] && { echo "$p"; return 0; }; sleep 2; done; return 1; }

run_instance(){
  local instance="$1" safe; safe=$(echo "$instance" | tr '.' '-')
  mkdir -p "$RESULTS_DIR/$instance"

  for RUN in $(seq 1 "$RUNS"); do
    local lf="$RESULTS_DIR/$instance/run${RUN}.log"
    if [ "$FORCE_RERUN" = false ] && [ -s "$lf" ] && grep -q "Benchmark Complete" "$lf" 2>/dev/null; then
      continue
    fi
    local job="${NAME}-100m-${safe}-${RUN}"
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
