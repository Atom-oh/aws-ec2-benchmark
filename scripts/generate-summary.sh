#!/bin/bash
# Generate Summary CSV for all benchmark results
cd /home/ec2-user/benchmark/results

echo "Generating summary CSVs..."

# ============ Redis Summary ============
echo "Processing Redis..."
echo "instance,set_rps,get_rps,incr_rps,lpush_rps,mset_rps" > redis/summary.csv
for dir in redis/*/; do
  instance=$(basename "$dir")
  if [ -f "${dir}run1.log" ]; then
    set_rps=$(grep "SET:" "${dir}"run*.log 2>/dev/null | grep "requests per second" | awk -F: '{print $NF}' | awk '{sum+=$1; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    get_rps=$(grep "GET:" "${dir}"run*.log 2>/dev/null | grep "requests per second" | awk -F: '{print $NF}' | awk '{sum+=$1; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    incr_rps=$(grep "INCR:" "${dir}"run*.log 2>/dev/null | grep "requests per second" | awk -F: '{print $NF}' | awk '{sum+=$1; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    lpush_rps=$(grep "LPUSH:" "${dir}"run*.log 2>/dev/null | grep "requests per second" | head -5 | awk -F: '{print $NF}' | awk '{sum+=$1; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    mset_rps=$(grep "MSET" "${dir}"run*.log 2>/dev/null | grep "requests per second" | awk -F: '{print $NF}' | awk '{sum+=$1; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    echo "${instance},${set_rps},${get_rps},${incr_rps},${lpush_rps},${mset_rps}" >> redis/summary.csv
  fi
done

# ============ Nginx Summary ============
echo "Processing Nginx..."
echo "instance,rps_2t_100c,rps_4t_200c,rps_8t_400c" > nginx/summary.csv
for dir in nginx/*/; do
  instance=$(basename "$dir")
  if [ -f "${dir}run1.log" ]; then
    rps_2t=$(grep -A5 "2 threads and 100 connections" "${dir}"run*.log 2>/dev/null | grep "Requests/sec:" | awk '{sum+=$2; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    rps_4t=$(grep -A5 "4 threads and 200 connections" "${dir}"run*.log 2>/dev/null | grep "Requests/sec:" | awk '{sum+=$2; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    rps_8t=$(grep -A5 "8 threads and 400 connections" "${dir}"run*.log 2>/dev/null | grep "Requests/sec:" | awk '{sum+=$2; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    echo "${instance},${rps_2t},${rps_4t},${rps_8t}" >> nginx/summary.csv
  fi
done

# ============ SpringBoot Summary ============
echo "Processing SpringBoot..."
echo "instance,rps_50c,rps_100c,rps_200c" > springboot/summary.csv
for dir in springboot/*/; do
  instance=$(basename "$dir")
  if [ -f "${dir}run1.log" ]; then
    rps_50=$(grep -A10 "50 connections" "${dir}"run*.log 2>/dev/null | grep "Requests/sec:" | awk '{sum+=$2; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    rps_100=$(grep -A10 "100 connections" "${dir}"run*.log 2>/dev/null | grep "Requests/sec:" | awk '{sum+=$2; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    rps_200=$(grep -A10 "200 connections" "${dir}"run*.log 2>/dev/null | grep "Requests/sec:" | awk '{sum+=$2; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    echo "${instance},${rps_50},${rps_100},${rps_200}" >> springboot/summary.csv
  fi
done

# ============ Elasticsearch Summary ============
echo "Processing Elasticsearch..."
echo "instance,cold_start_ms" > elasticsearch/summary.csv
for dir in elasticsearch/*/; do
  instance=$(basename "$dir")
  if [ -f "${dir}run1.log" ]; then
    # Extract cold start time from COLD_START_MS line
    cold_start=$(grep "COLD_START_MS:" "${dir}"run*.log 2>/dev/null | awk -F: '{sum+=$2; n++} END {if(n>0) printf "%.0f", sum/n; else print "0"}')
    [ -z "$cold_start" ] && cold_start="0"
    echo "${instance},${cold_start}" >> elasticsearch/summary.csv
  fi
done

# ============ sysbench-cpu Summary ============
echo "Processing sysbench-cpu..."
echo "instance,events_per_sec_avg" > sysbench-cpu/summary.csv
for dir in sysbench-cpu/*/; do
  instance=$(basename "$dir")
  if [ -f "${dir}run1.log" ]; then
    eps=$(grep "events per second:" "${dir}"run*.log 2>/dev/null | awk '{sum+=$NF; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
    echo "${instance},${eps}" >> sysbench-cpu/summary.csv
  fi
done

# ============ sysbench-memory Summary ============
echo "Processing sysbench-memory..."
echo "instance,write_ops_per_sec,read_ops_per_sec,write_mib_per_sec,read_mib_per_sec" > sysbench-memory/summary.csv
for dir in sysbench-memory/*/; do
  instance=$(basename "$dir")
  if [ -f "${dir}run1.log" ]; then
    # Extract from "Total operations: X (Y per second)"
    write_ops=$(grep -A30 "operation: write" "${dir}"run*.log 2>/dev/null | grep "per second" | head -1 | grep -oP '\(\K[0-9.]+')
    read_ops=$(grep -A30 "operation: read" "${dir}"run*.log 2>/dev/null | grep "per second" | head -1 | grep -oP '\(\K[0-9.]+')
    # Extract MiB/sec
    write_mib=$(grep -A30 "operation: write" "${dir}"run*.log 2>/dev/null | grep "MiB/sec" | head -1 | grep -oP '\(\K[0-9.]+')
    read_mib=$(grep -A30 "operation: read" "${dir}"run*.log 2>/dev/null | grep "MiB/sec" | head -1 | grep -oP '\(\K[0-9.]+')
    echo "${instance},${write_ops:-0},${read_ops:-0},${write_mib:-0},${read_mib:-0}" >> sysbench-memory/summary.csv
  fi
done

# ============ stress-ng Summary ============
echo "Processing stress-ng..."
echo "instance,matrix_bogo_ops,cpu_float_bogo_ops,cpu_int_bogo_ops,memcpy_bogo_ops,cache_bogo_ops,switch_bogo_ops,branch_bogo_ops" > stress-ng/summary.csv
for dir in stress-ng/*/; do
  instance=$(basename "$dir")
  if [ -f "${dir}run1.log" ]; then
    matrix=$(grep "matrix" "${dir}"run*.log 2>/dev/null | grep -oP '\d+\.\d+(?=\s+\d+\.\d+$)' | head -1)
    cpu_float=$(grep -A1 "Float Operations" "${dir}"run*.log 2>/dev/null | grep "cpu" | grep -oP '\d+\.\d+(?=\s+\d+\.\d+$)' | head -1)
    cpu_int=$(grep -A1 "Integer Operations" "${dir}"run*.log 2>/dev/null | grep "cpu" | grep -oP '\d+\.\d+(?=\s+\d+\.\d+$)' | head -1)
    memcpy=$(grep "memcpy" "${dir}"run*.log 2>/dev/null | grep -oP '\d+\.\d+(?=\s+\d+\.\d+$)' | head -1)
    cache=$(grep "cache" "${dir}"run*.log 2>/dev/null | grep -oP '\d+\.\d+(?=\s+\d+\.\d+$)' | head -1)
    switch=$(grep "switch" "${dir}"run*.log 2>/dev/null | grep -oP '\d+\.\d+(?=\s+\d+\.\d+$)' | head -1)
    branch=$(grep "branch" "${dir}"run*.log 2>/dev/null | grep -oP '\d+\.\d+(?=\s+\d+\.\d+$)' | head -1)
    echo "${instance},${matrix:-0},${cpu_float:-0},${cpu_int:-0},${memcpy:-0},${cache:-0},${switch:-0},${branch:-0}" >> stress-ng/summary.csv
  fi
done

# ============ fio-disk Summary ============
echo "Processing fio-disk..."
echo "instance,rand_read_iops,rand_write_iops,seq_read_bw_kb,seq_write_bw_kb,mixed_read_iops,mixed_write_iops" > fio-disk/summary.csv
for dir in fio-disk/*/; do
  instance=$(basename "$dir")
  if [ -f "${dir}run1.log" ]; then
    rand_read=$(grep -A3 "Random Read 4K" "${dir}"run*.log 2>/dev/null | grep "iops" | head -1 | grep -oP '"iops": \K[0-9.]+')
    rand_write=$(grep -A3 "Random Write 4K" "${dir}"run*.log 2>/dev/null | grep "iops" | head -1 | grep -oP '"iops": \K[0-9.]+')
    seq_read=$(grep -A3 "Sequential Read" "${dir}"run*.log 2>/dev/null | grep "bw_kb" | head -1 | grep -oP '"bw_kb": \K[0-9.]+')
    seq_write=$(grep -A3 "Sequential Write" "${dir}"run*.log 2>/dev/null | grep "bw_kb" | head -1 | grep -oP '"bw_kb": \K[0-9.]+')
    mixed_read=$(grep -A3 "Mixed Random" "${dir}"run*.log 2>/dev/null | grep "read_iops" | head -1 | grep -oP '"read_iops": \K[0-9.]+')
    mixed_write=$(grep -A3 "Mixed Random" "${dir}"run*.log 2>/dev/null | grep "write_iops" | head -1 | grep -oP '"write_iops": \K[0-9.]+')
    echo "${instance},${rand_read:-0},${rand_write:-0},${seq_read:-0},${seq_write:-0},${mixed_read:-0},${mixed_write:-0}" >> fio-disk/summary.csv
  fi
done

echo ""
echo "=== Summary files generated ==="
ls -la */summary.csv 2>/dev/null
