#!/bin/bash
# Benchmark Results Collector and Parser
# 벤치마크 결과를 파싱하여 CSV 및 Markdown 형식으로 변환

set -e

RESULTS_DIR="$(dirname "$0")/../results"
OUTPUT_DIR="${RESULTS_DIR}/summary"

mkdir -p "${OUTPUT_DIR}"

# CSV 파일 초기화
init_csv_files() {
    # System benchmark CSV
    echo "instance_type,cpu_events_per_sec,cpu_latency_avg_ms,memory_write_mib_sec,memory_read_mib_sec,stress_matrix_bogo_ops" \
        > "${OUTPUT_DIR}/system-benchmark.csv"

    # Redis benchmark CSV
    echo "instance_type,set_rps,get_rps,set_p99_latency_ms,get_p99_latency_ms,pipeline_set_rps,pipeline_get_rps" \
        > "${OUTPUT_DIR}/redis-benchmark.csv"

    # Nginx benchmark CSV
    echo "instance_type,small_rps_100conn,small_latency_avg_ms,index_rps_100conn,json_rps_100conn,high_conn_500_rps" \
        > "${OUTPUT_DIR}/nginx-benchmark.csv"

    # Spring Boot benchmark CSV
    echo "instance_type,jvm_startup_ms,warmup_rps,main_rps_50conn,main_rps_100conn,p99_latency_ms" \
        > "${OUTPUT_DIR}/springboot-benchmark.csv"
}

# Sysbench CPU 결과 파싱
parse_sysbench_cpu() {
    local file=$1
    local instance_type=$2

    if [[ -f "$file" ]]; then
        local events_per_sec=$(grep "events per second:" "$file" | tail -1 | awk '{print $NF}')
        local latency_avg=$(grep "avg:" "$file" | tail -1 | awk '{print $2}')
        echo "${events_per_sec:-0},${latency_avg:-0}"
    else
        echo "0,0"
    fi
}

# Sysbench Memory 결과 파싱
parse_sysbench_memory() {
    local file=$1

    if [[ -f "$file" ]]; then
        # Sequential Write throughput
        local write_mib=$(grep -A5 "Sequential Write" "$file" | grep "MiB transferred" | head -1 | grep -oP '\d+\.\d+' | head -1)
        # Sequential Read throughput
        local read_mib=$(grep -A5 "Sequential Read" "$file" | grep "MiB transferred" | head -1 | grep -oP '\d+\.\d+' | head -1)
        echo "${write_mib:-0},${read_mib:-0}"
    else
        echo "0,0"
    fi
}

# stress-ng 결과 파싱
parse_stress_ng() {
    local file=$1

    if [[ -f "$file" ]]; then
        local matrix_ops=$(grep "matrix" "$file" | grep "bogo-ops-per-second" | awk '{print $(NF-1)}' | head -1)
        echo "${matrix_ops:-0}"
    else
        echo "0"
    fi
}

# Redis 벤치마크 결과 파싱
parse_redis() {
    local file=$1

    if [[ -f "$file" ]]; then
        local set_rps=$(grep "^SET:" "$file" | head -1 | grep -oP '\d+\.\d+' | head -1)
        local get_rps=$(grep "^GET:" "$file" | head -1 | grep -oP '\d+\.\d+' | head -1)
        # Pipeline 결과
        local pipe_set=$(grep "^SET:" "$file" | tail -1 | grep -oP '\d+\.\d+' | head -1)
        local pipe_get=$(grep "^GET:" "$file" | tail -1 | grep -oP '\d+\.\d+' | head -1)
        echo "${set_rps:-0},${get_rps:-0},0,0,${pipe_set:-0},${pipe_get:-0}"
    else
        echo "0,0,0,0,0,0"
    fi
}

# Nginx 벤치마크 결과 파싱 (wrk 출력)
parse_nginx() {
    local file=$1

    if [[ -f "$file" ]]; then
        # Small response, 100 connections
        local small_rps=$(grep -A10 "Small Response.*100 connections" "$file" | grep "Requests/sec:" | head -1 | awk '{print $2}')
        local small_latency=$(grep -A10 "Small Response.*100 connections" "$file" | grep "Latency" | head -1 | awk '{print $2}' | sed 's/ms//')
        # Index page, 100 connections
        local index_rps=$(grep -A10 "Index Page.*100 connections" "$file" | grep "Requests/sec:" | head -1 | awk '{print $2}')
        # JSON response
        local json_rps=$(grep -A10 "JSON Response" "$file" | grep "Requests/sec:" | head -1 | awk '{print $2}')
        # High connections (500)
        local high_rps=$(grep -A10 "High Connections" "$file" | grep "Requests/sec:" | head -1 | awk '{print $2}')

        echo "${small_rps:-0},${small_latency:-0},${index_rps:-0},${json_rps:-0},${high_rps:-0}"
    else
        echo "0,0,0,0,0"
    fi
}

# Spring Boot 벤치마크 결과 파싱
parse_springboot() {
    local startup_file=$1
    local throughput_file=$2

    local jvm_startup="0"
    local main_rps_50="0"
    local main_rps_100="0"
    local p99_latency="0"

    if [[ -f "$startup_file" ]]; then
        # JVM startup time (평균)
        jvm_startup=$(grep "Run" "$startup_file" | head -5 | awk -F': ' '{sum+=$2; count++} END {print sum/count}' | sed 's/ms//')
    fi

    if [[ -f "$throughput_file" ]]; then
        # Main page, 50 connections
        main_rps_50=$(grep -A10 "50 connections, 60s" "$throughput_file" | grep "Requests/sec:" | head -1 | awk '{print $2}')
        # Main page, 100 connections
        main_rps_100=$(grep -A10 "100 connections, 60s" "$throughput_file" | grep "Requests/sec:" | head -1 | awk '{print $2}')
        # P99 latency
        p99_latency=$(grep -A10 "100 connections, 60s" "$throughput_file" | grep "99%" | head -1 | awk '{print $2}' | sed 's/ms//')
    fi

    echo "${jvm_startup:-0},0,${main_rps_50:-0},${main_rps_100:-0},${p99_latency:-0}"
}

# 결과 수집 메인 함수
collect_results() {
    init_csv_files

    echo "Collecting benchmark results..."

    # 각 인스턴스 타입별 결과 수집
    for dir in "${RESULTS_DIR}/system" "${RESULTS_DIR}/redis" "${RESULTS_DIR}/nginx" "${RESULTS_DIR}/springboot"; do
        if [[ ! -d "$dir" ]]; then
            continue
        fi

        benchmark_type=$(basename "$dir")

        case $benchmark_type in
            "system")
                for cpu_file in "${dir}"/*.cpu; do
                    [[ -f "$cpu_file" ]] || continue
                    local basename=$(basename "$cpu_file" .cpu)
                    local instance_type=$(echo "$basename" | sed 's/-[0-9]*-[0-9]*$//' | tr '-' '.')

                    local memory_file="${cpu_file%.cpu}.memory"
                    local stress_file="${cpu_file%.cpu}.stress-ng"

                    local cpu_result=$(parse_sysbench_cpu "$cpu_file" "$instance_type")
                    local memory_result=$(parse_sysbench_memory "$memory_file")
                    local stress_result=$(parse_stress_ng "$stress_file")

                    echo "${instance_type},${cpu_result},${memory_result},${stress_result}" >> "${OUTPUT_DIR}/system-benchmark.csv"
                done
                ;;

            "redis")
                for result_file in "${dir}"/*.log; do
                    [[ -f "$result_file" ]] || continue
                    local basename=$(basename "$result_file" .log)
                    local instance_type=$(echo "$basename" | sed 's/-[0-9]*-[0-9]*$//' | tr '-' '.')

                    local redis_result=$(parse_redis "$result_file")
                    echo "${instance_type},${redis_result}" >> "${OUTPUT_DIR}/redis-benchmark.csv"
                done
                ;;

            "nginx")
                for result_file in "${dir}"/*.log; do
                    [[ -f "$result_file" ]] || continue
                    local basename=$(basename "$result_file" .log)
                    local instance_type=$(echo "$basename" | sed 's/-[0-9]*-[0-9]*$//' | tr '-' '.')

                    local nginx_result=$(parse_nginx "$result_file")
                    echo "${instance_type},${nginx_result}" >> "${OUTPUT_DIR}/nginx-benchmark.csv"
                done
                ;;

            "springboot")
                for startup_file in "${dir}"/*.startup; do
                    [[ -f "$startup_file" ]] || continue
                    local basename=$(basename "$startup_file" .startup)
                    local instance_type=$(echo "$basename" | sed 's/-[0-9]*-[0-9]*$//' | tr '-' '.')

                    local throughput_file="${startup_file%.startup}.throughput"
                    local springboot_result=$(parse_springboot "$startup_file" "$throughput_file")
                    echo "${instance_type},${springboot_result}" >> "${OUTPUT_DIR}/springboot-benchmark.csv"
                done
                ;;
        esac
    done

    echo "Results collected to: ${OUTPUT_DIR}"
}

# 실행
collect_results
