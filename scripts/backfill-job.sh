#!/bin/bash
# 단일 인스턴스 백필 — Job형 시스템 벤치마크(sysbench-cpu/sysbench-memory/stress-ng/passmark)와 iperf3.
#   usage: scripts/backfill-job.sh <benchmark> <instance-type> [runs]
#   benchmark: sysbench-cpu | sysbench-memory | stress-ng | passmark | iperf3 | iperf3-udp | nginx | es-coldstart
# 결과: results/<benchmark>/<instance>/run<N>.log (기존 레이아웃과 동일). 완료 판정 문자열이 있는 회차는 건너뜀(멱등).
# iperf3: 서버 Deployment/Service 배포 → ClusterIP를 IPERF_SERVER_IP에 치환(CLAUDE.md의 placeholder 미치환
#   버그 재발 방지) → 클라이언트 Job N회 순차 → 서버 정리.
set -uo pipefail
kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }

BENCH="${1:?usage: backfill-job.sh <benchmark> <instance-type> [runs]}"
INSTANCE="${2:?instance-type required}"
RUNS="${3:-5}"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS=benchmark
SAFE=$(echo "$INSTANCE" | tr '.' '-')
ARCH=$(awk -v i="$INSTANCE" '$1==i{print $2}' "$BASE_DIR/config/instances-4vcpu.txt")
[ "$ARCH" = arm64 ] || ARCH=amd64
case "$BENCH" in
  sysbench-cpu)    TPL=benchmarks/system/sysbench-cpu.yaml;    DONE="events per second"; TO=1200 ;;
  sysbench-memory) TPL=benchmarks/system/sysbench-memory.yaml; DONE="MiB/sec";           TO=1200 ;;
  stress-ng)       TPL=benchmarks/system/stress-ng.yaml;       DONE="branch";            TO=1800 ;;
  passmark)        TPL=benchmarks/system/passmark.yaml;        DONE="SUMM_CPU";          TO=1800 ;;
  iperf3)          TPL=benchmarks/system/iperf3-network.yaml;  DONE="receiver";          TO=900; IPERF=1 ;;
  # iperf3-udp: UDP 전용(Service에 UDP 5201 포함) — 기존 iperf3의 ClusterIP 회차는 UDP가 전부 실패했음
  iperf3-udp)      TPL=benchmarks/system/iperf3-udp.yaml;      DONE="receiver";          TO=600; IPERF=1 ;;
  # nginx: 서버(nginx-server.yaml) + wrk Job(nginx-benchmark.yaml, Service DNS로 접속 — IP 치환 불필요)
  nginx)           TPL=benchmarks/nginx/nginx-benchmark.yaml; SERVER_TPL=benchmarks/nginx/nginx-server.yaml
                   DONE="===== Complete ====="; TO=900 ;;
  # es-coldstart: ARCH가 템플릿 여러 곳에 쓰여 전역 치환(CLAUDE.md 절차와 동일), 로그 이름 coldstart<N>.log
  es-coldstart)    TPL=benchmarks/elasticsearch/elasticsearch-coldstart.yaml; DONE="===== Complete ====="; TO=1200
                   ARCH_GLOBAL=1; PREFIX=coldstart; OUTNAME=elasticsearch ;;
  *) echo "unknown benchmark: $BENCH"; exit 2 ;;
esac
OUT="$BASE_DIR/results/${OUTNAME:-$BENCH}/$INSTANCE"
PREFIX="${PREFIX:-run}"
mkdir -p "$OUT"
log(){ echo "[$(date '+%H:%M:%S')] [$BENCH $INSTANCE] $*"; }

# ARCH_GLOBAL: 단어 단위(\bARCH\b) 치환 — 전역 s/ARCH/는 SEARCH_* 변수·출력 라벨까지 SEarm64_* 로 바꿨음(2026-11-12 발견)
render_file(){ local a; if [ -n "${ARCH_GLOBAL:-}" ]; then a="s/\\bARCH\\b/$ARCH/g"; else a="s|kubernetes.io/arch: ARCH|kubernetes.io/arch: $ARCH|g"; fi
  cat "$BASE_DIR/$1" | sed "s/INSTANCE_SAFE/$SAFE/g" | sed "s/\${INSTANCE_TYPE}/$INSTANCE/g" \
  | sed "s/INSTANCE_TYPE/$INSTANCE/g" | sed "$a"; }
render(){ render_file "$TPL"; }
doc(){ # <kind> : 렌더링된 템플릿에서 해당 kind 문서만
  render | awk -v k="$1" 'BEGIN{RS="\n---\n"; ORS="\n---\n"} $0 ~ "\nkind: "k"\n" || $0 ~ "^kind: "k"\n" {print}'; }
find_pod(){ local p t; for t in 1 2 3 4 5; do
  p=$(kubectl get pods -n $NS -l "job-name=$1" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
  [ -n "$p" ] && { echo "$p"; return 0; }; sleep 3; done; return 1; }

JOB=$(render | awk '/^kind: Job/{j=1} j && /^  name:/{print $2; exit}')
SERVER_IP=""
if [ -n "${IPERF:-}" ]; then
  { doc Service; doc Deployment; } | kubectl apply -f - >/dev/null || { log "서버 apply 실패"; exit 1; }
  kubectl wait --for=condition=available "deployment/iperf3-server-$SAFE" -n $NS --timeout=600s >/dev/null 2>&1 || { log "서버 기동 실패"; exit 1; }
  SERVER_IP=$(kubectl get svc -n $NS "iperf3-server-$SAFE" -o jsonpath='{.spec.clusterIP}')
  [ -n "$SERVER_IP" ] || { log "ClusterIP 조회 실패"; exit 1; }
  log "서버 준비: $SERVER_IP"
elif [ -n "${SERVER_TPL:-}" ]; then
  render_file "$SERVER_TPL" | kubectl apply -f - >/dev/null || { log "서버 apply 실패"; exit 1; }
  kubectl wait --for=condition=available "deployment/$BENCH-server-$SAFE" -n $NS --timeout=600s >/dev/null 2>&1 || { log "서버 기동 실패"; exit 1; }
  log "서버 준비"
fi

for r in $(seq 1 "$RUNS"); do
  lf="$OUT/$PREFIX$r.log"
  grep -q "$DONE" "$lf" 2>/dev/null && { log "run$r 스킵(완료)"; continue; }
  kubectl delete job "$JOB" -n $NS --ignore-not-found >/dev/null 2>&1
  if [ -n "${IPERF:-}" ]; then y=$(doc Job | sed "s/IPERF_SERVER_IP/$SERVER_IP/g"); else y=$(render); fi
  echo "$y" | kubectl apply -f - >/dev/null || { log "run$r apply 실패"; continue; }
  if kubectl wait --for=condition=complete "job/$JOB" -n $NS --timeout="${TO}s" >/dev/null 2>&1; then
    pod=$(find_pod "$JOB") && kubectl logs -n $NS "$pod" > "$lf" 2>/dev/null
  fi
  grep -q "$DONE" "$lf" 2>/dev/null && log "run$r 수집" || log "run$r 실패/불완전"
  kubectl delete job "$JOB" -n $NS --wait=false >/dev/null 2>&1
done
[ -n "${IPERF:-}" ] && kubectl delete deployment,service -n $NS "iperf3-server-$SAFE" --ignore-not-found >/dev/null 2>&1
[ -n "${SERVER_TPL:-}" ] && kubectl delete deployment,service -n $NS "$BENCH-server-$SAFE" --ignore-not-found >/dev/null 2>&1
log "완료: $(grep -l "$DONE" "$OUT"/$PREFIX*.log 2>/dev/null | wc -l)/$RUNS"
