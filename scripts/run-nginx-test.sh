#!/bin/bash
cd /home/ec2-user/benchmark
mkdir -p results/nginx/{c5.xlarge,c6g.xlarge}
kubectl apply -f benchmarks/nginx/nginx-server.yaml 2>/dev/null || true
for instance in c5.xlarge c6g.xlarge; do
  safe=$(echo $instance | tr '.' '-')
  sed -e "s/INSTANCE_SAFE/$safe/g" -e "s/\${INSTANCE_TYPE}/$instance/g" \
    benchmarks/nginx/nginx-server.yaml | kubectl apply -f -
  sleep 40
  kubectl wait --for=condition=available deployment/nginx-server-$safe -n benchmark --timeout=300s 2>/dev/null || true
  for i in 1 2 3 4 5; do
    echo "[Nginx] $instance run$i"
    sed -e "s/INSTANCE_SAFE/$safe/g" -e "s/\${INSTANCE_TYPE}/$instance/g" \
      benchmarks/nginx/nginx-benchmark.yaml | \
      sed "s/nginx-benchmark-$safe/nginx-benchmark-$safe-run$i/" | kubectl apply -f -
    kubectl wait --for=condition=complete job/nginx-benchmark-$safe-run$i -n benchmark --timeout=300s 2>/dev/null || true
    kubectl logs job/nginx-benchmark-$safe-run$i -n benchmark > results/nginx/$instance/run$i.log 2>/dev/null
    kubectl delete job nginx-benchmark-$safe-run$i -n benchmark --ignore-not-found=true
    sleep 3
  done
  kubectl delete deployment nginx-server-$safe -n benchmark --ignore-not-found=true
  kubectl delete service nginx-server-$safe -n benchmark --ignore-not-found=true
done
echo "[Nginx] DONE"
