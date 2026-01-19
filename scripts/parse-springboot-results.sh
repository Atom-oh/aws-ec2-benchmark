#!/bin/bash
# Parse Spring Boot benchmark results
# Output: results/springboot-summary.csv

RESULTS_DIR="/home/ec2-user/benchmark/results/springboot"
SERVER_LOGS_DIR="$RESULTS_DIR/server-logs"
OUTPUT_FILE="/home/ec2-user/benchmark/results/springboot-summary.csv"

echo "Parsing Spring Boot benchmark results..."

# CSV header
# JVM Startup: "Started DemoApplication in X.XXX seconds (process running for Y.YY)"
# Cold Start to First HTTP: Starting DemoApplication → Completed initialization
echo "instance_type,jvm_startup_sec,process_running_sec,starting_time,completed_time,coldstart_to_http_ms" > "$OUTPUT_FILE"

# Process each server log file
for logfile in "$SERVER_LOGS_DIR"/*.log; do
  [ -f "$logfile" ] || continue

  instance=$(basename "$logfile" .log)

  # Skip if not a valid instance
  [[ "$instance" == *"."* ]] || continue

  # Extract "Started DemoApplication in X.XXX seconds (process running for Y.YY)"
  started_line=$(grep "Started DemoApplication in" "$logfile" 2>/dev/null | head -1)
  jvm_startup=$(echo "$started_line" | grep -oP 'in \K[\d.]+(?= seconds)' || echo "")
  process_running=$(echo "$started_line" | grep -oP 'running for \K[\d.]+' || echo "")

  # Extract timestamps
  # Starting DemoApplication timestamp
  starting_time=$(grep "Starting DemoApplication" "$logfile" 2>/dev/null | head -1 | awk '{print $1}')

  # Completed initialization timestamp (DispatcherServlet lazy init on first HTTP request)
  completed_time=$(grep "Completed initialization" "$logfile" 2>/dev/null | head -1 | awk '{print $1}')

  # Calculate cold start to first HTTP (ms)
  coldstart_to_http_ms=""
  if [ -n "$starting_time" ] && [ -n "$completed_time" ]; then
    # Convert ISO timestamps to epoch milliseconds
    start_epoch=$(date -d "$starting_time" +%s%3N 2>/dev/null || echo "")
    end_epoch=$(date -d "$completed_time" +%s%3N 2>/dev/null || echo "")
    if [ -n "$start_epoch" ] && [ -n "$end_epoch" ]; then
      coldstart_to_http_ms=$((end_epoch - start_epoch))
    fi
  fi

  # Output CSV row
  if [ -n "$jvm_startup" ]; then
    echo "$instance,$jvm_startup,$process_running,$starting_time,$completed_time,$coldstart_to_http_ms" >> "$OUTPUT_FILE"
    echo "  $instance: JVM=${jvm_startup}s, ColdStart=${coldstart_to_http_ms}ms"
  else
    echo "  $instance: No startup data found"
  fi
done

echo ""
echo "Results saved to: $OUTPUT_FILE"
echo "Total instances: $(tail -n +2 "$OUTPUT_FILE" | wc -l)"

# Also create a simpler summary matching the guide format
SIMPLE_OUTPUT="/home/ec2-user/benchmark/results/springboot-coldstart-summary.csv"
echo "instance_type,jvm_startup_ms,coldstart_to_http_ms" > "$SIMPLE_OUTPUT"

tail -n +2 "$OUTPUT_FILE" | while IFS=, read -r instance jvm_startup process_running starting completed coldstart; do
  # Convert jvm_startup from seconds to ms
  jvm_ms=$(echo "$jvm_startup * 1000" | bc 2>/dev/null | cut -d'.' -f1)
  echo "$instance,$jvm_ms,$coldstart" >> "$SIMPLE_OUTPUT"
done

echo "Simple summary saved to: $SIMPLE_OUTPUT"
