#!/bin/bash
# 벤치마크 결과 파싱 스크립트
# 5회 반복 결과에서 평균, 표준편차 계산

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$BASE_DIR/results"

log_info() { echo "[INFO] $1"; }

# ===================
# SYSBENCH 파싱
# ===================
parse_sysbench() {
    log_info "Parsing Sysbench results..."
    local output_csv="$RESULTS_DIR/sysbench-summary.csv"

    echo "Instance Type,MT events/sec (avg),MT events/sec (std),ST events/sec (avg),ST events/sec (std)" > "$output_csv"

    for instance_dir in "$RESULTS_DIR/sysbench"/*; do
        [[ -d "$instance_dir" ]] || continue
        local instance=$(basename "$instance_dir")

        local mt_values=()
        local st_values=()

        for run_log in "$instance_dir"/run*.log; do
            [[ -f "$run_log" ]] || continue

            # Multi-thread: 3회 평균의 events per second
            local mt_avg=$(grep "events per second:" "$run_log" | head -3 | awk '{sum+=$4} END {if(NR>0) print sum/NR; else print 0}')
            [[ -n "$mt_avg" && "$mt_avg" != "0" ]] && mt_values+=("$mt_avg")

            # Single-thread
            local st_val=$(grep -A20 "Single Thread Performance" "$run_log" | grep "events per second:" | awk '{print $4}')
            [[ -n "$st_val" ]] && st_values+=("$st_val")
        done

        # 평균 및 표준편차 계산
        if [[ ${#mt_values[@]} -gt 0 ]]; then
            local mt_avg=$(echo "${mt_values[@]}" | tr ' ' '\n' | awk '{sum+=$1; sumsq+=$1*$1} END {print sum/NR}')
            local mt_std=$(echo "${mt_values[@]}" | tr ' ' '\n' | awk -v avg="$mt_avg" '{sumsq+=($1-avg)^2} END {print sqrt(sumsq/NR)}')
        else
            mt_avg="N/A"; mt_std="N/A"
        fi

        if [[ ${#st_values[@]} -gt 0 ]]; then
            local st_avg=$(echo "${st_values[@]}" | tr ' ' '\n' | awk '{sum+=$1; sumsq+=$1*$1} END {print sum/NR}')
            local st_std=$(echo "${st_values[@]}" | tr ' ' '\n' | awk -v avg="$st_avg" '{sumsq+=($1-avg)^2} END {print sqrt(sumsq/NR)}')
        else
            st_avg="N/A"; st_std="N/A"
        fi

        echo "$instance,$mt_avg,$mt_std,$st_avg,$st_std" >> "$output_csv"
    done

    log_info "Sysbench summary saved to $output_csv"
}

# ===================
# NGINX 파싱
# ===================
parse_nginx() {
    log_info "Parsing Nginx results..."
    local output_csv="$RESULTS_DIR/nginx-summary.csv"

    echo "Instance Type,2t/100c (avg),2t/100c (std),4t/200c (avg),4t/200c (std),8t/400c (avg),8t/400c (std),Latency Avg (ms)" > "$output_csv"

    for instance_dir in "$RESULTS_DIR/nginx"/*; do
        [[ -d "$instance_dir" ]] || continue
        local instance=$(basename "$instance_dir")

        local t2c100_values=()
        local t4c200_values=()
        local t8c400_values=()
        local latency_values=()

        for run_log in "$instance_dir"/run*.log; do
            [[ -f "$run_log" ]] || continue

            # 2t/100c
            local t2c100=$(grep -A5 "2 threads, 100 connections" "$run_log" | grep "Requests/sec:" | awk '{print $2}')
            [[ -n "$t2c100" ]] && t2c100_values+=("$t2c100")

            # 4t/200c
            local t4c200=$(grep -A5 "4 threads, 200 connections" "$run_log" | grep "Requests/sec:" | awk '{print $2}')
            [[ -n "$t4c200" ]] && t4c200_values+=("$t4c200")

            # 8t/400c
            local t8c400=$(grep -A5 "8 threads, 400 connections" "$run_log" | grep "Requests/sec:" | awk '{print $2}')
            [[ -n "$t8c400" ]] && t8c400_values+=("$t8c400")

            # Latency (첫 번째 테스트의 Avg)
            local lat=$(grep -A5 "2 threads, 100 connections" "$run_log" | grep "Latency" | head -1 | awk '{print $2}' | sed 's/ms//' | sed 's/us/*0.001/' | bc 2>/dev/null || echo "")
            [[ -n "$lat" ]] && latency_values+=("$lat")
        done

        # 평균 및 표준편차 계산
        calc_stats() {
            local -n arr=$1
            if [[ ${#arr[@]} -gt 0 ]]; then
                local avg=$(printf '%s\n' "${arr[@]}" | awk '{sum+=$1} END {printf "%.2f", sum/NR}')
                local std=$(printf '%s\n' "${arr[@]}" | awk -v avg="$avg" '{sumsq+=($1-avg)^2} END {printf "%.2f", sqrt(sumsq/NR)}')
                echo "$avg,$std"
            else
                echo "N/A,N/A"
            fi
        }

        local t2c100_stats=$(calc_stats t2c100_values)
        local t4c200_stats=$(calc_stats t4c200_values)
        local t8c400_stats=$(calc_stats t8c400_values)

        local lat_avg="N/A"
        if [[ ${#latency_values[@]} -gt 0 ]]; then
            lat_avg=$(printf '%s\n' "${latency_values[@]}" | awk '{sum+=$1} END {printf "%.3f", sum/NR}')
        fi

        echo "$instance,$t2c100_stats,$t4c200_stats,$t8c400_stats,$lat_avg" >> "$output_csv"
    done

    log_info "Nginx summary saved to $output_csv"
}

# ===================
# REDIS 파싱
# ===================
parse_redis() {
    log_info "Parsing Redis results..."
    local output_csv="$RESULTS_DIR/redis-summary.csv"

    echo "Instance Type,SET (avg),SET (std),GET (avg),GET (std),Pipeline SET (avg),Pipeline SET (std),Latency p50 (ms)" > "$output_csv"

    for instance_dir in "$RESULTS_DIR/redis"/*; do
        [[ -d "$instance_dir" ]] || continue
        local instance=$(basename "$instance_dir")

        local set_values=()
        local get_values=()
        local pipeline_set_values=()
        local latency_values=()

        for run_log in "$instance_dir"/run*.log; do
            [[ -f "$run_log" ]] || continue

            # Standard benchmark - SET
            local set_val=$(grep -A50 "Standard Benchmark" "$run_log" | grep "^SET:" | head -1 | awk '{print $2}')
            [[ -n "$set_val" ]] && set_values+=("$set_val")

            # Standard benchmark - GET
            local get_val=$(grep -A50 "Standard Benchmark" "$run_log" | grep "^GET:" | head -1 | awk '{print $2}')
            [[ -n "$get_val" ]] && get_values+=("$get_val")

            # Pipeline benchmark - SET
            local pipe_set=$(grep -A20 "Pipeline Benchmark" "$run_log" | grep "SET:" | awk '{print $2}')
            [[ -n "$pipe_set" ]] && pipeline_set_values+=("$pipe_set")

            # Latency p50 (from SET command)
            local lat=$(grep -A50 "Standard Benchmark" "$run_log" | grep "^SET:" | head -1 | grep -o "p50=[0-9.]*" | cut -d= -f2)
            [[ -n "$lat" ]] && latency_values+=("$lat")
        done

        # 평균 및 표준편차 계산
        calc_stats() {
            local -n arr=$1
            if [[ ${#arr[@]} -gt 0 ]]; then
                local avg=$(printf '%s\n' "${arr[@]}" | awk '{sum+=$1} END {printf "%.2f", sum/NR}')
                local std=$(printf '%s\n' "${arr[@]}" | awk -v avg="$avg" '{sumsq+=($1-avg)^2} END {printf "%.2f", sqrt(sumsq/NR)}')
                echo "$avg,$std"
            else
                echo "N/A,N/A"
            fi
        }

        local set_stats=$(calc_stats set_values)
        local get_stats=$(calc_stats get_values)
        local pipeline_stats=$(calc_stats pipeline_set_values)

        local lat_avg="N/A"
        if [[ ${#latency_values[@]} -gt 0 ]]; then
            lat_avg=$(printf '%s\n' "${latency_values[@]}" | awk '{sum+=$1} END {printf "%.3f", sum/NR}')
        fi

        echo "$instance,$set_stats,$get_stats,$pipeline_stats,$lat_avg" >> "$output_csv"
    done

    log_info "Redis summary saved to $output_csv"
}

# ===================
# ELASTICSEARCH 파싱
# ===================
parse_elasticsearch() {
    log_info "Parsing Elasticsearch results..."
    local output_csv="$RESULTS_DIR/elasticsearch-summary.csv"

    echo "Instance Type,Cold Start (avg ms),Cold Start (std ms),Index Time (avg ms),Index Time (std ms)" > "$output_csv"

    for instance_dir in "$RESULTS_DIR/elasticsearch"/*; do
        [[ -d "$instance_dir" ]] || continue
        local instance=$(basename "$instance_dir")

        local coldstart_values=()
        local indextime_values=()

        for run_log in "$instance_dir"/run*.log; do
            [[ -f "$run_log" ]] || continue

            # Cold start time
            local cs=$(grep "COLD_START_MS:" "$run_log" | tail -1 | awk '{print $2}')
            [[ -n "$cs" ]] && coldstart_values+=("$cs")

            # Index time
            local idx=$(grep "INDEX_TIME_MS:" "$run_log" | awk '{print $2}')
            [[ -n "$idx" ]] && indextime_values+=("$idx")
        done

        # 평균 및 표준편차 계산
        calc_stats() {
            local -n arr=$1
            if [[ ${#arr[@]} -gt 0 ]]; then
                local avg=$(printf '%s\n' "${arr[@]}" | awk '{sum+=$1} END {printf "%.2f", sum/NR}')
                local std=$(printf '%s\n' "${arr[@]}" | awk -v avg="$avg" '{sumsq+=($1-avg)^2} END {printf "%.2f", sqrt(sumsq/NR)}')
                echo "$avg,$std"
            else
                echo "N/A,N/A"
            fi
        }

        local cs_stats=$(calc_stats coldstart_values)
        local idx_stats=$(calc_stats indextime_values)

        echo "$instance,$cs_stats,$idx_stats" >> "$output_csv"
    done

    log_info "Elasticsearch summary saved to $output_csv"
}

# ===================
# MAIN
# ===================
case "${1:-all}" in
    sysbench)
        parse_sysbench
        ;;
    nginx)
        parse_nginx
        ;;
    redis)
        parse_redis
        ;;
    elasticsearch)
        parse_elasticsearch
        ;;
    all)
        parse_sysbench
        parse_nginx
        parse_redis
        parse_elasticsearch
        ;;
    *)
        echo "Usage: $0 [sysbench|nginx|redis|elasticsearch|all]"
        exit 1
        ;;
esac

log_info "All parsing complete!"
log_info "Summary files:"
ls -la "$RESULTS_DIR"/*-summary.csv 2>/dev/null || echo "No summary files found"
