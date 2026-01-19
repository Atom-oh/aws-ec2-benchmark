#!/bin/bash
# Benchmark 환경 초기 설정
# Namespace 생성 및 ConfigMaps 적용

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="benchmark"
BENCHMARK_DIR="${SCRIPT_DIR}/../benchmarks"

echo "🚀 Setting up benchmark environment..."

# 1. Namespace 생성
echo ""
echo "📦 Creating namespace: ${NAMESPACE}"
kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

# 2. ConfigMaps 적용 (Redis, Nginx 설정)
echo ""
echo "⚙️  Applying ConfigMaps..."

# Redis ConfigMap
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: ${NAMESPACE}
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
    io-threads 4
    io-threads-do-reads yes
EOF

# Nginx ConfigMap
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
  namespace: ${NAMESPACE}
data:
  nginx.conf: |
    worker_processes auto;
    worker_rlimit_nofile 65535;
    events {
        worker_connections 10240;
        use epoll;
        multi_accept on;
    }
    http {
        include /etc/nginx/mime.types;
        default_type application/octet-stream;
        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;
        keepalive_timeout 65;
        keepalive_requests 10000;
        access_log off;
        error_log /var/log/nginx/error.log crit;
        gzip off;
        server {
            listen 80 reuseport;
            server_name _;
            location / { root /usr/share/nginx/html; index index.html; }
            location /small { return 200 "OK"; add_header Content-Type text/plain; }
            location /json { return 200 '{"status":"ok"}'; add_header Content-Type application/json; }
            location /health { return 200 "healthy\n"; add_header Content-Type text/plain; }
        }
    }
  index.html: |
    <!DOCTYPE html><html><head><title>Benchmark</title></head>
    <body><h1>Nginx Benchmark Test Page</h1></body></html>
EOF

# 3. 결과 디렉토리 생성
mkdir -p "${SCRIPT_DIR}/../results/all"
mkdir -p "${SCRIPT_DIR}/../results/summary"

echo ""
echo "✅ Setup completed!"
echo ""
echo "Next steps:"
echo "  1. Apply Karpenter NodePool: kubectl apply -f karpenter/nodepool-8vcpu.yaml"
echo "  2. Run benchmark: ./scripts/run-benchmark-8vcpu.sh gen8"
echo "  3. Cleanup when done: ./scripts/cleanup.sh"
