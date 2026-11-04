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

# INSTANCES_OVERRIDE="c8g.xlarge c8i.xlarge" 처럼 공백 구분 목록을 주면 config 대신 그 목록만 실행(스모크 테스트용)
if [ -n "${INSTANCES_OVERRIDE:-}" ]; then
  read -ra INSTANCES <<< "$INSTANCES_OVERRIDE"
else
  mapfile -t INSTANCES < <(grep -vE '^\s*#|^\s*$' "$INSTANCE_FILE" | awk '{print $1}')
fi
log "인스턴스 ${#INSTANCES[@]}개, ${RUNS}회 반복"

mkdir -p "$RESULTS_DIR"

find_pod(){ local sel="$1" p; for t in 1 2 3 4 5; do
  p=$(kubectl get pods -n "$NAMESPACE" -l "$sel" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
  [ -n "$p" ] && { echo "$p"; return 0; }; sleep 2; done; return 1; }

# AZ는 EC2 오퍼링 API로 정한다: DEFAULT_AZ에 그 타입이 있으면 DEFAULT_AZ, 없으면 FALLBACK_AZS 순서로
# 첫 오퍼링 AZ. (이전에는 c7i-flex만 2b로 하드코딩 — 2a 기본일 때 결과는 동일.) 2026-11 web 실행에서
# 2a의 c6in.2xlarge(클라이언트) On-Demand가 InsufficientInstanceCapacity라 기본 AZ를 2c로 바꿔야 했는데,
# 2c에는 c7i-flex/m6gd/m7gd/r6gd/r8gd가 없어 하드코딩으로는 대응할 수 없었다.
FALLBACK_AZS="${FALLBACK_AZS:-ap-northeast-2b ap-northeast-2c ap-northeast-2a}"
declare -A OFFERED=()
while read -r it zone; do OFFERED["$it|$zone"]=1; done < <(
  aws ec2 describe-instance-type-offerings --region ap-northeast-2 --location-type availability-zone \
    --filters "Name=instance-type,Values=$(IFS=,; echo "${INSTANCES[*]}")" \
    --query 'InstanceTypeOfferings[].[InstanceType,Location]' --output text)
[ ${#OFFERED[@]} -gt 0 ] || { log "${RED}오퍼링 조회 실패 — AWS CLI 자격증명 확인${NC}"; exit 1; }
az_for(){
  local instance="$1" z
  [ -n "${OFFERED["$instance|$DEFAULT_AZ"]:-}" ] && { echo "$DEFAULT_AZ"; return; }
  for z in $FALLBACK_AZS; do [ -n "${OFFERED["$instance|$z"]:-}" ] && { echo "$z"; return; }; done
  echo "$DEFAULT_AZ"
}
for i in "${INSTANCES[@]}"; do z=$(az_for "$i"); [ "$z" != "$DEFAULT_AZ" ] && log "AZ 대체: $i → $z ($DEFAULT_AZ 오퍼링 없음)"; done

# Job 완료 대기. kubectl 자체가 즉시 실패(프로세스 생성 EAGAIN, API 일시 오류 등)하면 '타임아웃'으로
# 오판하지 않도록 남은 시간 안에서 재시도한다 — 진짜 타임아웃("timed out")만 실패로 본다.
wait_job(){
  local job="$1" out deadline=$((SECONDS + JOB_TIMEOUT))
  while [ $SECONDS -lt $deadline ]; do
    out=$(kubectl wait --for=condition=complete "job/$job" -n "$NAMESPACE" --timeout="$((deadline - SECONDS))s" 2>&1) && return 0
    echo "$out" | grep -q "timed out" && return 1
    log "${YELLOW}job wait 오류 재시도${NC}: $job — $(echo "$out" | tail -1)"
    sleep 10
  done
  return 1
}

# 동시 실행 제한. 이 워크스테이션은 여러 세션이 cgroup(code-server.service) pids.max=8192를 공유하는데
# (스레드 포함), 2026-11 web 본 실행에서 55개 인스턴스를 한꺼번에 띄우자 7980/8192까지 차서 fork가
# EAGAIN으로 실패 → 가짜 '실패/타임아웃'이 났고 다른 세션까지 영향을 받았다. 그래서
#   (1) MAX_PARALLEL개(기본 10)까지만 인스턴스를 동시에 돌리고
#   (2) cgroup pids 사용률이 PIDS_HIGH_PCT(기본 92%) 이상이면 새 인스턴스 투입을 멈춘다.
MAX_PARALLEL="${MAX_PARALLEL:-10}"
PIDS_HIGH_PCT="${PIDS_HIGH_PCT:-92}"
CG_DIR="/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup 2>/dev/null)"
pids_tight(){
  [ -r "$CG_DIR/pids.current" ] && [ -r "$CG_DIR/pids.max" ] || return 1
  local cur max; cur=$(cat "$CG_DIR/pids.current"); max=$(cat "$CG_DIR/pids.max")
  [ "$max" = max ] && return 1
  [ $((cur * 100 / max)) -ge "$PIDS_HIGH_PCT" ]
}
throttle(){
  local warned=false
  while [ "$(jobs -rp | wc -l)" -ge "$MAX_PARALLEL" ] || pids_tight; do
    if pids_tight && [ "$warned" = false ]; then log "${YELLOW}cgroup pids ${PIDS_HIGH_PCT}% 이상 — 투입 대기${NC}"; warned=true; fi
    sleep 5
  done
}

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

  # apply/wait 출력은 실패 시에만 로그에 남긴다. 2026-11 web 스모크에서 동시 기동 직후 1초 만에
  # "서버 기동 실패"가 무작위로 났는데(=apply 실패로 Deployment 부재 → wait 즉시 NotFound) 출력이
  # /dev/null이라 원인을 알 수 없었음 → 일시 오류는 재시도하고, 끝내 실패하면 마지막 에러를 기록.
  local out ok=false
  for t in 1 2 3; do
    if out=$(cat "$SERVER_TEMPLATE" \
        | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s|\${INSTANCE_TYPE}|${instance}|g" | sed "s|\${AZ}|${az}|g" \
        | kubectl apply -f - 2>&1); then ok=true; break; fi
    log "${YELLOW}apply 재시도 ${t}/3${NC}: $instance — $(echo "$out" | tail -1)"
    sleep $((t * 5))
  done
  local deadline=$((SECONDS + SERVER_READY_TIMEOUT))
  while [ "$ok" = true ] && [ $SECONDS -lt $deadline ]; do
    if out=$(kubectl wait --for=condition=available "deployment/${NAME}-remote-${safe}" -n "$NAMESPACE" \
        --timeout="$((deadline - SECONDS))s" 2>&1); then ok=done; break; fi
    echo "$out" | grep -q "timed out" && break   # 진짜 타임아웃은 재시도하지 않음
    log "${YELLOW}wait 오류 재시도${NC}: $instance — $(echo "$out" | tail -1)"
    sleep 5
  done

  if [ "$ok" != done ]; then
    log "${RED}서버 기동 실패${NC}: $instance — $(echo "$out" | tail -1)"
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

    if wait_job "$job"; then
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

  # pvc: 서버 템플릿이 PVC를 쓰는 경우(PostgreSQL 등) 같은 app/instance-type 레이블로 함께 정리 — 없으면 no-op
  kubectl delete deployment,service,configmap,pvc -n "$NAMESPACE" -l "app=${APP_LABEL},instance-type=${instance}" --ignore-not-found >/dev/null 2>&1
  log "[$instance] 완료"
}

log "동시 실행 상한 ${MAX_PARALLEL}, cgroup pids 상한 ${PIDS_HIGH_PCT}%"
for instance in "${INSTANCES[@]}"; do throttle; run_instance "$instance" & done
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
