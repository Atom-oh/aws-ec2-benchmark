#!/bin/bash
# The finite Jobs own load/results/cleanup; this process launches then observes.
set -euo pipefail
cd "$(dirname "$0")/.."
run_id=${1:?Usage: run-springboot-traffic48.sh RUN_ID}
if [[ ! "$run_id" =~ ^[a-z0-9]([a-z0-9-]{0,14}[a-z0-9])?$ ]]; then
  echo 'Invalid run id' >&2
  exit 2
fi
output="results/springboot-traffic48/$run_id"
echo "$BASHPID" > "$output/observer.pid"
trap 'rc=$?; printf "%s exit=%s\n" "$(date -u +%FT%TZ)" "$rc" > "$output/observer-exit.txt"' EXIT
echo "CALIBRATING $(date -u +%FT%TZ)"
python3 -u scripts/springboot_traffic48.py calibrate --run-id "$run_id"
echo "LAUNCHING $(date -u +%FT%TZ)"
python3 -u scripts/springboot_traffic48.py launch --run-id "$run_id"
echo "OBSERVING $(date -u +%FT%TZ)"
python3 -u scripts/springboot_traffic48.py watch --run-id "$run_id"
