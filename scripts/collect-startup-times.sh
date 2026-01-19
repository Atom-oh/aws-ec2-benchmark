#!/bin/bash
# Collect Spring Boot startup times from server logs

RESULTS_DIR="/home/ec2-user/benchmark/results/springboot"
OUTPUT_FILE="$RESULTS_DIR/startup-times.csv"

echo "instance_type,startup_seconds,process_seconds" > "$OUTPUT_FILE"

# Get all springboot-server deployments
for deploy in $(kubectl get deployments -n benchmark -l app=springboot-server -o name 2>/dev/null); do
  instance_type=$(kubectl get $deploy -n benchmark -o jsonpath='{.metadata.labels.instance-type}' 2>/dev/null)

  # Get startup time from logs
  log=$(kubectl logs -n benchmark $deploy 2>/dev/null | grep "Started DemoApplication" | head -1)

  if [ -n "$log" ]; then
    # Extract "Started DemoApplication in X.XXX seconds (process running for Y.YY)"
    startup=$(echo "$log" | grep -oP 'in \K[\d.]+(?= seconds)')
    process=$(echo "$log" | grep -oP 'running for \K[\d.]+')
    echo "$instance_type,$startup,$process"
    echo "$instance_type,$startup,$process" >> "$OUTPUT_FILE"
  fi
done

echo ""
echo "Results saved to $OUTPUT_FILE"
wc -l "$OUTPUT_FILE"
