#!/bin/bash
# SpringBoot 단일 인스턴스 백필 (wrk 5회 + coldstart 5회) — 신규 인스턴스(c9g 등)나 재측정용.
#   usage: scripts/backfill-springboot.sh <instance-type> [runs]
#   env: RESULTS_SUBDIR(기본 springboot — 재측정은 다른 디렉터리로 분리), SKIP_COLDSTART=1(wrk만)
#   wrk 로그 끝에 RUN_START/RUN_END(epoch)를 덧붙여 node-sampler 로그와 시간 정렬할 수 있게 한다.
#   WRK_THREADS_SEQ="2 6 2 6 2 6": 회차별 wrk 스레드 수(클라이언트 한계 검증용 — 같은 서버 호스트에서 번갈아 측정).
#     스레드 > 2인 회차는 클라이언트 CPU 요청을 스레드 수만큼 올려 노드를 사실상 독점시킨다.
# - wrk: springboot-server.yaml(C2 전용 JAVA_OPTS — 본 데이터셋과 동일) + springboot-benchmark.yaml, 회차 순차.
# - coldstart: 비교 대상 51개(2026-01-20 수집)가 JVM 기본값(Tiered 켜짐)이므로 같은 조건으로 맞추려고
#   템플릿의 C2 전용 플래그를 제거해 실행하고, results/springboot/<inst>/COLDSTART_PROFILE에 "default"를 기록
#   (parsers/springboot.py가 이 마커를 날짜 규칙보다 우선 적용).
# - 이미 수집된 회차는 건너뛴다(멱등). 부하 중 클럭은 node-sampler DaemonSet + collect-node-sampler.sh가 별도 기록.
set -uo pipefail
kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }

INSTANCE="${1:?usage: backfill-springboot.sh <instance-type> [runs]}"
RUNS="${2:-5}"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TPL="$BASE_DIR/benchmarks/springboot"
OUT="$BASE_DIR/results/${RESULTS_SUBDIR:-springboot}/$INSTANCE"
NS=benchmark
SAFE=$(echo "$INSTANCE" | tr '.' '-')
ARCH=$(awk -v i="$INSTANCE" '$1==i{print $2}' "$BASE_DIR/config/instances-4vcpu.txt")
[ "$ARCH" = arm64 ] || ARCH=amd64
mkdir -p "$OUT"
log(){ echo "[$(date '+%H:%M:%S')] [springboot $INSTANCE] $*"; }

find_pod(){ local p t; for t in 1 2 3 4 5; do
  p=$(kubectl get pods -n $NS -l "job-name=$1" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
  [ -n "$p" ] && { echo "$p"; return 0; }; sleep 3; done; return 1; }

run_job(){ # <job-name> <rendered-yaml> <log-file> <timeout-s>
  local job="$1" yaml="$2" lf="$3" to="$4" pod
  kubectl delete job "$job" -n $NS --ignore-not-found >/dev/null 2>&1
  echo "$yaml" | kubectl apply -f - >/dev/null || { log "apply 실패: $job"; return 1; }
  if kubectl wait --for=condition=complete "job/$job" -n $NS --timeout="${to}s" >/dev/null 2>&1; then
    pod=$(find_pod "$job") && kubectl logs -n $NS "$pod" > "$lf" 2>/dev/null
  fi
  kubectl delete job "$job" -n $NS --wait=false >/dev/null 2>&1
  [ -s "$lf" ]
}

# ---- wrk ----
need=false; for r in $(seq 1 "$RUNS"); do grep -q "Benchmark Complete" "$OUT/wrk$r.log" 2>/dev/null || need=true; done
if $need; then
  cat "$TPL/springboot-server.yaml" | sed "s/INSTANCE_SAFE/$SAFE/g" | sed "s/\${INSTANCE_TYPE}/$INSTANCE/g" | sed "s/INSTANCE_TYPE/$INSTANCE/g" \
    | sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: $ARCH|g" | kubectl apply -f - >/dev/null
  if kubectl wait --for=condition=available "deployment/springboot-server-$SAFE" -n $NS --timeout=600s >/dev/null 2>&1; then
    for r in $(seq 1 "$RUNS"); do
      lf="$OUT/wrk$r.log"; grep -q "Benchmark Complete" "$lf" 2>/dev/null && continue
      y=$(cat "$TPL/springboot-benchmark.yaml" | sed "s/INSTANCE_SAFE/$SAFE/g" | sed "s/\${INSTANCE_TYPE}/$INSTANCE/g" \
        | sed "s/INSTANCE_TYPE/$INSTANCE/g" | sed "s/RUN_NUMBER/$r/g" | sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: $ARCH|g")
      th=""; [ -n "${WRK_THREADS_SEQ:-}" ] && th=$(echo $WRK_THREADS_SEQ | awk -v i=$r '{print $i}')
      if [ -n "$th" ] && [ "$th" != 2 ]; then
        y=$(echo "$y" | sed "s/wrk -t2 /wrk -t$th /g" | sed "s/2 threads,/$th threads,/g" | sed "s/cpu: \"1500m\"/cpu: \"$th\"/")
      fi
      t0=$(date +%s)
      if run_job "springboot-benchmark-$SAFE" "$y" "$lf" 900; then
        node=$(kubectl get pods -n $NS -l "app=springboot-server,instance-type=$INSTANCE" -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null)
        printf 'RUN_START: %s\nRUN_END: %s\nSERVER_NODE: %s\nWRK_THREADS: %s\n' "$t0" "$(date +%s)" "$node" "${th:-2}" >> "$lf"; log "wrk$r 수집 (t${th:-2}, $node)"
      else log "wrk$r 실패"; fi
    done
  else
    log "서버 기동 실패"
  fi
  kubectl delete deployment,service -n $NS "springboot-server-$SAFE" --ignore-not-found >/dev/null 2>&1
fi

# ---- coldstart (JVM 기본값) ----
[ -n "${SKIP_COLDSTART:-}" ] && { log "완료(wrk만): $(grep -l 'Benchmark Complete' "$OUT"/wrk*.log 2>/dev/null | wc -l)/$RUNS"; exit 0; }
echo "default" > "$OUT/COLDSTART_PROFILE"
for r in $(seq 1 "$RUNS"); do
  lf="$OUT/coldstart$r.log"; grep -q "Started PetClinicApplication" "$lf" 2>/dev/null && continue
  y=$(cat "$TPL/springboot-coldstart.yaml" | sed "s/INSTANCE_SAFE/$SAFE/g" | sed "s/\${INSTANCE_TYPE}/$INSTANCE/g" \
    | sed "s/INSTANCE_TYPE/$INSTANCE/g" | sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: $ARCH|g" \
    | sed "s/ -XX:-TieredCompilation -XX:ReservedCodeCacheSize=64M -XX:InitialCodeCacheSize=64M//")
  run_job "springboot-coldstart-$SAFE" "$y" "$lf" 900 && log "coldstart$r 수집" || log "coldstart$r 실패"
done
log "완료: wrk $(grep -l 'Benchmark Complete' "$OUT"/wrk*.log 2>/dev/null | wc -l)/$RUNS, coldstart $(grep -l 'Started PetClinicApplication' "$OUT"/coldstart*.log 2>/dev/null | wc -l)/$RUNS"
