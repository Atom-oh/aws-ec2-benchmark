#!/bin/bash
# Geekbench 6 백필 — 무료판은 점수를 로컬에 남기지 않고 Geekbench Browser(공개)에 업로드만 한다.
# 이 스크립트는 측정·로그 수집까지만 하고(results/geekbench/<inst>/run<N>.log), 점수는 로그의 결과 URL을 브라우저로
# 열어 results/geekbench/<inst>/scores.json에 기록한다(Geekbench Browser는 Cloudflare 봇 차단이라 자동 수집 불가).
# 사용: scripts/backfill-geekbench.sh <runs> <instance>...
set -uo pipefail
kubectl() { command kubectl --context mall-apne2-mgmt "$@"; }
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS=benchmark
RUNS="${1:?runs}"; shift
log() { echo "[$(date '+%H:%M:%S')] $*"; }

one() {
  local inst=$1 r=$2 safe arch job lf
  safe=$(echo "$inst" | tr '.' '-')
  arch=$(awk -v i="$inst" '$1==i {print $2}' "$BASE_DIR/config/instances-4vcpu.txt"); [ "$arch" = arm64 ] || arch=amd64
  job="geekbench-${safe}"
  lf="$BASE_DIR/results/geekbench/$inst/run$r.log"
  mkdir -p "$(dirname "$lf")"
  grep -q "browser.geekbench.com/v6/cpu/[0-9]" "$lf" 2>/dev/null && { log "[$inst] run$r 이미 완료"; return 0; }
  kubectl delete job "$job" -n "$NS" --ignore-not-found >/dev/null 2>&1
  sed -e "s/INSTANCE_SAFE/${safe}/g" -e "s/INSTANCE_TYPE/${inst}/g" -e "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g" \
    "$BASE_DIR/benchmarks/system/geekbench.yaml" | kubectl apply -f - >/dev/null || { log "[$inst] apply 실패"; return 1; }
  local w=0 st fl p t
  while [ $w -lt 1800 ]; do
    st=$(kubectl get job "$job" -n "$NS" -o jsonpath='{.status.succeeded}' 2>/dev/null)
    fl=$(kubectl get job "$job" -n "$NS" -o jsonpath='{.status.failed}' 2>/dev/null)
    [ "$st" = 1 ] && break; [ -n "$fl" ] && [ "$fl" != 0 ] && break
    sleep 15; w=$((w + 15))
  done
  for t in 1 2 3 4 5; do p=$(kubectl get pods -n "$NS" -l "job-name=$job" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1); [ -n "$p" ] && break; sleep 3; done
  [ -n "${p:-}" ] && kubectl logs -n "$NS" "$p" > "$lf" 2>/dev/null
  if grep -q "browser.geekbench.com/v6/cpu/[0-9]" "$lf" 2>/dev/null; then log "[$inst] run$r $(grep -oE 'https://browser.geekbench.com/v6/cpu/[0-9]+' "$lf" | head -1)"
  else log "[$inst] run$r 실패 (succeeded=$st failed=$fl ${w}s)"; fi
  kubectl delete job "$job" -n "$NS" --ignore-not-found >/dev/null 2>&1
}
for inst in "$@"; do ( for r in $(seq 1 "$RUNS"); do one "$inst" "$r"; done ) & done
wait
log "전체 완료"
