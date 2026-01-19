#!/bin/bash
cd /home/ec2-user/benchmark/results/redis

echo "instance,set_rps_avg,get_rps_avg,lpush_rps_avg,pipeline_set_avg"

for dir in */; do
    inst="${dir%/}"
    set_sum=0; get_sum=0; lpush_sum=0; pipe_sum=0; count=0

    for i in 1 2 3 4 5; do
        log="$dir/run$i.log"
        [ -s "$log" ] || continue

        # Extract final results (format: "SET: 40650.41 requests per second")
        set_val=$(grep -E "^\s*SET: [0-9.]+ requests" "$log" | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        get_val=$(grep -E "^\s*GET: [0-9.]+ requests" "$log" | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        lpush_val=$(grep -E "^\s*LPUSH: [0-9.]+ requests" "$log" | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        pipe_val=$(grep -A50 "Pipeline Benchmark" "$log" | grep -E "^\s*SET: [0-9.]+ requests" | grep -oE '[0-9]+\.[0-9]+' | head -1)

        [ -n "$set_val" ] && set_sum=$(echo "$set_sum + $set_val" | bc) && count=$((count+1))
        [ -n "$get_val" ] && get_sum=$(echo "$get_sum + $get_val" | bc)
        [ -n "$lpush_val" ] && lpush_sum=$(echo "$lpush_sum + $lpush_val" | bc)
        [ -n "$pipe_val" ] && pipe_sum=$(echo "$pipe_sum + $pipe_val" | bc)
    done

    if [ $count -gt 0 ]; then
        set_avg=$(echo "scale=2; $set_sum / $count" | bc)
        get_avg=$(echo "scale=2; $get_sum / $count" | bc)
        lpush_avg=$(echo "scale=2; $lpush_sum / $count" | bc)
        pipe_avg=$(echo "scale=2; $pipe_sum / $count" | bc)
        echo "$inst,$set_avg,$get_avg,$lpush_avg,$pipe_avg"
    fi
done
