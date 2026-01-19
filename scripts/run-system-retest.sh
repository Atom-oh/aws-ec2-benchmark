#!/bin/bash
# System 벤치마크 재실행 (Ubuntu 기반 multi-arch)
cd /home/ec2-user/benchmark

BENCHMARKS="sysbench-cpu sysbench-memory fio-disk stress-ng"
INSTANCES="c5.xlarge c6g.xlarge"

for bench in $BENCHMARKS; do
  echo "Starting $bench..."

  cat > /tmp/run-$bench.sh << 'SCRIPT'
#!/bin/bash
cd /home/ec2-user/benchmark
BENCH="$1"
for instance in c5.xlarge c6g.xlarge; do
  safe=$(echo $instance | tr '.' '-')
  for i in 1 2 3 4 5; do
    echo "[$BENCH] $instance run$i"

    # Create temp file with substitutions
    sed "s/INSTANCE_SAFE/$safe/g" benchmarks/system/$BENCH.yaml > /tmp/$BENCH-temp1.yaml
    sed 's/\${INSTANCE_TYPE}/'"$instance"'/g' /tmp/$BENCH-temp1.yaml > /tmp/$BENCH-temp2.yaml
    sed "s/name: $BENCH-$safe/name: $BENCH-$safe-run$i/" /tmp/$BENCH-temp2.yaml > /tmp/$BENCH-final.yaml

    kubectl apply -f /tmp/$BENCH-final.yaml
    kubectl wait --for=condition=complete job/$BENCH-$safe-run$i -n benchmark --timeout=900s 2>/dev/null || true
    kubectl logs job/$BENCH-$safe-run$i -n benchmark > results/$BENCH/$instance/run$i.log 2>/dev/null
    kubectl delete job $BENCH-$safe-run$i -n benchmark --ignore-not-found=true
    sleep 3
  done
done
echo "[$BENCH] DONE"
SCRIPT
  chmod +x /tmp/run-$bench.sh
  nohup /tmp/run-$bench.sh $bench > results/$bench.log 2>&1 &
  echo "$bench PID: $!"
done

echo ""
echo "=== System benchmarks started ==="
