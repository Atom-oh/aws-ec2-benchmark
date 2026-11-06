#!/bin/sh
# One uninterrupted wrk process keeps load on the server while minute probes run.
set -eu
RESULTS_DIR=${RESULTS_DIR:-/results}
DURATION_SECONDS=${DURATION_SECONDS:-172800}
WARMUP_SECONDS=${WARMUP_SECONDS:-300}
SAMPLE_SECONDS=${SAMPLE_SECONDS:-60}
CLEANUP=${CLEANUP:-1}
mkdir -p "$RESULTS_DIR"
MAIN_PID=
OUTCOME=FAILED

finish() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$MAIN_PID" ]; then
        kill "$MAIN_PID" 2>/dev/null || true
        wait "$MAIN_PID" 2>/dev/null || true
    fi
    printf '%s %s exit=%s\n' "$OUTCOME" "$(date -u +%FT%TZ)" "$rc" > "$RESULTS_DIR/status.txt"
    if [ "$CLEANUP" = 1 ]; then
        sa=/var/run/secrets/kubernetes.io/serviceaccount
        api="https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT_HTTPS}"
        for resource in "jobs/$SERVER_JOB" "services/$SERVER_SERVICE"; do
            case "$resource" in jobs/*) group=apis/batch/v1;; *) group=api/v1;; esac
            if ! curl --fail --silent --show-error --max-time 30 --retry 3 \
                --cacert "$sa/ca.crt" -H "Authorization: Bearer $(cat "$sa/token")" \
                -X DELETE "$api/$group/namespaces/benchmark/$resource" \
                >> "$RESULTS_DIR/cleanup.log" 2>&1; then
                echo "CLEANUP_FAILED $resource" >> "$RESULTS_DIR/cleanup.log"
            fi
        done
    fi
    echo "$OUTCOME exit=$rc"
    exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'WARMUP %s\n' "$(date -u +%FT%TZ)" > "$RESULTS_DIR/status.txt"
wrk -t4 -c200 -d"${WARMUP_SECONDS}s" --latency "$TARGET/" > "$RESULTS_DIR/warmup.log" 2>&1

START=$(date +%s)
END=$((START + DURATION_SECONDS))
printf 'RUNNING start_epoch=%s end_epoch=%s\n' "$START" "$END" > "$RESULTS_DIR/status.txt"
printf 'instance=%s\nrun_id=%s\nstart_epoch=%s\nend_epoch=%s\ncontinuous=t4,c200\nprobe=t2,c100\nwarmup_seconds=%s\n' \
    "$INSTANCE_TYPE" "$RUN_ID" "$START" "$END" "$WARMUP_SECONDS" > "$RESULTS_DIR/run.txt"
echo "START instance=$INSTANCE_TYPE epoch=$START end=$END duration=$DURATION_SECONDS"
echo 'timestamp,elapsed_sec,probe_rps,avg_latency_ms,p99_latency_ms,socket_errors,http_errors' > "$RESULTS_DIR/samples.csv"
(
    # Record exit immediately, including if wrk stops during the last probe.
    wrk -t4 -c200 -d"${DURATION_SECONDS}s" --latency "$TARGET/" > "$RESULTS_DIR/continuous.log" 2>&1 &
    worker=$!
    trap 'kill "$worker" 2>/dev/null || true; wait "$worker" 2>/dev/null || true; exit 143' INT TERM
    set +e
    wait "$worker"
    result=$?
    date +%s > "$RESULTS_DIR/continuous-end-epoch.txt"
    exit "$result"
) &
MAIN_PID=$!

while :; do
    now=$(date +%s)
    remaining=$((END - now))
    [ "$remaining" -gt 0 ] || break
    if ! kill -0 "$MAIN_PID" 2>/dev/null; then
        echo 'FAILED: continuous load exited early' >&2
        exit 1
    fi
    interval=$SAMPLE_SECONDS
    [ "$remaining" -ge "$interval" ] || interval=$remaining
    stamp=$(date -u +%FT%TZ)
    # Store raw metrics and errors; never silently manufacture zero CPU samples.
    for metric in system.cpu.usage process.cpu.usage jvm.memory.used jvm.gc.pause process.uptime; do
        if body=$(curl --fail --silent --show-error --max-time 5 "$TARGET/actuator/metrics/$metric" 2>> "$RESULTS_DIR/metrics-errors.log"); then
            printf '{"timestamp":"%s","metric":"%s","data":%s}\n' "$stamp" "$metric" "$body" >> "$RESULTS_DIR/metrics.ndjson"
        else
            printf '{"timestamp":"%s","metric":"%s","error":"fetch_failed"}\n' "$stamp" "$metric" >> "$RESULTS_DIR/metrics.ndjson"
        fi
    done
    remaining=$((END - $(date +%s)))
    [ "$remaining" -gt 0 ] || break
    [ "$remaining" -ge "$interval" ] || interval=$remaining
    wrk -t2 -c100 -d"${interval}s" --latency "$TARGET/" > "$RESULTS_DIR/probe.tmp" 2>&1
    elapsed=$(($(date +%s) - START))
    printf '\n--- %s elapsed=%s duration=%s ---\n' "$stamp" "$elapsed" "$interval" >> "$RESULTS_DIR/probes.log"
    cat "$RESULTS_DIR/probe.tmp" >> "$RESULTS_DIR/probes.log"
    values=$(awk '
        function ms(v) {
            if (v ~ /us$/) return (v+0)/1000;
            if (v ~ /ms$/) return v+0;
            if (v ~ /s$/) return (v+0)*1000;
            return v+0;
        }
        $1=="Requests/sec:" {rps=$2}
        $1=="Latency" && $2 ~ /^[0-9]/ {avg=ms($2); seen_avg=1}
        $1=="99%" {p99=ms($2); seen_p99=1}
        /Socket errors:/ {socket=$4+$6+$8+$10}
        /Non-2xx or 3xx responses:/ {http=$5}
        END {
            if (!(rps>0) || !seen_avg || !seen_p99) exit 1;
            printf "%s,%.3f,%.3f,%d,%d",rps,avg,p99,socket,http;
        }' "$RESULTS_DIR/probe.tmp") || { echo 'FAILED: missing probe throughput or latency' >&2; exit 1; }
    printf '%s,%s,%s\n' "$stamp" "$elapsed" "$values" | tee -a "$RESULTS_DIR/samples.csv"
done
wait "$MAIN_PID"
MAIN_PID=
ACTUAL_END=$(cat "$RESULTS_DIR/continuous-end-epoch.txt")
printf 'actual_continuous_end_epoch=%s\n' "$ACTUAL_END" >> "$RESULTS_DIR/run.txt"
[ "$ACTUAL_END" -ge "$END" ] || { echo 'FAILED: continuous load ended before 48-hour target' >&2; exit 1; }
awk '$1=="Requests/sec:" && $2>0 {ok=1} END {exit !ok}' "$RESULTS_DIR/continuous.log" || {
    echo 'FAILED: continuous load returned no throughput' >&2
    exit 1
}
OUTCOME=COMPLETE
