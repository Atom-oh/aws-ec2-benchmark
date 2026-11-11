#!/bin/bash
# Elasticsearch Rally 백필 — 지정 인스턴스만, 기존 템플릿 그대로(benchmarks/elasticsearch/elasticsearch-{server,rally}.yaml).
# generate-elasticsearch-benchmark.sh와 같은 순서(인스턴스별 ES 서버 1개 → Rally 5회 순차 → 정리)이지만:
#   - kube context 고정(공유 kubeconfig에서 다른 세션이 current-context를 바꾸는 일 방지)
#   - arch는 config/instances-4vcpu.txt 컬럼2(awk) — 정규식 판별 금지(c8gn/r8gd 오판 이력)
#   - 로그 수집 재시도 + 빈 파일 검사(거짓 '수집 완료' 방지), 완료 로그는 건너뜀(멱등)
#   - 인스턴스 수가 적은 백필 전용(동시 실행 = 인스턴스 수)
# 사용: scripts/backfill-es-rally.sh c9g.xlarge c8gn.xlarge r8gd.xlarge m8i-flex.xlarge
set -u
kubectl() { command kubectl --context mall-apne2-mgmt "$@"; }

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH="$BASE_DIR/benchmarks/elasticsearch"
RESULTS="$BASE_DIR/results/elasticsearch"
NS=benchmark
RUNS="${RUNS:-5}"
log() { echo "[$(date '+%H:%M:%S')] $*"; }

arch_of() {
  local a; a=$(awk -v i="$1" '$1==i {print $2}' "$BASE_DIR/config/instances-4vcpu.txt")
  case "$a" in arm64) echo arm64 ;; x86_64|amd64) echo amd64 ;; *) echo "" ;; esac
}

find_pod() { # job → pod (최대 5회 재시도)
  local p i
  for i in 1 2 3 4 5; do
    p=$(kubectl get pods -n "$NS" -l "job-name=$1" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    [ -n "$p" ] && { echo "$p"; return 0; }
    sleep 3
  done
  return 1
}

run_instance() {
  local inst=$1 safe arch
  safe=$(echo "$inst" | tr '.' '-')
  arch=$(arch_of "$inst")
  [ -z "$arch" ] && { log "[$inst] config에 없음 — 건너뜀"; return 1; }
  mkdir -p "$RESULTS/$inst"
  local need=0 r
  for r in $(seq 1 "$RUNS"); do grep -q "Rally Benchmark Complete" "$RESULTS/$inst/rally$r.log" 2>/dev/null || need=1; done
  [ "$need" = 0 ] && { log "[$inst] rally $RUNS회 이미 완료"; return 0; }

  log "[$inst] ES 서버 배포 (arch=$arch)"
  # 여러 인스턴스가 공용 ConfigMap(es-config)을 동시에 apply하면 충돌로 실패할 수 있어 재시도(2026-11-11 실제 발생)
  local ok=0 t
  for t in 1 2 3 4 5; do
    if sed -e "s/INSTANCE_SAFE/${safe}/g" -e "s/INSTANCE_TYPE/${inst}/g" -e "s/ARCH/${arch}/g" "$BENCH/elasticsearch-server.yaml" \
        | kubectl apply -f - >/dev/null 2>&1; then ok=1; break; fi
    sleep $((t * 3))
  done
  [ "$ok" = 1 ] || { log "[$inst] 서버 apply 실패(5회 재시도)"; return 1; }
  if ! kubectl rollout status deployment/es-server-"$safe" -n "$NS" --timeout=900s >/dev/null 2>&1; then
    log "[$inst] 서버 준비 타임아웃"; kubectl get pods -n "$NS" -l "instance-type=$inst" -o wide 2>&1 | tail -3; return 1
  fi
  for r in $(seq 1 "$RUNS"); do
    local lf="$RESULTS/$inst/rally$r.log" job="es-rally-${safe}-run${r}"
    grep -q "Rally Benchmark Complete" "$lf" 2>/dev/null && { log "[$inst] rally$r 이미 완료"; continue; }
    kubectl delete job "$job" -n "$NS" --ignore-not-found >/dev/null 2>&1
    sed -e "s/INSTANCE_SAFE/${safe}/g" -e "s/INSTANCE_TYPE/${inst}/g" -e "s/RUN_NUMBER/${r}/g" -e "s/ARCH/${arch}/g" "$BENCH/elasticsearch-rally.yaml" \
      | kubectl apply -f - >/dev/null || { log "[$inst] rally$r apply 실패"; continue; }
    local waited=0 st fl
    while [ "$waited" -lt 2400 ]; do
      st=$(kubectl get job "$job" -n "$NS" -o jsonpath='{.status.succeeded}' 2>/dev/null)
      fl=$(kubectl get job "$job" -n "$NS" -o jsonpath='{.status.failed}' 2>/dev/null)
      [ "$st" = "1" ] && break
      [ -n "$fl" ] && [ "$fl" != "0" ] && break
      sleep 15; waited=$((waited + 15))
    done
    local pod; pod=$(find_pod "$job")
    if [ -n "$pod" ]; then kubectl logs -n "$NS" "$pod" > "$lf" 2>/dev/null; fi
    if [ -s "$lf" ] && grep -q "Rally Benchmark Complete" "$lf"; then log "[$inst] rally$r 수집 완료"
    else log "[$inst] rally$r 실패 (succeeded=$st failed=$fl, ${waited}s)"; fi
    kubectl delete job "$job" -n "$NS" --ignore-not-found >/dev/null 2>&1
  done
  log "[$inst] 서버 정리"
  kubectl delete deployment,service -n "$NS" -l "app=es-server,instance-type=$inst" --ignore-not-found >/dev/null 2>&1
}

[ $# -eq 0 ] && { echo "usage: $0 <instance>..."; exit 1; }
for i in "$@"; do run_instance "$i" & done
wait
log "전체 완료: $(for i in "$@"; do echo -n "$i=$(grep -l 'Rally Benchmark Complete' "$RESULTS/$i"/rally*.log 2>/dev/null | wc -l)/$RUNS "; done)"
