#!/bin/bash
cd /home/ec2-user/benchmark
mkdir -p results/sysbench/{c5.xlarge,c6g.xlarge}
for instance in c5.xlarge c6g.xlarge; do
  safe=$(echo $instance | tr '.' '-')
  for i in 1 2 3 4 5; do
    echo "[Sysbench] $instance run$i"
    sed -e "s/INSTANCE_SAFE/$safe/g" -e "s/\${INSTANCE_TYPE}/$instance/g" \
      benchmarks/system/sysbench-cpu.yaml | \
      sed "s/sysbench-cpu-$safe/sysbench-cpu-$safe-run$i/" | kubectl apply -f -
    kubectl wait --for=condition=complete job/sysbench-cpu-$safe-run$i -n benchmark --timeout=600s 2>/dev/null || true
    kubectl logs job/sysbench-cpu-$safe-run$i -n benchmark > results/sysbench/$instance/run$i.log 2>/dev/null
    kubectl delete job sysbench-cpu-$safe-run$i -n benchmark --ignore-not-found=true
    sleep 3
  done
done
echo "[Sysbench] DONE"
