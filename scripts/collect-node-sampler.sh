#!/bin/bash
# node-sampler DaemonSet 로그 수집기 — INTERVAL초마다 각 샘플러 Pod의 최근 로그를 노드별 파일에 덧붙인다.
#   results/node-sampler/<instance-type>/<node-name>.log
#   파일 첫 줄(최초 1회): # node=<name> instance_type=<type> zone=<az> instance_id=<i-...> 헤더
# 노드는 벤치마크가 끝나면 Karpenter가 ~60초 안에 회수하므로, 짧은 간격(기본 30초)으로 --since 겹치게 읽는다.
# 겹친 줄은 파서(scripts/dashboard/parsers/node_sampler.py)가 ts로 중복 제거한다.
# 종료: Ctrl-C 또는 kill. 프로세스는 kubectl 하나씩 순차 실행(공유 cgroup pids 한도 고려).
set -uo pipefail
kubectl(){ command kubectl --context mall-apne2-mgmt "$@"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(dirname "$SCRIPT_DIR")/results/node-sampler"
INTERVAL="${INTERVAL:-30}"
mkdir -p "$OUT"
declare -A HEADER_DONE=()

while true; do
  while read -r pod node; do
    [ -n "$pod" ] && [ -n "$node" ] || continue
    if [ -z "${HEADER_DONE[$node]:-}" ]; then
      meta=$(kubectl get node "$node" -o jsonpath='{.metadata.labels.node\.kubernetes\.io/instance-type} {.metadata.labels.topology\.kubernetes\.io/zone} {.spec.providerID}' 2>/dev/null) || continue
      read -r itype zone pid <<< "$meta"
      [ -n "$itype" ] || continue
      mkdir -p "$OUT/$itype"
      f="$OUT/$itype/$node.log"
      [ -s "$f" ] || echo "# node=$node instance_type=$itype zone=$zone instance_id=${pid##*/}" > "$f"
      HEADER_DONE[$node]="$f"
    fi
    kubectl logs -n benchmark "$pod" --since="$((INTERVAL + 15))s" 2>/dev/null >> "${HEADER_DONE[$node]}"
  done < <(kubectl get pods -n benchmark -l app=node-sampler -o jsonpath='{range .items[*]}{.metadata.name} {.spec.nodeName}{"\n"}{end}' 2>/dev/null)
  sleep "$INTERVAL"
done
