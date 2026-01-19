#!/bin/bash
# Deploy Redis servers for all 51 instances

BENCHMARK_DIR="/home/ec2-user/benchmark"

INSTANCES=(
  c8i.xlarge c8i-flex.xlarge c8g.xlarge
  c7i.xlarge c7i-flex.xlarge c7g.xlarge c7gd.xlarge
  c6i.xlarge c6id.xlarge c6in.xlarge c6g.xlarge c6gd.xlarge c6gn.xlarge
  c5.xlarge c5a.xlarge c5d.xlarge c5n.xlarge
  m8i.xlarge m8g.xlarge
  m7i.xlarge m7i-flex.xlarge m7g.xlarge m7gd.xlarge
  m6i.xlarge m6id.xlarge m6in.xlarge m6idn.xlarge m6g.xlarge m6gd.xlarge
  m5.xlarge m5a.xlarge m5ad.xlarge m5d.xlarge m5zn.xlarge
  r8i.xlarge r8i-flex.xlarge r8g.xlarge
  r7i.xlarge r7g.xlarge r7gd.xlarge
  r6i.xlarge r6id.xlarge r6g.xlarge r6gd.xlarge
  r5.xlarge r5a.xlarge r5ad.xlarge r5b.xlarge r5d.xlarge r5dn.xlarge r5n.xlarge
)

echo "[$(date '+%H:%M:%S')] Deploying Redis ConfigMap..."
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: benchmark
data:
  redis.conf: |
    bind 0.0.0.0
    port 6379
    protected-mode no
    maxmemory 0
    tcp-backlog 511
    tcp-keepalive 300
    loglevel notice
    save ""
    appendonly no
    io-threads 2
    io-threads-do-reads yes
EOF

echo "[$(date '+%H:%M:%S')] Deploying ${#INSTANCES[@]} Redis servers..."

for INSTANCE in "${INSTANCES[@]}"; do
  SAFE_NAME=$(echo "$INSTANCE" | tr '.' '-')
  
  # Check if already exists
  if kubectl get deployment "redis-server-${SAFE_NAME}" -n benchmark &>/dev/null; then
    echo "  Skip ${INSTANCE} (already exists)"
    continue
  fi
  
  kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis-server-${SAFE_NAME}
  namespace: benchmark
  labels:
    app: redis-server
    benchmark: redis
    instance-type: "${INSTANCE}"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis-server
      instance-type: "${INSTANCE}"
  template:
    metadata:
      labels:
        app: redis-server
        benchmark: redis
        instance-type: "${INSTANCE}"
    spec:
      nodeSelector:
        node.kubernetes.io/instance-type: "${INSTANCE}"
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
        - name: redis
          image: public.ecr.aws/docker/library/redis:7-alpine
          resources: {}
          ports:
            - containerPort: 6379
          command:
            - redis-server
            - /etc/redis/redis.conf
          volumeMounts:
            - name: redis-config
              mountPath: /etc/redis
          readinessProbe:
            tcpSocket:
              port: 6379
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: redis-config
          configMap:
            name: redis-config
---
apiVersion: v1
kind: Service
metadata:
  name: redis-server-${SAFE_NAME}
  namespace: benchmark
  labels:
    app: redis-server
    instance-type: "${INSTANCE}"
spec:
  selector:
    app: redis-server
    instance-type: "${INSTANCE}"
  ports:
    - port: 6379
      targetPort: 6379
  type: ClusterIP
EOF

  echo "  Deployed redis-server-${SAFE_NAME}"
done

echo "[$(date '+%H:%M:%S')] Waiting for Redis servers to be ready..."

while true; do
  TOTAL=$(kubectl get pods -n benchmark -l app=redis-server --no-headers 2>/dev/null | wc -l)
  RUNNING=$(kubectl get pods -n benchmark -l app=redis-server --no-headers 2>/dev/null | grep -c Running || echo 0)
  echo "  Ready: ${RUNNING}/${#INSTANCES[@]}"
  
  if [ "$RUNNING" -ge "${#INSTANCES[@]}" ]; then
    break
  fi
  sleep 10
done

echo "[$(date '+%H:%M:%S')] All Redis servers are ready!"
