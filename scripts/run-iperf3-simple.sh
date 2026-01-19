#!/bin/bash
# Simplified iperf3 benchmark using Pod IP directly (no Service needed)

set -e

BENCHMARK_DIR="/home/ec2-user/benchmark"
RESULTS_DIR="$BENCHMARK_DIR/results/iperf3"
RUNS=5

mkdir -p "$RESULTS_DIR"

run_iperf3_test() {
    local instance=$1
    local run=$2
    local safe_name=$(echo "$instance" | tr '.' '-')
    local result_dir="$RESULTS_DIR/$instance"
    
    mkdir -p "$result_dir"
    
    # Skip if already has result
    if [ -s "$result_dir/run${run}.log" ]; then
        echo "[Skip] $instance run$run - already exists"
        return 0
    fi
    
    echo "[Test] $instance run$run"
    
    # Deploy server
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: iperf3-server-${safe_name}
  namespace: benchmark
  labels:
    app: iperf3-server
    benchmark: iperf3
    instance-type: "${instance}"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: iperf3-server
      instance-type: "${instance}"
  template:
    metadata:
      labels:
        app: iperf3-server
        benchmark: iperf3
        instance-type: "${instance}"
    spec:
      nodeSelector:
        node.kubernetes.io/instance-type: "${instance}"
      tolerations:
        - key: "benchmark"
          operator: "Equal"
          value: "true"
          effect: "NoSchedule"
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: benchmark
                    operator: Exists
              topologyKey: "kubernetes.io/hostname"
      containers:
        - name: iperf3-server
          image: 180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/docker-hub/networkstatic/iperf3:latest
          args: ["-s"]
          ports:
            - containerPort: 5201
EOF
    
    # Wait for server pod to be ready and get its IP
    echo "  Waiting for server pod..."
    local server_ip=""
    for i in {1..60}; do
        server_ip=$(kubectl get pods -n benchmark -l app=iperf3-server,instance-type="${instance}" \
            -o jsonpath='{.items[0].status.podIP}' 2>/dev/null)
        if [ -n "$server_ip" ] && [ "$server_ip" != "null" ]; then
            status=$(kubectl get pods -n benchmark -l app=iperf3-server,instance-type="${instance}" \
                -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
            if [ "$status" = "Running" ]; then
                break
            fi
        fi
        sleep 5
    done
    
    if [ -z "$server_ip" ] || [ "$server_ip" = "null" ]; then
        echo "  ERROR: Server pod not ready"
        return 1
    fi
    
    echo "  Server ready at IP: $server_ip"
    
    # Run client job with Pod IP
    local job_name="iperf3-client-${safe_name}-run${run}"
    
    cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: benchmark
  labels:
    benchmark: iperf3
    test-type: network
    instance-type: "${instance}"
spec:
  ttlSecondsAfterFinished: 3600
  backoffLimit: 0
  template:
    metadata:
      labels:
        benchmark: iperf3
        test-type: network
    spec:
      restartPolicy: Never
      nodeSelector:
        node.kubernetes.io/instance-type: "${instance}"
      tolerations:
        - key: "benchmark"
          operator: "Equal"
          value: "true"
          effect: "NoSchedule"
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: benchmark
                    operator: Exists
              topologyKey: "kubernetes.io/hostname"
      containers:
        - name: iperf3-client
          image: 180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/docker-hub/networkstatic/iperf3:latest
          command:
            - /bin/sh
            - -c
            - |
              SERVER="${server_ip}"
              
              echo "===== iperf3 Network Benchmark ====="
              echo "Instance Type: ${instance}"
              echo "Server: \${SERVER}"
              echo ""
              
              # Wait for server to be ready
              for i in \$(seq 1 30); do
                if nc -z \${SERVER} 5201 2>/dev/null; then
                  break
                fi
                sleep 2
              done
              
              echo "--- TCP Bandwidth (Single Stream) ---"
              iperf3 -c \${SERVER} -t 30 -J | jq '{sender_mbps: .end.sum_sent.bits_per_second/1000000, receiver_mbps: .end.sum_received.bits_per_second/1000000}'
              
              echo ""
              echo "--- TCP Bandwidth (8 Parallel Streams) ---"
              iperf3 -c \${SERVER} -t 30 -P 8 -J | jq '{sender_mbps: .end.sum_sent.bits_per_second/1000000, receiver_mbps: .end.sum_received.bits_per_second/1000000}'
              
              echo ""
              echo "--- TCP Bandwidth (Reverse Mode) ---"
              iperf3 -c \${SERVER} -t 30 -R -J | jq '{sender_mbps: .end.sum_sent.bits_per_second/1000000, receiver_mbps: .end.sum_received.bits_per_second/1000000}'
              
              echo ""
              echo "--- UDP Bandwidth Test (1Gbps target) ---"
              iperf3 -c \${SERVER} -t 30 -u -b 1G -J | jq '{mbps: .end.sum.bits_per_second/1000000, jitter_ms: .end.sum.jitter_ms, lost_percent: .end.sum.lost_percent}'
              
              echo ""
              echo "===== iperf3 Benchmark Complete ====="
EOF
    
    # Wait for job to complete
    echo "  Waiting for client job..."
    for i in {1..60}; do
        status=$(kubectl get job -n benchmark "$job_name" --no-headers 2>/dev/null | awk '{print $2}')
        if [ "$status" = "Complete" ]; then
            break
        elif [ "$status" = "Failed" ]; then
            echo "  Job failed"
            break
        fi
        sleep 10
    done
    
    # Collect logs
    local pod=$(kubectl get pods -n benchmark -l job-name="$job_name" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -n "$pod" ]; then
        kubectl logs -n benchmark "$pod" > "$result_dir/run${run}.log" 2>/dev/null
        size=$(stat -c%s "$result_dir/run${run}.log" 2>/dev/null || echo "0")
        echo "  Logs saved: $size bytes"
    fi
    
    # Cleanup job (keep server for next run)
    kubectl delete job -n benchmark "$job_name" --ignore-not-found=true 2>/dev/null
}

cleanup_server() {
    local instance=$1
    local safe_name=$(echo "$instance" | tr '.' '-')
    kubectl delete deployment -n benchmark "iperf3-server-${safe_name}" --ignore-not-found=true 2>/dev/null
}

# Main
INSTANCES=$(grep -v "^#" "$BENCHMARK_DIR/config/instances-4vcpu.txt" | grep -v "^$")

echo "===== iperf3 Network Benchmark ====="
echo ""

for instance in $INSTANCES; do
    # Run all runs for this instance
    for run in $(seq 1 $RUNS); do
        run_iperf3_test "$instance" "$run"
    done
    
    # Cleanup server after all runs
    cleanup_server "$instance"
done

echo ""
echo "===== iperf3 Benchmark Complete ====="
