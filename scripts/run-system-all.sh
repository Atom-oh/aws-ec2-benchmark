#!/bin/bash
# 모든 system 벤치마크 병렬 실행
cd /home/ec2-user/benchmark

BENCHMARKS="sysbench-cpu sysbench-memory fio-disk stress-ng"
# geekbench, passmark, startup-time은 특수 케이스로 제외
# iperf3는 서버+클라이언트 구조로 별도 처리

for bench in $BENCHMARKS; do
  echo "Starting $bench..."
  mkdir -p results/$bench/{c5.xlarge,c6g.xlarge}

  cat > /tmp/run-$bench.sh << SCRIPT
#!/bin/bash
cd /home/ec2-user/benchmark
for instance in c5.xlarge c6g.xlarge; do
  safe=\$(echo \$instance | tr '.' '-')
  for i in 1 2 3 4 5; do
    echo "[$bench] \$instance run\$i"
    sed -e "s/INSTANCE_SAFE/\$safe/g" -e "s/\\\${INSTANCE_TYPE}/\$instance/g" \
      benchmarks/system/$bench.yaml | \
      sed "s/$bench-\$safe/$bench-\$safe-run\$i/" | kubectl apply -f -
    kubectl wait --for=condition=complete job/$bench-\$safe-run\$i -n benchmark --timeout=900s 2>/dev/null || true
    kubectl logs job/$bench-\$safe-run\$i -n benchmark > results/$bench/\$instance/run\$i.log 2>/dev/null
    kubectl delete job $bench-\$safe-run\$i -n benchmark --ignore-not-found=true
    sleep 3
  done
done
echo "[$bench] DONE"
SCRIPT
  chmod +x /tmp/run-$bench.sh
  nohup /tmp/run-$bench.sh > results/$bench.log 2>&1 &
  echo "$bench PID: $!"
done

echo ""
echo "=== All system benchmarks started ==="
