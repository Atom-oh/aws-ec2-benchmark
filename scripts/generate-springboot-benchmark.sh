#!/bin/bash
# Spring Boot Benchmark Suite
# 1. Coldstart: 51 instances × 5 runs = 255 jobs (fully parallel)
# 2. wrk: 51 instances parallel, 5 sequential runs per instance
#
# Usage:
#   ./generate-springboot-benchmark.sh coldstart   # Run coldstart only
#   ./generate-springboot-benchmark.sh wrk         # Run wrk only
#   ./generate-springboot-benchmark.sh all         # Run both
#   ./generate-springboot-benchmark.sh collect     # Collect logs only

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="/home/ec2-user/benchmark"
RESULTS_DIR="$BASE_DIR/results/springboot"
COLDSTART_TEMPLATE="$BASE_DIR/benchmarks/springboot/springboot-coldstart.yaml"
SERVER_TEMPLATE="$BASE_DIR/benchmarks/springboot/springboot-server.yaml"
WRK_TEMPLATE="$BASE_DIR/benchmarks/springboot/springboot-benchmark.yaml"

# Instance lists
INTEL_INSTANCES=(
  c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge
  c6i.xlarge c6id.xlarge c6in.xlarge
  c7i.xlarge c7i-flex.xlarge
  c8i.xlarge c8i-flex.xlarge
  m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge
  m6i.xlarge m6id.xlarge m6idn.xlarge m6in.xlarge
  m7i.xlarge m7i-flex.xlarge
  m8i.xlarge
  r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge
  r6i.xlarge r6id.xlarge
  r7i.xlarge
  r8i.xlarge r8i-flex.xlarge
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

ALL_INSTANCES=("${INTEL_INSTANCES[@]}" "${GRAVITON_INSTANCES[@]}")

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

get_arch() {
  local instance=$1
  if [[ "$instance" =~ g\. ]] || [[ "$instance" =~ gd\. ]] || [[ "$instance" =~ gn\. ]]; then
    echo "arm64"
  else
    echo "amd64"
  fi
}

# ============================================================
# COLDSTART BENCHMARK (255 jobs parallel)
# ============================================================
run_coldstart() {
  log "===== Spring Boot Coldstart Benchmark ====="
  log "Deploying ${#ALL_INSTANCES[@]} instances × 5 runs = $((${#ALL_INSTANCES[@]} * 5)) jobs"

  # Create result directories
  for instance in "${ALL_INSTANCES[@]}"; do
    mkdir -p "$RESULTS_DIR/$instance"
  done

  # Deploy all 255 jobs
  log "Phase 1: Deploying all coldstart jobs..."
  local deployed=0

  for run in 1 2 3 4 5; do
    for instance in "${INTEL_INSTANCES[@]}"; do
      local safe_name=$(echo "$instance" | tr '.' '-')
      local job_name="springboot-coldstart-${safe_name}-run${run}"

      # Check if job already exists
      if kubectl get job -n benchmark "$job_name" &>/dev/null; then
        log "  [SKIP] $job_name already exists"
        continue
      fi

      cat "$COLDSTART_TEMPLATE" | \
        sed "s/springboot-coldstart-INSTANCE_SAFE/${job_name}/g" | \
        sed "s/INSTANCE_SAFE/${safe_name}/g" | \
        sed "s/INSTANCE_TYPE/${instance}/g" | \
        sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: amd64|g" | \
        kubectl apply -f - 2>/dev/null

      ((deployed++))
    done

    for instance in "${GRAVITON_INSTANCES[@]}"; do
      local safe_name=$(echo "$instance" | tr '.' '-')
      local job_name="springboot-coldstart-${safe_name}-run${run}"

      if kubectl get job -n benchmark "$job_name" &>/dev/null; then
        log "  [SKIP] $job_name already exists"
        continue
      fi

      cat "$COLDSTART_TEMPLATE" | \
        sed "s/springboot-coldstart-INSTANCE_SAFE/${job_name}/g" | \
        sed "s/INSTANCE_SAFE/${safe_name}/g" | \
        sed "s/INSTANCE_TYPE/${instance}/g" | \
        sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: arm64|g" | \
        kubectl apply -f - 2>/dev/null

      ((deployed++))
    done

    log "  Deployed run $run: $deployed jobs total"
  done

  log "Phase 2: Real-time log collection (wait + collect)..."
  wait_and_collect_coldstart

  log "Phase 3: Cleanup coldstart jobs..."
  kubectl delete jobs -n benchmark -l benchmark=springboot-coldstart --ignore-not-found=true

  log "===== Coldstart Benchmark Complete ====="
}

wait_and_collect_coldstart() {
  # 배포와 동시에 실시간으로 로그 수집
  # TTL(30분) 내에 완료된 Job의 로그를 즉시 수집
  local total=$((${#ALL_INSTANCES[@]} * 5))
  local max_wait=1800  # 30 minutes
  local wait_time=0
  local collected=0

  log "Starting real-time log collection (total: $total jobs)..."

  while [ $wait_time -lt $max_wait ]; do
    collected=0

    # 모든 Job을 순회하며 완료된 것의 로그 수집
    for run in 1 2 3 4 5; do
      for instance in "${ALL_INSTANCES[@]}"; do
        local safe_name=$(echo "$instance" | tr '.' '-')
        local job_name="springboot-coldstart-${safe_name}-run${run}"
        local log_file="$RESULTS_DIR/$instance/coldstart${run}.log"

        # 이미 수집된 경우 스킵
        if [ -s "$log_file" ]; then
          ((collected++))
          continue
        fi

        # Job 상태 확인 (완료되었는지)
        local succeeded=$(kubectl get job -n benchmark "$job_name" \
          -o jsonpath='{.status.succeeded}' 2>/dev/null || echo "0")

        if [ "$succeeded" = "1" ]; then
          # Pod에서 로그 수집
          local pod=$(kubectl get pods -n benchmark -l job-name="$job_name" \
            --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

          if [ -n "$pod" ]; then
            kubectl logs -n benchmark "$pod" > "$log_file" 2>/dev/null
            if [ -s "$log_file" ]; then
              log "  [COLLECTED] $instance run$run"
              ((collected++))
              # 로그 수집 성공 시 Job 즉시 삭제 (비용 절감)
              kubectl delete job "$job_name" -n benchmark --ignore-not-found=true 2>/dev/null &
            else
              # 빈 파일 삭제 (재시도 가능하게)
              rm -f "$log_file"
            fi
          fi
        fi
      done
    done

    log "  Progress: $collected/$total logs collected (${wait_time}s elapsed)"

    # 모든 로그 수집 완료
    if [ "$collected" -ge "$total" ]; then
      log "All logs collected!"
      break
    fi

    sleep 20
    ((wait_time+=20))
  done

  # 최종 통계
  local final_count=$(find "$RESULTS_DIR" -name "coldstart*.log" -size +0 2>/dev/null | wc -l)
  log "Final: $final_count/$total logs collected"
}

# ============================================================
# WRK BENCHMARK (51 parallel, 5 sequential per instance)
# ============================================================
run_wrk() {
  log "===== Spring Boot wrk Benchmark ====="
  log "Deploying ${#ALL_INSTANCES[@]} servers, 5 sequential runs per instance"

  # Create result directories
  for instance in "${ALL_INSTANCES[@]}"; do
    mkdir -p "$RESULTS_DIR/$instance"
  done

  # Phase 1: Deploy all servers
  log "Phase 1: Deploying SpringBoot servers..."
  deploy_all_servers

  # Phase 2: Wait for servers to be ready
  log "Phase 2: Waiting for servers to be ready..."
  wait_for_servers

  # Phase 3: Run wrk benchmarks (parallel per instance, sequential per run)
  log "Phase 3: Running wrk benchmarks..."
  run_wrk_parallel

  # Phase 4: Cleanup
  log "Phase 4: Cleanup servers..."
  kubectl delete deployment -n benchmark -l app=springboot-server --ignore-not-found=true
  kubectl delete service -n benchmark -l app=springboot-server --ignore-not-found=true

  log "===== wrk Benchmark Complete ====="
}

deploy_all_servers() {
  for instance in "${INTEL_INSTANCES[@]}"; do
    local safe_name=$(echo "$instance" | tr '.' '-')

    if kubectl get deployment -n benchmark "springboot-server-${safe_name}" &>/dev/null; then
      log "  [SKIP] springboot-server-${safe_name} already exists"
      continue
    fi

    cat "$SERVER_TEMPLATE" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s|\${INSTANCE_TYPE}|${instance}|g" | \
      kubectl apply -f - 2>/dev/null

    log "  [DEPLOY] $instance"
  done

  for instance in "${GRAVITON_INSTANCES[@]}"; do
    local safe_name=$(echo "$instance" | tr '.' '-')

    if kubectl get deployment -n benchmark "springboot-server-${safe_name}" &>/dev/null; then
      log "  [SKIP] springboot-server-${safe_name} already exists"
      continue
    fi

    cat "$SERVER_TEMPLATE" | \
      sed "s/INSTANCE_SAFE/${safe_name}/g" | \
      sed "s|\${INSTANCE_TYPE}|${instance}|g" | \
      kubectl apply -f - 2>/dev/null

    log "  [DEPLOY] $instance"
  done
}

wait_for_servers() {
  local total=${#ALL_INSTANCES[@]}
  local max_wait=600  # 10 minutes
  local wait_time=0

  while [ $wait_time -lt $max_wait ]; do
    local ready=0
    for instance in "${ALL_INSTANCES[@]}"; do
      local safe_name=$(echo "$instance" | tr '.' '-')
      local replicas=$(kubectl get deployment -n benchmark "springboot-server-${safe_name}" \
        -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
      [ "$replicas" = "1" ] && ((ready++))
    done

    log "  Servers ready: $ready/$total (${wait_time}s elapsed)"

    if [ "$ready" -ge "$total" ]; then
      break
    fi

    sleep 15
    ((wait_time+=15))
  done
}

run_wrk_parallel() {
  # Run wrk for each instance in parallel (background jobs)
  # Each instance runs 5 sequential tests

  local pids=()

  for instance in "${ALL_INSTANCES[@]}"; do
    (
      local safe_name=$(echo "$instance" | tr '.' '-')
      local arch=$(get_arch "$instance")

      for run in 1 2 3 4 5; do
        local job_name="springboot-wrk-${safe_name}-run${run}"
        local log_file="$RESULTS_DIR/$instance/wrk${run}.log"

        # Skip if log already exists and has content
        if [ -s "$log_file" ]; then
          log "  [SKIP] $instance run$run - log exists"
          continue
        fi

        # Deploy wrk job
        cat "$WRK_TEMPLATE" | \
          sed "s/springboot-benchmark-INSTANCE_SAFE/${job_name}/g" | \
          sed "s/INSTANCE_SAFE/${safe_name}/g" | \
          sed "s|\${INSTANCE_TYPE}|${instance}|g" | \
          kubectl apply -f - 2>/dev/null

        # Wait for job completion (max 10 minutes per run)
        kubectl wait --for=condition=complete job/"$job_name" -n benchmark --timeout=600s 2>/dev/null || true

        # Collect log
        local pod=$(kubectl get pods -n benchmark -l job-name="$job_name" \
          --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

        if [ -n "$pod" ]; then
          kubectl logs -n benchmark "$pod" > "$log_file" 2>/dev/null
          if [ -s "$log_file" ]; then
            log "  [OK] $instance run$run"
          else
            log "  [EMPTY] $instance run$run - retrying..."
            rm -f "$log_file"
            sleep 2
            kubectl logs -n benchmark "$pod" > "$log_file" 2>/dev/null
            if [ -s "$log_file" ]; then
              log "  [OK] $instance run$run (retry)"
            else
              log "  [FAIL] $instance run$run - empty log"
              rm -f "$log_file"
            fi
          fi
        else
          log "  [FAIL] $instance run$run - no pod"
        fi

        # Cleanup job
        kubectl delete job "$job_name" -n benchmark --ignore-not-found=true 2>/dev/null
      done
    ) &
    pids+=($!)
  done

  # Wait for all background jobs
  log "Waiting for ${#pids[@]} parallel wrk processes..."
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

# ============================================================
# COLLECT LOGS ONLY
# ============================================================
collect_only() {
  log "===== Collecting Existing Logs ====="

  for instance in "${ALL_INSTANCES[@]}"; do
    mkdir -p "$RESULTS_DIR/$instance"
  done

  # Collect coldstart logs
  log "Collecting coldstart logs..."
  for run in 1 2 3 4 5; do
    for instance in "${ALL_INSTANCES[@]}"; do
      local safe_name=$(echo "$instance" | tr '.' '-')
      local job_name="springboot-coldstart-${safe_name}-run${run}"
      local log_file="$RESULTS_DIR/$instance/coldstart${run}.log"

      # Skip if already collected
      [ -s "$log_file" ] && continue

      local pod=$(kubectl get pods -n benchmark -l job-name="$job_name" \
        --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

      if [ -n "$pod" ]; then
        kubectl logs -n benchmark "$pod" > "$log_file" 2>/dev/null
        if [ -s "$log_file" ]; then
          log "  [OK] $instance coldstart${run}"
        else
          rm -f "$log_file"
        fi
      fi
    done
  done

  # Collect wrk logs if jobs exist
  log "Collecting wrk logs..."
  for run in 1 2 3 4 5; do
    for instance in "${ALL_INSTANCES[@]}"; do
      local safe_name=$(echo "$instance" | tr '.' '-')
      local job_name="springboot-wrk-${safe_name}-run${run}"
      local log_file="$RESULTS_DIR/$instance/wrk${run}.log"

      # Skip if already collected
      [ -s "$log_file" ] && continue

      local pod=$(kubectl get pods -n benchmark -l job-name="$job_name" \
        --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

      if [ -n "$pod" ]; then
        kubectl logs -n benchmark "$pod" > "$log_file" 2>/dev/null
        if [ -s "$log_file" ]; then
          log "  [OK] $instance wrk${run}"
        else
          rm -f "$log_file"
        fi
      fi
    done
  done

  log "===== Collection Complete ====="
}

# ============================================================
# STATUS CHECK
# ============================================================
status() {
  echo "===== SpringBoot Benchmark Status ====="
  echo ""
  echo "Coldstart Jobs:"
  kubectl get jobs -n benchmark -l benchmark=springboot-coldstart --no-headers 2>/dev/null | \
    awk '{print $1, $2}' | sort | head -20
  echo "..."
  local cs_total=$(kubectl get jobs -n benchmark -l benchmark=springboot-coldstart --no-headers 2>/dev/null | wc -l)
  local cs_done=$(kubectl get jobs -n benchmark -l benchmark=springboot-coldstart --no-headers 2>/dev/null | grep -c "1/1" || echo 0)
  echo "Total: $cs_done/$cs_total completed"
  echo ""

  echo "SpringBoot Servers:"
  kubectl get deployments -n benchmark -l app=springboot-server --no-headers 2>/dev/null | \
    awk '{print $1, $2}' | head -10
  echo "..."
  local srv_total=$(kubectl get deployments -n benchmark -l app=springboot-server --no-headers 2>/dev/null | wc -l)
  local srv_ready=$(kubectl get deployments -n benchmark -l app=springboot-server --no-headers 2>/dev/null | grep -c "1/1" || echo 0)
  echo "Total: $srv_ready/$srv_total ready"
  echo ""

  echo "wrk Jobs:"
  kubectl get jobs -n benchmark -l benchmark=springboot-benchmark --no-headers 2>/dev/null | \
    awk '{print $1, $2}' | head -10
  echo ""

  echo "Results Directory:"
  for instance in "${ALL_INSTANCES[@]:0:5}"; do
    echo -n "  $instance: "
    ls "$RESULTS_DIR/$instance/" 2>/dev/null | tr '\n' ' '
    echo ""
  done
  echo "  ..."
}

# ============================================================
# MAIN
# ============================================================
case "${1:-all}" in
  coldstart)
    run_coldstart
    ;;
  wrk)
    run_wrk
    ;;
  all)
    run_coldstart
    run_wrk
    ;;
  collect)
    collect_only
    ;;
  status)
    status
    ;;
  *)
    echo "Usage: $0 {coldstart|wrk|all|collect|status}"
    echo ""
    echo "Commands:"
    echo "  coldstart  - Run coldstart benchmark (255 jobs parallel)"
    echo "  wrk        - Run wrk HTTP benchmark (51 parallel × 5 sequential)"
    echo "  all        - Run both coldstart and wrk"
    echo "  collect    - Collect logs from existing jobs"
    echo "  status     - Show current benchmark status"
    exit 1
    ;;
esac
