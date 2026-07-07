#!/bin/bash
# Kafka 포화(saturation) 시나리오 실행: 인스턴스별 브로커(Deployment) 1개 배포 → 3개 압축
# 시나리오(uncompressed/lz4/zstd) × 5 run = 15회 8-way 병렬 클라이언트 Job 순차 실행 → 로그 수집 →
# 브로커 정리. 인스턴스 간에는 완전 병렬. 베이스라인(generate-kafka-benchmark.sh)과 동일한 5회 반복
# 컨벤션, 결과는 별도 디렉터리(results/kafka-max).
set -uo pipefail

# 공유 kubeconfig 환경 대비: 다른 동시 세션이 current-context를 바꿔도 영향받지 않도록 고정
# (실제로 이 세션에서 무관한 다른 작업이 kubeconfig의 current-context를 바꿔놓은 적이 있었음).
kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
NAME="kafka"
RESULTS_DIR="$BASE_DIR/results/kafka-max"
BENCHMARK_DIR="$BASE_DIR/benchmarks/$NAME"
SERVER_TEMPLATE="$BENCHMARK_DIR/kafka-server.yaml"
CLIENT_TEMPLATE="$BENCHMARK_DIR/kafka-benchmark-max.yaml"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"
NAMESPACE="benchmark"
CODECS=(uncompressed lz4 zstd)
RUNS=5
JOB_TIMEOUT=1200
SCHED_WAIT=300
KAFKA_VERSION="3.9.1"

FORCE_RERUN=false; [ "${1:-}" == "--force" ] && FORCE_RERUN=true
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log(){ echo -e "[$(date '+%H:%M:%S')] $*"; }

get_arch(){ local a; a=$(awk -v i="$1" '$1==i{print $2}' "$INSTANCE_FILE"); [ "$a" = arm64 ] && echo arm64 || echo amd64; }

mapfile -t INSTANCES < <(grep -vE '^\s*#|^\s*$' "$INSTANCE_FILE" | awk '{print $1}')
log "인스턴스 ${#INSTANCES[@]}개 x 시나리오 ${#CODECS[@]}개 x run ${RUNS}회"

kubectl apply -f "$BENCHMARK_DIR/kafka-storageclass.yaml" >/dev/null 2>&1
log "gp3-kafka StorageClass 적용(idempotent)"

wait_server_schedulable(){ local instance="$1" t p; for t in $(seq 1 $((SCHED_WAIT/5))); do
  p=$(kubectl get pods -n "$NAMESPACE" -l "app=kafka-server,instance-type=${instance}" --no-headers -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
  [ "$p" = Running ] && return 0; sleep 5; done; return 1; }

# pod 조회 재시도(최대 5회) — job-name 라벨 조회가 API 순간 부하로 빈 값을 줄 때가 있어,
# 재시도 없이 바로 실패로 넘기면 "수집 완료" 로그는 찍히는데 실제로는 빈 로그가 남는 버그가 생김.
find_pod(){ local job="$1" p; for t in 1 2 3 4 5; do
  p=$(kubectl get pods -n "$NAMESPACE" -l job-name="$job" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
  [ -n "$p" ] && { echo "$p"; return 0; }; sleep 2; done; return 1; }

run_instance(){
  local instance="$1" safe arch; safe=$(echo "$instance"|tr '.' '-'); arch=$(get_arch "$instance")
  mkdir -p "$RESULTS_DIR/$instance"

  local done_count=0 total=$(( ${#CODECS[@]} * RUNS ))
  for codec in "${CODECS[@]}"; do for RUN in $(seq 1 "$RUNS"); do
    [ -s "$RESULTS_DIR/$instance/${codec}-run${RUN}.log" ] && done_count=$((done_count+1))
  done; done
  if [ "$FORCE_RERUN" = false ] && [ "$done_count" -eq "$total" ]; then
    log "${GREEN}스킵(완료됨)${NC}: $instance"; return
  fi

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

  for codec in "${CODECS[@]}"; do
    for RUN in $(seq 1 "$RUNS"); do
      local lf="$RESULTS_DIR/$instance/${codec}-run${RUN}.log"
      [ "$FORCE_RERUN" = false ] && [ -s "$lf" ] && continue
      local job="kafka-max-${safe}-${codec}-run${RUN}"
      cat "$CLIENT_TEMPLATE" \
        | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${instance}/g" \
        | sed "s/RUN_NUMBER/${RUN}/g"     | sed "s/KAFKA_VERSION/${KAFKA_VERSION}/g" \
        | sed "s/CODEC/${codec}/g" \
        | kubectl apply -f - >/dev/null 2>&1

      if kubectl wait --for=condition=complete "job/$job" -n "$NAMESPACE" --timeout="${JOB_TIMEOUT}s" >/dev/null 2>&1; then
        local pod; pod=$(find_pod "$job")
        if [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" > "$lf" 2>/dev/null && [ -s "$lf" ]; then
          log "${GREEN}수집${NC}: $instance $codec run$RUN"
        else
          log "${RED}실패(로그 수집 불가, pod=${pod:-없음})${NC}: $instance $codec run$RUN"
        fi
      else
        log "${RED}실패/타임아웃${NC}: $instance $codec run$RUN"
        local pod; pod=$(find_pod "$job")
        [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" > "$lf" 2>/dev/null
      fi
      kubectl delete job "$job" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
    done
  done

  kubectl delete deployment "kafka-server-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  kubectl delete service "kafka-server-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  kubectl delete pvc "kafka-data-${safe}" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  log "[$instance] 완료"
}

for instance in "${INSTANCES[@]}"; do run_instance "$instance" & done
wait
log "${GREEN}전체 완료${NC}: $(find "$RESULTS_DIR" -name '*-run*.log' -size +0 | wc -l) 로그"
# python3 scripts/generate-kafka-report.py
