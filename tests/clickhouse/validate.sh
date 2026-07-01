#!/bin/bash
# ClickHouse 벤치마크 산출물 검증 (단위테스트 대체 게이트).
# 라이브 클러스터 불필요 — YAML 파싱 / dry-run(client) / 구문 / 카운트 검증만.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(cd "$SCRIPT_DIR/../.." && pwd)"
CH="$BASE/benchmarks/clickhouse"
Q="$CH/queries"
PASS=0; FAIL=0
ok(){ echo "  ✓ $1"; PASS=$((PASS+1)); }
no(){ echo "  ✗ $1"; FAIL=$((FAIL+1)); }

yaml_ok(){ python3 -c "import yaml,sys;list(yaml.safe_load_all(open('$1')))" 2>/dev/null; }

echo "== Task 1: StorageClass + VolumeSnapshotClass =="
f="$CH/clickhouse-storageclass.yaml"
yaml_ok "$f" && ok "YAML 파싱" || no "YAML 파싱"
grep -q 'iops: "16000"' "$f" && grep -q 'throughput: "1000"' "$f" && ok "gp3 16000/1000" || no "gp3 스펙"
grep -q "gp3-clickhouse-snapclass" "$f" && ok "snapclass 포함" || no "snapclass"

echo "== Task 2: 정적 VolumeSnapshot (clickhouse-hits-024 → snap-024) =="
f="$CH/clickhouse-snapshot.yaml"
yaml_ok "$f" && ok "YAML 파싱" || no "YAML 파싱"
grep -q "snap-024c86faa00cd0448" "$f" && ok "snapshotHandle" || no "snapshotHandle"
grep -q "clickhouse-hits-024" "$f" && ok "고유 이름 clickhouse-hits-024 (라이브 충돌 없음)" || no "고유 이름"
grep -q "volumeSnapshotContentName" "$f" && grep -q "volumeSnapshotRef" "$f" && ok "정적 바인딩 API 필드" || no "바인딩 필드"
# Job PVC dataSource 가 동일 이름 참조하는지 (CRITICAL 정합성)
grep -q "name: clickhouse-hits-024" "$CH/clickhouse-clickbench.yaml" && ok "Job PVC dataSource 이름 정합" || no "PVC dataSource 이름 불일치"

echo "== Task 3: ClickBench 43쿼리 =="
n=$(grep -c ';' "$Q/queries.sql")
[ "$n" -eq 43 ] && ok "쿼리 43개 (세미콜론)" || no "쿼리 수=$n (기대 43)"
grep -qi "FROM hits" "$Q/queries.sql" && ok "hits 참조" || no "hits 참조"

echo "== Task 4: INSERT =="
grep -q "INSERT_ROWS" "$Q/insert.sql" && ok "INSERT_ROWS placeholder" || no "placeholder"
grep -qi "INSERT INTO hits" "$Q/insert.sql" && ok "INSERT 구문" || no "구문"

echo "== Task 5: self-JOIN =="
grep -qi "JOIN" "$Q/join.sql" && ok "JOIN 구문" || no "구문"
grep -q "grace_hash" "$Q/join.sql" && ok "grace_hash" || no "grace_hash"
grep -q "SPILL_BYTES" "$Q/join.sql" && grep -q "MAX_MEM_BYTES" "$Q/join.sql" && ok "RAM-상대 placeholder" || no "spill placeholder"

echo "== Task 6: Job 템플릿 (치환 후 dry-run) =="
f="$CH/clickhouse-clickbench.yaml"
for pair in "c8i.xlarge:amd64" "c8g.xlarge:arm64"; do
  inst="${pair%%:*}"; arch="${pair##*:}"; safe=$(echo "$inst"|tr '.' '-')
  out=$(cat "$f" | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${inst}/g" \
        | sed "s/RUN_NUMBER/1/g" | sed "s/CLICKHOUSE_VERSION/24.8.14.39/g" \
        | sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g")
  echo "$out" | python3 -c "import yaml,sys;list(yaml.safe_load_all(sys.stdin))" 2>/dev/null \
    && ok "치환 YAML ($inst)" || no "치환 YAML ($inst)"
  if echo "$out" | grep -Eq "INSTANCE_SAFE|INSTANCE_TYPE|RUN_NUMBER|CLICKHOUSE_VERSION|arch: ARCH"; then
    no "placeholder 잔류 ($inst)"; else ok "placeholder 잔류 0 ($inst)"; fi
  # 클러스터 있으면 dry-run (없으면 skip)
  if kubectl version --client >/dev/null 2>&1 && kubectl get ns benchmark >/dev/null 2>&1; then
    echo "$out" | kubectl apply --dry-run=client -f - >/dev/null 2>&1 && ok "dry-run ($inst)" || no "dry-run ($inst)"
  fi
done
grep -q "podAntiAffinity" "$f" && ok "podAntiAffinity" || no "podAntiAffinity"
grep -q "backoffLimit: 0" "$f" && ok "backoffLimit 0" || no "backoffLimit"
grep -q "chown -R 101:101" "$f" && ok "initContainer chown" || no "chown"
# 고정 메모리 limit 부재: limits: 아래 memory 가 없어야 함
if awk '/limits:/{f=1;next} f&&/memory:/{print;exit}' "$f" | grep -q memory; then
  no "고정 메모리 limit 존재"; else ok "고정 메모리 limit 없음"; fi

echo "== Task 7: 실행 스크립트 =="
s="$BASE/scripts/generate-clickhouse-benchmark.sh"
bash -n "$s" 2>/dev/null && ok "bash -n" || no "bash -n"
grep -q "create configmap clickhouse-queries" "$s" && ok "ConfigMap 생성" || no "ConfigMap"
ni=$(grep -vE '^\s*#|^\s*$' "$BASE/config/instances-4vcpu.txt" | awk '{print $1}' | grep -c xlarge)
[ "$ni" -eq 54 ] && ok "인스턴스 54개" || no "인스턴스=$ni"

echo "== Task 8: 리포트 파서 =="
p="$BASE/scripts/generate-clickhouse-report.py"
python3 -m py_compile "$p" 2>/dev/null && ok "py_compile" || no "py_compile"
python3 "$p" >/dev/null 2>&1 && ok "빈/부분 입력 graceful 실행" || no "실행 실패"

echo "== Task 9: 리포트 스캐폴드 =="
h="$BASE/results/clickhouse/report-charts.html"
grep -q 'cdn.jsdelivr.net/npm/chart.js' "$h" && ok "Chart.js CDN (ES 리포트와 동일, 프리뷰 동작)" || no "Chart.js 미참조"
# TDZ 방지: renderTable이 쓰는 let sortKey가 초기 실행 블록(if(!rows.length))보다 먼저 선언돼야 함
awk '/let sortKey/{s=NR} /if\(!rows.length\)/{e=NR} END{exit !(s&&e&&s<e)}' "$h" && ok "module-state가 실행 전 선언(TDZ 안전)" || no "TDZ 위험: let 선언이 실행 블록 뒤"
grep -q "EBS 대역폭" "$h" && ok "EBS 교란 명시" || no "EBS 교란"
python3 -c "import html.parser,sys
class P(html.parser.HTMLParser):
    pass
P().feed(open('$h').read())" 2>/dev/null && ok "HTML 파싱" || no "HTML 파싱"

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
