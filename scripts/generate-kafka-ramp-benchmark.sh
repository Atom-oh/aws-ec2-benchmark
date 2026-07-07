#!/bin/bash
# Kafka 램프업/포화점/지연곡선 시나리오(Phase 3): 인스턴스별 브로커(Deployment) 1개 배포 → 90초
# 버스트크레딧 고갈 → 8-way 병렬 produce 목표치를 8단계로 올려 실제/목표 비율 99.5% 미달 지점(포화점)
# 탐지 → 로그 수집 → 브로커 정리. 인스턴스 간 완전 병렬. 100% 기준점(BASELINE_MB)은 이미 완료된
# Phase 2(results/kafka-max, uncompressed 8-way) 실측치를 읽어 계산 — 반드시 Phase 2가 먼저 있어야 함.
set -uo pipefail

# 공유 kubeconfig 환경 대비: 다른 동시 세션이 current-context를 바꿔도 영향받지 않도록 고정.
kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
NAME="kafka"
RESULTS_DIR="$BASE_DIR/results/kafka-ramp"
MAX_RESULTS_DIR="$BASE_DIR/results/kafka-max"
BENCHMARK_DIR="$BASE_DIR/benchmarks/$NAME"
SERVER_TEMPLATE="$BENCHMARK_DIR/kafka-server.yaml"
CLIENT_TEMPLATE="$BENCHMARK_DIR/kafka-benchmark-ramp.yaml"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"
NAMESPACE="benchmark"
JOB_TIMEOUT=1200
SCHED_WAIT=300
KAFKA_VERSION="3.9.1"

FORCE_RERUN=false; [ "${1:-}" == "--force" ] && FORCE_RERUN=true
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log(){ echo -e "[$(date '+%H:%M:%S')] $*"; }

get_arch(){ local a; a=$(awk -v i="$1" '$1==i{print $2}' "$INSTANCE_FILE"); [ "$a" = arm64 ] && echo arm64 || echo amd64; }

# Phase 2(uncompressed 8-way) 5회 median MB/s → 램프의 100% 기준점. 없으면 250(베이스라인 근사) 대체.
baseline_mb(){
  local instance="$1" f
  local vals=()
  for f in "$MAX_RESULTS_DIR/$instance"/uncompressed-run*.log; do
    [ -s "$f" ] || continue
    local v; v=$(grep "^PRODUCE_TOTAL_MB_PER_SEC:" "$f" | awk '{print $2}')
    [ -n "$v" ] && vals+=("$v")
  done
  if [ "${#vals[@]}" -eq 0 ]; then echo 250; return; fi
  printf '%s\n' "${vals[@]}" | sort -n | awk '{a[NR]=$1} END{print (NR%2) ? a[(NR+1)/2] : (a[NR/2]+a[NR/2+1])/2}'
}

mapfile -t INSTANCES < <(grep -vE '^\s*#|^\s*$' "$INSTANCE_FILE" | awk '{print $1}')
log "인스턴스 ${#INSTANCES[@]}개 x 램프 1회(8단계)"

kubectl apply -f "$BENCHMARK_DIR/kafka-storageclass.yaml" >/dev/null 2>&1

wait_server_schedulable(){ local instance="$1" t p; for t in $(seq 1 $((SCHED_WAIT/5))); do
  p=$(kubectl get pods -n "$NAMESPACE" -l "app=kafka-server,instance-type=${instance}" --no-headers -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
  [ "$p" = Running ] && return 0; sleep 5; done; return 1; }

run_instance(){
  local instance="$1" safe arch base; safe=$(echo "$instance"|tr '.' '-'); arch=$(get_arch "$instance")
  mkdir -p "$RESULTS_DIR/$instance"
  local lf="$RESULTS_DIR/$instance/run1.log"
  if [ "$FORCE_RERUN" = false ] && [ -s "$lf" ]; then
    log "${GREEN}스킵(완료됨)${NC}: $instance"; return
  fi
  base=$(baseline_mb "$instance")

  cat "$SERVER_TEMPLATE" \
    | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${instance}/g" \
    | sed "s/KAFKA_VERSION/${KAFKA_VERSION}/g" \
    | sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g" \
    | kubectl apply -f - >/dev/null 2>&1

  if ! wait_server_schedulable "$instance"; then
    log "${YELLOW}브로커 스케줄 불가 — skip${NC}: $instance"
    kubectl delete deployment "kafka-server-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
    kubectl delete service "kafka-server-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
    kubectl delete pvc "kafka-data-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
    return
  fi
  kubectl wait --for=condition=available "deployment/kafka-server-${safe}" -n "$NAMESPACE" --timeout=300s >/dev/null 2>&1

  local job="kafka-ramp-${safe}-run1"
  cat "$CLIENT_TEMPLATE" \
    | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${instance}/g" \
    | sed "s/RUN_NUMBER/1/g"          | sed "s/KAFKA_VERSION/${KAFKA_VERSION}/g" \
    | sed "s/BASELINE_MB/${base}/g" \
    | kubectl apply -f - >/dev/null 2>&1

  # pod 조회를 재시도(최대 5회) — job-name 라벨 조회가 API 순간 부하로 빈 값을 줄 때가 있어,
  # 예전엔 이 경우도 "수집 완료"로 잘못 로그되면서 실제로는 빈 로그 파일이 남는 버그가 있었음.
  find_pod(){ local job="$1" p; for t in 1 2 3 4 5; do
    p=$(kubectl get pods -n "$NAMESPACE" -l job-name="$job" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    [ -n "$p" ] && { echo "$p"; return 0; }; sleep 2; done; return 1; }

  if kubectl wait --for=condition=complete "job/$job" -n "$NAMESPACE" --timeout="${JOB_TIMEOUT}s" >/dev/null 2>&1; then
    local pod; pod=$(find_pod "$job")
    if [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" > "$lf" 2>/dev/null && [ -s "$lf" ]; then
      log "${GREEN}수집${NC}: $instance (baseline=${base}MB/s)"
    else
      log "${RED}실패(로그 수집 불가, pod=${pod:-없음})${NC}: $instance"
    fi
  else
    log "${RED}실패/타임아웃${NC}: $instance"
    local pod; pod=$(find_pod "$job")
    [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" > "$lf" 2>/dev/null
  fi
  kubectl delete job "$job" -n "$NAMESPACE" --wait=false >/dev/null 2>&1

  kubectl delete deployment "kafka-server-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  kubectl delete service "kafka-server-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  kubectl delete pvc "kafka-data-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  log "[$instance] 완료"
}

for instance in "${INSTANCES[@]}"; do run_instance "$instance" & done
wait
log "${GREEN}전체 완료${NC}: $(find "$RESULTS_DIR" -name 'run*.log' -size +0 | wc -l) 로그"
# python3 scripts/generate-kafka-report.py
