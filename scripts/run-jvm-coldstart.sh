#!/bin/bash
# JVM Coldstart Benchmark Runner
# Runs SpringBoot and Elasticsearch coldstart benchmarks with 60% heap

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="${BASE_DIR}/results"
CONFIG_FILE="${BASE_DIR}/config/instances-4vcpu.txt"

# Benchmark type: springboot or elasticsearch
BENCHMARK_TYPE="${1:-all}"
MAX_CONCURRENT="${2:-10}"

# Instance lists by architecture
INTEL_INSTANCES=(
    c5.xlarge c5d.xlarge c5n.xlarge
    c6i.xlarge c6id.xlarge c6in.xlarge
    c7i.xlarge c7i-flex.xlarge
    c8i.xlarge c8i-flex.xlarge
    m5.xlarge m5d.xlarge m5zn.xlarge
    m6i.xlarge m6id.xlarge m6in.xlarge m6idn.xlarge
    m7i.xlarge m7i-flex.xlarge
    m8i.xlarge
    r5.xlarge r5d.xlarge r5n.xlarge r5dn.xlarge r5b.xlarge
    r6i.xlarge r6id.xlarge
    r7i.xlarge
    r8i.xlarge r8i-flex.xlarge
)

AMD_INSTANCES=(
    c5a.xlarge
    m5a.xlarge m5ad.xlarge
    r5a.xlarge r5ad.xlarge
)

GRAVITON_INSTANCES=(
    c6g.xlarge c6gd.xlarge c6gn.xlarge
    c7g.xlarge c7gd.xlarge
    c8g.xlarge
    m6g.xlarge m6gd.xlarge
    m7g.xlarge m7gd.xlarge
    m8g.xlarge
    r6g.xlarge r6gd.xlarge
    r7g.xlarge r7gd.xlarge
    r8g.xlarge
)

log() {
    echo "[$(date '+%H:%M:%S')] $1"
}

run_springboot_coldstart() {
    local instance=$1
    local arch=$2
    local safe_name=$(echo "$instance" | tr '.' '-')

    # Delete old job if exists
    kubectl delete job springboot-coldstart-${safe_name} -n benchmark 2>/dev/null || true

    # Create temp file with correct substitution
    local temp_file=$(mktemp)
    sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
        -e "s/INSTANCE_TYPE/${instance}/g" \
        -e "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g" \
        "${BASE_DIR}/benchmarks/springboot/springboot-coldstart.yaml" > "$temp_file"

    kubectl apply -f "$temp_file" >/dev/null
    rm "$temp_file"

    log "  [STARTED] springboot-coldstart ${instance}"
}

run_elasticsearch_coldstart() {
    local instance=$1
    local arch=$2
    local safe_name=$(echo "$instance" | tr '.' '-')

    # Delete old job if exists
    kubectl delete job es-coldstart-${safe_name} -n benchmark 2>/dev/null || true

    # Create temp file with correct substitution
    local temp_file=$(mktemp)
    sed -e "s/INSTANCE_SAFE/${safe_name}/g" \
        -e "s/INSTANCE_TYPE/${instance}/g" \
        -e "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g" \
        "${BASE_DIR}/benchmarks/elasticsearch/elasticsearch-coldstart.yaml" > "$temp_file"

    kubectl apply -f "$temp_file" >/dev/null
    rm "$temp_file"

    log "  [STARTED] es-coldstart ${instance}"
}

wait_for_jobs() {
    local job_prefix=$1
    local max_wait=600  # 10 minutes
    local start_time=$(date +%s)

    while true; do
        local running
        running=$(kubectl get jobs -n benchmark --no-headers 2>/dev/null | grep "^${job_prefix}" | grep -c "Running" 2>/dev/null || true)
        running=${running:-0}
        running=$(echo "$running" | tr -d '[:space:]')

        if [ -z "$running" ] || [ "$running" -eq 0 ] 2>/dev/null; then
            break
        fi

        local elapsed=$(($(date +%s) - start_time))
        if [ $elapsed -gt $max_wait ]; then
            log "  [TIMEOUT] Some jobs still running after ${max_wait}s"
            break
        fi

        log "  [WAITING] ${running} jobs still running..."
        sleep 30
    done
}

collect_logs() {
    local job_prefix=$1
    local output_dir=$2

    mkdir -p "$output_dir"

    for job in $(kubectl get jobs -n benchmark --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep "^${job_prefix}"); do
        local instance=$(echo "$job" | sed "s/${job_prefix}-//" | tr '-' '.')
        # Fix instance name (e.g., c8i.flex.xlarge -> c8i-flex.xlarge)
        instance=$(echo "$instance" | sed 's/\.flex\./-flex./')

        local log_file="${output_dir}/${instance}.log"
        kubectl logs -n benchmark -l job-name=${job} --all-containers > "$log_file" 2>/dev/null || true

        if [ -s "$log_file" ]; then
            log "  [SAVED] ${instance}"
        fi
    done
}

collect_batch_logs() {
    local job_prefix=$1
    local output_dir=$2

    mkdir -p "$output_dir"

    for job in $(kubectl get jobs -n benchmark --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep "^${job_prefix}"); do
        local instance=$(echo "$job" | sed "s/${job_prefix}-//" | tr '-' '.')
        instance=$(echo "$instance" | sed 's/\.flex\./-flex./')
        local log_file="${output_dir}/${instance}.log"

        # Only collect if not already collected
        if [ ! -s "$log_file" ]; then
            kubectl logs -n benchmark -l job-name=${job} > "$log_file" 2>/dev/null || true
            if [ -s "$log_file" ]; then
                log "  [SAVED] ${instance}"
            fi
        fi
    done
}

run_batch() {
    local benchmark=$1
    local -n instances=$2
    local arch=$3

    local batch_size=$MAX_CONCURRENT
    local total=${#instances[@]}
    local current=0
    local output_dir

    if [ "$benchmark" == "springboot" ]; then
        output_dir="${RESULTS_DIR}/springboot-coldstart-60heap"
    else
        output_dir="${RESULTS_DIR}/elasticsearch-coldstart-60heap"
    fi
    mkdir -p "$output_dir"

    for instance in "${instances[@]}"; do
        current=$((current + 1))

        if [ "$benchmark" == "springboot" ]; then
            run_springboot_coldstart "$instance" "$arch"
        elif [ "$benchmark" == "elasticsearch" ]; then
            run_elasticsearch_coldstart "$instance" "$arch"
        fi

        # Wait when batch is full
        if [ $((current % batch_size)) -eq 0 ]; then
            log "[BATCH] Waiting for batch to complete (${current}/${total})..."
            sleep 10
            if [ "$benchmark" == "springboot" ]; then
                wait_for_jobs "springboot-coldstart"
                collect_batch_logs "springboot-coldstart" "$output_dir"
            else
                wait_for_jobs "es-coldstart"
                collect_batch_logs "es-coldstart" "$output_dir"
            fi
        fi
    done

    # Wait for remaining and collect
    log "[BATCH] Waiting for final batch..."
    sleep 10
    if [ "$benchmark" == "springboot" ]; then
        wait_for_jobs "springboot-coldstart"
        collect_batch_logs "springboot-coldstart" "$output_dir"
    else
        wait_for_jobs "es-coldstart"
        collect_batch_logs "es-coldstart" "$output_dir"
    fi
}

main() {
    log "===== JVM Coldstart Benchmark (60% Heap) ====="
    log "Benchmark: ${BENCHMARK_TYPE}"
    log "Max Concurrent: ${MAX_CONCURRENT}"

    if [ "$BENCHMARK_TYPE" == "springboot" ] || [ "$BENCHMARK_TYPE" == "all" ]; then
        log ""
        log "=== SpringBoot Coldstart ==="

        log "[Intel instances]"
        run_batch "springboot" INTEL_INSTANCES "amd64"

        log "[AMD instances]"
        run_batch "springboot" AMD_INSTANCES "amd64"

        log "[Graviton instances]"
        run_batch "springboot" GRAVITON_INSTANCES "arm64"

        log "[Collecting logs]"
        collect_logs "springboot-coldstart" "${RESULTS_DIR}/springboot-coldstart-60heap"
    fi

    if [ "$BENCHMARK_TYPE" == "elasticsearch" ] || [ "$BENCHMARK_TYPE" == "all" ]; then
        log ""
        log "=== Elasticsearch Coldstart ==="

        log "[Intel instances]"
        run_batch "elasticsearch" INTEL_INSTANCES "amd64"

        log "[AMD instances]"
        run_batch "elasticsearch" AMD_INSTANCES "amd64"

        log "[Graviton instances]"
        run_batch "elasticsearch" GRAVITON_INSTANCES "arm64"

        log "[Collecting logs]"
        collect_logs "es-coldstart" "${RESULTS_DIR}/elasticsearch-coldstart-60heap"
    fi

    log ""
    log "===== Complete ====="
}

main
