#!/bin/bash
# Parse Redis benchmark results
# Output: results/redis-summary.csv

RESULTS_DIR="/home/ec2-user/benchmark/results/redis"
OUTPUT_FILE="/home/ec2-user/benchmark/results/redis-summary.csv"

echo "Parsing Redis benchmark results..."

# CSV header
echo "instance_type,set_avg,set_std,get_avg,get_std,pipeline_set_avg,pipeline_set_std,latency_p50_avg,latency_p50_std" > "$OUTPUT_FILE"

# Function to calculate mean and std
calc_stats() {
  local values=("$@")
  local n=${#values[@]}

  if [ $n -eq 0 ]; then
    echo "0 0"
    return
  fi

  # Calculate mean
  local sum=0
  for v in "${values[@]}"; do
    sum=$(echo "$sum + $v" | bc -l)
  done
  local mean=$(echo "scale=2; $sum / $n" | bc -l)

  # Calculate std
  local sq_sum=0
  for v in "${values[@]}"; do
    local diff=$(echo "$v - $mean" | bc -l)
    sq_sum=$(echo "$sq_sum + ($diff * $diff)" | bc -l)
  done
  local std=$(echo "scale=2; sqrt($sq_sum / $n)" | bc -l)

  echo "$mean $std"
}

# Process each instance directory
for instance_dir in "$RESULTS_DIR"/*/; do
  [ -d "$instance_dir" ] || continue

  instance=$(basename "$instance_dir")

  # Skip if not a valid instance directory
  [[ "$instance" == *"."* ]] || continue

  # Arrays to collect values across runs
  set_values=()
  get_values=()
  pipeline_set_values=()
  latency_p50_values=()

  # Process each run
  for run_file in "$instance_dir"/run*.log; do
    [ -f "$run_file" ] || continue

    # Extract results (format: "COMMAND: XXXXX.XX requests per second, p50=X.XXX msec")
    # Get all matching lines
    results=$(grep -oE "[A-Z_]+: [0-9.]+ requests per second, p50=[0-9.]+ msec" "$run_file" 2>/dev/null)

    # Standard SET (first occurrence, typically ~100K range)
    set_val=$(echo "$results" | grep "SET:" | head -1 | grep -oP "SET: \K[0-9.]+")
    [ -n "$set_val" ] && set_values+=("$set_val")

    # Standard GET (first occurrence)
    get_val=$(echo "$results" | grep "GET:" | head -1 | grep -oP "GET: \K[0-9.]+")
    [ -n "$get_val" ] && get_values+=("$get_val")

    # Pipeline SET (very high value, typically 500K+)
    # Find SET results > 500000 (pipeline results are much higher)
    for line in $(echo "$results" | grep "SET:" | grep -oP "SET: \K[0-9.]+"); do
      if [ -n "$line" ]; then
        is_pipeline=$(echo "$line > 500000" | bc -l 2>/dev/null || echo "0")
        if [ "$is_pipeline" = "1" ]; then
          pipeline_set_values+=("$line")
          break
        fi
      fi
    done

    # Latency p50 from standard SET
    latency_val=$(echo "$results" | grep "SET:" | head -1 | grep -oP "p50=\K[0-9.]+")
    [ -n "$latency_val" ] && latency_p50_values+=("$latency_val")
  done

  # Calculate statistics
  set_stats=$(calc_stats "${set_values[@]}")
  get_stats=$(calc_stats "${get_values[@]}")
  pipeline_set_stats=$(calc_stats "${pipeline_set_values[@]}")
  latency_stats=$(calc_stats "${latency_p50_values[@]}")

  # Output CSV row
  echo "$instance,${set_stats// /,},${get_stats// /,},${pipeline_set_stats// /,},${latency_stats// /,}" >> "$OUTPUT_FILE"

  echo "  $instance: ${#set_values[@]} runs processed"
done

echo ""
echo "Results saved to: $OUTPUT_FILE"
echo "Total instances: $(tail -n +2 "$OUTPUT_FILE" | wc -l)"
