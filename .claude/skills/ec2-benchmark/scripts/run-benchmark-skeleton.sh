#!/bin/bash
# Benchmark run-script skeleton — copy to scripts/generate-<name>-benchmark.sh and adapt.
# Encodes the two things that are easy to get wrong:
#   1) FULL-PARALLEL execution (no serial batches) — instances restore independently, and the
#      benchmark-server NodePool CPU limit (~480 = 120 nodes) absorbs all 51 at once.
#   2) FAST-SKIP of unschedulable instances (flex types unavailable in the cluster AZs) so one
#      stuck Pending pod never stalls the whole run waiting out the Job timeout.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
NAME="<name>"                                   # <-- set
RESULTS_DIR="$BASE_DIR/results/$NAME"
BENCHMARK_DIR="$BASE_DIR/benchmarks/$NAME"
TEMPLATE="$BENCHMARK_DIR/$NAME.yaml"
INSTANCE_FILE="$BASE_DIR/config/instances-4vcpu.txt"
NAMESPACE="benchmark"
SETS=5
JOB_TIMEOUT=2400          # max wait for a RUNNING job (cold EBS + heavy work can be slow)
SCHED_WAIT=300            # if not Running within this, treat as unschedulable and skip
VERSION="<image-tag>"     # <-- set if the template has a *_VERSION placeholder

FORCE_RERUN=false; [ "${1:-}" == "--force" ] && FORCE_RERUN=true
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log(){ echo -e "[$(date '+%H:%M:%S')] $*"; }

# arch from column 2 of the instance file (x86_64/arm64). awk, NOT grep -P (portability).
get_arch(){ local a; a=$(awk -v i="$1" '$1==i{print $2}' "$INSTANCE_FILE"); [ "$a" = arm64 ] && echo arm64 || echo amd64; }

mapfile -t INSTANCES < <(grep -vE '^\s*#|^\s*$' "$INSTANCE_FILE" | awk '{print $1}')
log "인스턴스 ${#INSTANCES[@]}개"

# --- prerequisites: snapshot (if used) + config ConfigMap (idempotent) ---
# kubectl apply -f "$BENCHMARK_DIR/$NAME-snapshot.yaml"; wait for readyToUse==true
# kubectl create configmap $NAME-cfg -n $NAMESPACE --from-file=... --dry-run=client -o yaml | kubectl apply -f -

# returns 0 if the job's pod reaches Running/Succeeded within SCHED_WAIT, else 1 (unschedulable)
wait_schedulable(){ local job="$1" t p; for t in $(seq 1 $((SCHED_WAIT/5))); do
  p=$(kubectl get pods -n "$NAMESPACE" -l job-name="$job" --no-headers -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
  [ "$p" = Running ] || [ "$p" = Succeeded ] && return 0; sleep 5; done; return 1; }

run_instance(){
  local instance="$1" safe arch; safe=$(echo "$instance"|tr '.' '-'); arch=$(get_arch "$instance")
  mkdir -p "$RESULTS_DIR/$instance"
  for SET in $(seq 1 "$SETS"); do
    local lf="$RESULTS_DIR/$instance/set${SET}.log"
    [ "$FORCE_RERUN" = false ] && [ -s "$lf" ] && continue        # resumable: skip done
    local job="$NAME-${safe}-run${SET}" pvc="$NAME-data-${safe}-run${SET}"
    cat "$TEMPLATE" \
      | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${instance}/g" \
      | sed "s/RUN_NUMBER/${SET}/g"     | sed "s/<TOOL>_VERSION/${VERSION}/g" \
      | sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g" \
      | kubectl apply -f - >/dev/null 2>&1
    if ! wait_schedulable "$job"; then
      log "${YELLOW}스케줄 불가 — skip${NC}: $instance"
      kubectl delete job "$job" pvc "$pvc" -n "$NAMESPACE" --wait=false >/dev/null 2>&1; return
    fi
    if kubectl wait --for=condition=complete "job/$job" -n "$NAMESPACE" --timeout="${JOB_TIMEOUT}s" >/dev/null 2>&1; then
      local pod; pod=$(kubectl get pods -n "$NAMESPACE" -l job-name="$job" --no-headers -o custom-columns=":metadata.name"|head -1)
      [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" > "$lf" 2>/dev/null; log "${GREEN}수집${NC}: $instance set$SET"
    else
      log "${RED}실패/타임아웃${NC}: $instance set$SET"
      local pod; pod=$(kubectl get pods -n "$NAMESPACE" -l job-name="$job" --no-headers -o custom-columns=":metadata.name"|head -1)
      [ -n "$pod" ] && kubectl logs -n "$NAMESPACE" "$pod" > "$lf" 2>/dev/null
    fi
    kubectl delete job "$job" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
    kubectl delete pvc "$pvc" -n "$NAMESPACE" --wait=false >/dev/null 2>&1
  done
  log "[$instance] 완료"
}

# full-parallel: launch all, single wait (NodePool CPU limit throttles, skip handles flex)
for instance in "${INSTANCES[@]}"; do run_instance "$instance" & done
wait
log "${GREEN}전체 완료${NC}: $(find "$RESULTS_DIR" -name 'set*.log' -size +0 | wc -l) 로그"
# python3 scripts/generate-$NAME-report.py
