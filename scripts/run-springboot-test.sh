#!/bin/bash
cd /home/ec2-user/benchmark
mkdir -p results/springboot/{c5.xlarge,c6g.xlarge}
for entry in "c5.xlarge amd64" "c6g.xlarge arm64"; do
  instance=$(echo $entry | cut -d' ' -f1)
  arch=$(echo $entry | cut -d' ' -f2)
  safe=$(echo $instance | tr '.' '-')
  for i in 1 2 3 4 5; do
    echo "[SpringBoot] $instance run$i"
    sed -e "s/INSTANCE_SAFE/$safe/g" -e "s/INSTANCE_TYPE/$instance/g" -e "s/ARCH/$arch/g" \
      benchmarks/springboot/springboot-coldstart.yaml | \
      sed "s/springboot-coldstart-$safe/springboot-coldstart-$safe-run$i/" | kubectl apply -f -
    kubectl wait --for=condition=complete job/springboot-coldstart-$safe-run$i -n benchmark --timeout=300s 2>/dev/null || true
    kubectl logs job/springboot-coldstart-$safe-run$i -n benchmark > results/springboot/$instance/run$i.log 2>/dev/null
    kubectl delete job springboot-coldstart-$safe-run$i -n benchmark --ignore-not-found=true
    sleep 5
  done
done
echo "[SpringBoot] DONE"
