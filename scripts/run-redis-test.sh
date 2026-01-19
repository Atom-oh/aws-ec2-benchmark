#!/bin/bash
cd /home/ec2-user/benchmark
mkdir -p results/redis/{c5.xlarge,c6g.xlarge}
for instance in c5.xlarge c6g.xlarge; do
  safe=$(echo $instance | tr '.' '-')
  sed -e "s/INSTANCE_SAFE/$safe/g" -e "s/\${INSTANCE_TYPE}/$instance/g" \
    benchmarks/redis/redis-server.yaml | kubectl apply -f -
  sleep 40
  kubectl wait --for=condition=available deployment/redis-server-$safe -n benchmark --timeout=300s 2>/dev/null || true
  for i in 1 2 3 4 5; do
    echo "[Redis] $instance run$i"
    sed -e "s/INSTANCE_SAFE/$safe/g" -e "s/\${INSTANCE_TYPE}/$instance/g" \
      benchmarks/redis/redis-benchmark.yaml | \
      sed "s/redis-benchmark-$safe/redis-benchmark-$safe-run$i/" | kubectl apply -f -
    kubectl wait --for=condition=complete job/redis-benchmark-$safe-run$i -n benchmark --timeout=600s 2>/dev/null || true
    kubectl logs job/redis-benchmark-$safe-run$i -n benchmark > results/redis/$instance/run$i.log 2>/dev/null
    kubectl delete job redis-benchmark-$safe-run$i -n benchmark --ignore-not-found=true
    sleep 3
  done
  kubectl delete deployment redis-server-$safe -n benchmark --ignore-not-found=true
  kubectl delete service redis-server-$safe -n benchmark --ignore-not-found=true
done
echo "[Redis] DONE"
