#!/bin/bash
# Benchmark 리소스 전체 정리
# benchmark namespace 삭제로 모든 리소스 한번에 제거

set -e

NAMESPACE="benchmark"

echo "🧹 Cleaning up benchmark resources..."

# 1. Namespace 내 모든 리소스 확인
echo ""
echo "📋 Resources in ${NAMESPACE} namespace:"
kubectl get all -n ${NAMESPACE} 2>/dev/null || echo "Namespace not found or empty"

# 2. 사용자 확인
read -p "Delete all resources in '${NAMESPACE}' namespace? (y/N): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Cancelled."
    exit 0
fi

# 3. Namespace 삭제 (모든 리소스 자동 삭제)
echo ""
echo "🗑️  Deleting namespace: ${NAMESPACE}"
kubectl delete namespace ${NAMESPACE} --ignore-not-found

# 4. Karpenter 노드 정리 (benchmark 라벨이 있는 노드)
echo ""
echo "🖥️  Cleaning up benchmark nodes..."
kubectl delete nodes -l node-type=benchmark --ignore-not-found 2>/dev/null || true

echo ""
echo "✅ Cleanup completed!"
