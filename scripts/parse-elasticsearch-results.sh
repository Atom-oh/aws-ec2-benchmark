#!/bin/bash
# Parse Elasticsearch benchmark results
# Output: results/elasticsearch-summary.csv

RESULTS_DIR="/home/ec2-user/benchmark/results/elasticsearch"
OUTPUT_FILE="/home/ec2-user/benchmark/results/elasticsearch-summary.csv"

echo "Parsing Elasticsearch benchmark results..."

# CSV header
echo "instance_type,cold_start_avg,cold_start_std,seq_index_avg,seq_index_std,bulk_index_avg,bulk_index_std,search_match_all_avg,search_match_all_std,search_term_avg,search_term_std,gc_time_avg,gc_time_std" > "$OUTPUT_FILE"

# Function to calculate mean and std
calc_stats() {
  local values=("$@")
  local n=${#values[@]}

  if [ $n -eq 0 ]; then
    echo "0 0"
    return
  fi

  # Filter out empty values
  local valid_values=()
  for v in "${values[@]}"; do
    [ -n "$v" ] && [[ "$v" =~ ^[0-9.]+$ ]] && valid_values+=("$v")
  done

  n=${#valid_values[@]}
  if [ $n -eq 0 ]; then
    echo "0 0"
    return
  fi

  # Calculate mean
  local sum=0
  for v in "${valid_values[@]}"; do
    sum=$(echo "$sum + $v" | bc -l 2>/dev/null || echo "$sum")
  done
  local mean=$(echo "scale=2; $sum / $n" | bc -l 2>/dev/null || echo "0")

  # Calculate std
  local sq_sum=0
  for v in "${valid_values[@]}"; do
    local diff=$(echo "$v - $mean" | bc -l 2>/dev/null || echo "0")
    sq_sum=$(echo "$sq_sum + ($diff * $diff)" | bc -l 2>/dev/null || echo "$sq_sum")
  done
  local std=$(echo "scale=2; sqrt($sq_sum / $n)" | bc -l 2>/dev/null || echo "0")

  echo "$mean $std"
}

# Process each instance directory
for instance_dir in "$RESULTS_DIR"/*/; do
  [ -d "$instance_dir" ] || continue

  instance=$(basename "$instance_dir")

  # Skip if not a valid instance directory
  [[ "$instance" == *"."* ]] || continue

  # Arrays to collect values across runs
  cold_start_values=()
  seq_index_values=()
  bulk_index_values=()
  search_match_all_values=()
  search_term_values=()
  gc_time_values=()

  # Process each run
  for run_file in "$instance_dir"/run*.log; do
    [ -f "$run_file" ] || continue

    # Extract metrics (format: "METRIC_NAME: VALUE")
    cold_start=$(grep "COLD_START_MS:" "$run_file" | tail -1 | awk '{print $2}')
    seq_index=$(grep "SEQUENTIAL_INDEX_100_MS:" "$run_file" | head -1 | awk '{print $2}')
    bulk_index=$(grep "BULK_INDEX_1000_MS:" "$run_file" | head -1 | awk '{print $2}')
    # Handle both SEamd64_ and SEARCH_ prefixes
    search_match_all=$(grep -E "(SEamd64_MATCH_ALL_AVG_MS|SEARCH_MATCH_ALL_AVG_MS):" "$run_file" | head -1 | awk '{print $2}')
    search_term=$(grep -E "(SEamd64_TERM_AVG_MS|SEARCH_TERM_AVG_MS):" "$run_file" | head -1 | awk '{print $2}')
    gc_time=$(grep "GC_TIME_DURING_TEST_MS:" "$run_file" | head -1 | awk '{print $2}')

    [ -n "$cold_start" ] && cold_start_values+=("$cold_start")
    [ -n "$seq_index" ] && seq_index_values+=("$seq_index")
    [ -n "$bulk_index" ] && bulk_index_values+=("$bulk_index")
    [ -n "$search_match_all" ] && search_match_all_values+=("$search_match_all")
    [ -n "$search_term" ] && search_term_values+=("$search_term")
    [ -n "$gc_time" ] && gc_time_values+=("$gc_time")
  done

  # Calculate statistics
  cold_start_stats=$(calc_stats "${cold_start_values[@]}")
  seq_index_stats=$(calc_stats "${seq_index_values[@]}")
  bulk_index_stats=$(calc_stats "${bulk_index_values[@]}")
  search_match_all_stats=$(calc_stats "${search_match_all_values[@]}")
  search_term_stats=$(calc_stats "${search_term_values[@]}")
  gc_time_stats=$(calc_stats "${gc_time_values[@]}")

  # Output CSV row
  echo "$instance,${cold_start_stats// /,},${seq_index_stats// /,},${bulk_index_stats// /,},${search_match_all_stats// /,},${search_term_stats// /,},${gc_time_stats// /,}" >> "$OUTPUT_FILE"

  echo "  $instance: ${#cold_start_values[@]} runs processed"
done

echo ""
echo "Results saved to: $OUTPUT_FILE"
echo "Total instances: $(tail -n +2 "$OUTPUT_FILE" | wc -l)"
