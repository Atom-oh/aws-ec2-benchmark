#!/bin/bash
# 벤치마크 결과 수집 및 HTML 리포트 생성

RESULTS_DIR="/home/ec2-user/benchmark/results"
BENCHMARK_TYPE=${1:-all}  # all, geekbench, passmark, coldstart

# 인스턴스 목록
INTEL_INSTANCES="c8i.xlarge c8i-flex.xlarge c7i.xlarge c7i-flex.xlarge c6i.xlarge c6id.xlarge c6in.xlarge c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge m8i.xlarge m7i.xlarge m7i-flex.xlarge m6i.xlarge m6id.xlarge m6in.xlarge m6idn.xlarge m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge r8i.xlarge r8i-flex.xlarge r7i.xlarge r6i.xlarge r6id.xlarge r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge"

GRAVITON_INSTANCES="c8g.xlarge c7g.xlarge c7gd.xlarge c6g.xlarge c6gd.xlarge c6gn.xlarge m8g.xlarge m7g.xlarge m7gd.xlarge m6g.xlarge m6gd.xlarge r8g.xlarge r7g.xlarge r7gd.xlarge r6g.xlarge r6gd.xlarge"

ALL_INSTANCES="$INTEL_INSTANCES $GRAVITON_INSTANCES"

echo "=========================================="
echo " 결과 수집 시작: $BENCHMARK_TYPE"
echo " Time: $(date)"
echo "=========================================="

# 함수: 로그 수집
collect_logs() {
    local benchmark=$1
    local label=$2

    echo ""
    echo "=== Collecting $benchmark logs ==="

    mkdir -p "$RESULTS_DIR/$benchmark"

    for instance in $ALL_INSTANCES; do
        local safe_name=$(echo "$instance" | tr '.' '-')
        local job_name="${benchmark}-${safe_name}"
        local pod_name=$(kubectl get pods -n benchmark -l job-name=$job_name --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)

        if [ -n "$pod_name" ]; then
            mkdir -p "$RESULTS_DIR/$benchmark/$instance"
            kubectl logs -n benchmark "$pod_name" > "$RESULTS_DIR/$benchmark/$instance/run1.log" 2>/dev/null
            echo "  Collected: $instance"
        else
            echo "  MISSING: $instance"
        fi
    done
}

# 함수: Cold Start 결과 파싱
parse_coldstart() {
    echo ""
    echo "=== Parsing Cold Start results ==="

    local csv="$RESULTS_DIR/coldstart/summary.csv"
    echo "instance,coldstart_ms,memory_mb" > "$csv"

    for instance in $ALL_INSTANCES; do
        local log="$RESULTS_DIR/coldstart/$instance/run1.log"
        if [ -f "$log" ]; then
            local coldstart=$(grep "COLD_START_MS:" "$log" 2>/dev/null | awk '{print $2}')
            local memory=$(grep "Total Memory:" "$log" 2>/dev/null | awk '{print $3}' | tr -d 'MB')
            echo "$instance,${coldstart:-0},${memory:-0}" >> "$csv"
        fi
    done

    echo "  Saved to: $csv"
}

# 함수: Geekbench 결과 파싱
parse_geekbench() {
    echo ""
    echo "=== Parsing Geekbench results ==="

    local csv="$RESULTS_DIR/geekbench/summary.csv"
    echo "instance,single_core,multi_core" > "$csv"

    for instance in $ALL_INSTANCES; do
        local log="$RESULTS_DIR/geekbench/$instance/run1.log"
        if [ -f "$log" ]; then
            local single=$(grep "SINGLE_CORE_SCORE:" "$log" 2>/dev/null | awk '{print $2}')
            local multi=$(grep "MULTI_CORE_SCORE:" "$log" 2>/dev/null | awk '{print $2}')
            echo "$instance,${single:-0},${multi:-0}" >> "$csv"
        fi
    done

    echo "  Saved to: $csv"
}

# 함수: Passmark 결과 파싱
parse_passmark() {
    echo ""
    echo "=== Parsing Passmark results ==="

    local csv="$RESULTS_DIR/passmark/summary.csv"
    echo "instance,cpu_mark" > "$csv"

    for instance in $ALL_INSTANCES; do
        local log="$RESULTS_DIR/passmark/$instance/run1.log"
        if [ -f "$log" ]; then
            local cpu_mark=$(grep "CPU_MARK:" "$log" 2>/dev/null | awk '{print $2}')
            echo "$instance,${cpu_mark:-0}" >> "$csv"
        fi
    done

    echo "  Saved to: $csv"
}

# 메인 실행
case $BENCHMARK_TYPE in
    coldstart)
        collect_logs "springboot-coldstart" "benchmark=springboot-coldstart"
        # 이름 변경
        mv "$RESULTS_DIR/springboot-coldstart" "$RESULTS_DIR/coldstart" 2>/dev/null || true
        parse_coldstart
        ;;
    geekbench)
        collect_logs "geekbench" "benchmark=geekbench"
        parse_geekbench
        ;;
    passmark)
        collect_logs "passmark" "benchmark=passmark"
        parse_passmark
        ;;
    all)
        collect_logs "springboot-coldstart" "benchmark=springboot-coldstart"
        mv "$RESULTS_DIR/springboot-coldstart" "$RESULTS_DIR/coldstart" 2>/dev/null || true
        parse_coldstart

        collect_logs "geekbench" "benchmark=geekbench"
        parse_geekbench

        collect_logs "passmark" "benchmark=passmark"
        parse_passmark
        ;;
esac

echo ""
echo "=========================================="
echo " 결과 수집 완료!"
echo " Time: $(date)"
echo "=========================================="
