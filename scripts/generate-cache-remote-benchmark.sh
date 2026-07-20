#!/bin/bash
# Redis/Valkey 원격 토폴로지(server=대상 인스턴스 전용 / client=benchmark-client 노드풀) 실행기.
# localhost 방식이 io-threads 효과를 CPU 경합으로 왜곡시키는 문제(Valkey io4 -26% 역효과)를
# 확인 후 도입 — smoke test(c8g.xlarge)에서 io-threads 4가 SET/GET +22~30% 정상 효과로 반전됨.
#
# AZ 고정(2026-07 재확인): 54개를 임의 zone에 배치하면 zone 자체가 latency를 2배 이상 좌우함을
# 발견(c8g가 하필 2b에 떨어져 c8i-flex보다 느리게 나온 것처럼 보였으나, 실은 zone 아티팩트였고
# 같은 zone(2c)의 m8g/r8g는 낮은 latency). 서버 nodeSelector에 topology.kubernetes.io/zone을
# 고정해 클라이언트(podAffinity로 서버 zone을 따라감)까지 전부 같은 zone에서 실행되도록
# 강제한다 — AZ 편향을 제거해야 인스턴스 타입 간 비교가 공정해짐.
#
# 사용: generate-cache-remote-benchmark.sh <name> <server-template.yaml> <client-template.yaml> <app-label> [runs] [az]
#   name: results/<name>-remote/ 하위에 로그 저장 (예: redis, redis-io4, valkey, valkey-io4)
#   app-label: 서버 Deployment/Service의 app 레이블 (예: redis-remote-server)
#   az: 기본 ap-northeast-2a(54개 중 c7i-flex.xlarge만 이 zone에 오퍼링이 없어 자동으로 2b로 오버라이드)
set -uo pipefail

kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

NAME="${1:?usage: generate-cache-remote-benchmark.sh <name> <server-template> <client-template> <app-label> [runs] [az]}"
SERVER_TEMPLATE="${2:?server-template.yaml required}"
CLIENT_TEMPLATE="${3:?client-template.yaml required}"
APP_LABEL="${4:?app-label required (e.g. redis-remote-server)}"
RUNS="${5:-3}"
DEFAULT_AZ="${6:-ap-northeast-2a}"

RESULTS_DIR="$BASE_DIR/results/${NAME}-remote"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"
NAMESPACE="benchmark"
SERVER_READY_TIMEOUT=180
JOB_TIMEOUT=2400  # 원격 토폴로지 대부분 4~6분이나, 5세대 AMD(r5a 등)는 40K ops/s대라 20M req에 500s+ 소요 — 넉넉히 30분

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log(){ echo -e "[$(date '+%H:%M:%S')] [$NAME-remote] $*"; }

mapfile -t INSTANCES < <(grep -vE '^\s*#|^\s*$' "$INSTANCE_FILE" | awk '{print $1}')
log "인스턴스 ${#INSTANCES[@]}개, ${RUNS}회 반복"

mkdir -p "$RESULTS_DIR"

find_pod(){ local sel="$1" p; for t in 1 2 3 4 5; do
  p=$(kubectl get pods -n "$NAMESPACE" -l "$sel" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
  [ -n "$p" ] && { echo "$p"; return 0; }; sleep 2; done; return 1; }

# c7i-flex.xlarge는 ap-northeast-2a에 오퍼링이 없음(aws ec2 describe-instance-type-offerings로
# 확인) — 이 인스턴스만 2b로 오버라이드. 다른 53개는 전부 DEFAULT_AZ 하나로 통일.
az_for(){ local instance="$1"; [ "$instance" = "c7i-flex.xlarge" ] && echo "ap-northeast-2b" || echo "$DEFAULT_AZ"; }

run_instance(){
  local instance="$1" safe; safe=$(echo "$instance" | tr '.' '-')
  local az; az=$(az_for "$instance")
  mkdir -p "$RESULTS_DIR/$instance"

  local need_run=false
  for RUN in $(seq 1 "$RUNS"); do
    [ -s "$RESULTS_DIR/$instance/run${RUN}.log" ] && grep -q "Benchmark Complete" "$RESULTS_DIR/$instance/run${RUN}.log" 2>/dev/null || need_run=true
  done
  if [ "$need_run" = false ]; then
    log "[$instance] 스킵(이미 완료)"
    return
  fi

  cat "$SERVER_TEMPLATE" \
    | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s|\${INSTANCE_TYPE}|${instance}|g" | sed "s|\${AZ}|${az}|g" \
    | kubectl apply -f - >/dev/null 2>&1

  if ! kubectl wait --for=condition=available "deployment/${NAME}-remote-${safe}" -n "$NAMESPACE" --timeout="${SERVER_READY_TIMEOUT}s" >/dev/null 2>&1; then
    log "${RED}서버 기동 실패${NC}: $instance"
    kubectl delete deployment,service -n "$NAMESPACE" "${NAME}-remote-${safe}" --ignore-not-found >/dev/null 2>&1
    return
  fi

  for RUN in $(seq 1 "$RUNS"); do
    local lf="$RESULTS_DIR/$instance/run${RUN}.log"
    if [ -s "$lf" ] && grep -q "Benchmark Complete" "$lf" 2>/dev/null; then
      continue
    fi
    local job="${NAME}-remote-bench-${safe}-${RUN}"
    kubectl delete job "$job" -n "$NAMESPACE" --ignore-not-found >/dev/null 2>&1

    cat "$CLIENT_TEMPLATE" \
      | sed "s/JOB_NAME/${job}/g" \
      | sed "s/SERVICE_NAME/${NAME}-remote-${safe}/g" \
      | sed "s/SERVER_APP_LABEL/${APP_LABEL}/g" \
      | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s|\${INSTANCE_TYPE}|${instance}|g" \
      | sed "s/RUN_NUM/${RUN}/g" \
      | kubectl apply -f - >/dev/null 2>&1

    if kubectl wait --for=condition=complete "job/$job" -n "$NAMESPACE" --timeout="${JOB_TIMEOUT}s" >/dev/null 2>&1; then
      local pod; pod=$(find_pod "job-name=$job")
      if [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" 2>/dev/null | tr '\r' '\n' > "$lf" && [ -s "$lf" ]; then
        log "${GREEN}수집${NC}: $instance run$RUN"
      else
        log "${RED}실패(로그 수집 불가, pod=${pod:-없음})${NC}: $instance run$RUN"
      fi
    else
      log "${RED}실패/타임아웃${NC}: $instance run$RUN"
      local pod; pod=$(find_pod "job-name=$job")
      [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" 2>/dev/null | tr '\r' '\n' > "$lf"
    fi
    kubectl delete job "$job" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  done

  kubectl delete deployment,service,configmap -n "$NAMESPACE" -l "app=${APP_LABEL},instance-type=${instance}" --ignore-not-found >/dev/null 2>&1
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
