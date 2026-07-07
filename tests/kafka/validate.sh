#!/bin/bash
# Kafka 벤치마크 산출물 검증 (단위테스트 대체 게이트).
# 라이브 클러스터 불필요 — YAML 파싱 / dry-run(client) / 구문 / 카운트 검증만.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(cd "$SCRIPT_DIR/../.." && pwd)"
KF="$BASE/benchmarks/kafka"
PASS=0; FAIL=0
ok(){ echo "  ✓ $1"; PASS=$((PASS+1)); }
no(){ echo "  ✗ $1"; FAIL=$((FAIL+1)); }

yaml_ok(){ python3 -c "import yaml,sys;list(yaml.safe_load_all(open('$1')))" 2>/dev/null; }

echo "== Task 0: gp3-kafka StorageClass =="
fsc="$KF/kafka-storageclass.yaml"
yaml_ok "$fsc" && ok "YAML 파싱" || no "YAML 파싱"
grep -q "type: gp3" "$fsc" && ok "type: gp3" || no "type: gp3 누락"
grep -q 'throughput: "2000"' "$fsc" && ok "throughput 2000 (gp3 절대 최대)" || no "throughput 설정"
grep -q "io2" "$fsc" && ok "io2 시도 실패 사유 문서화" || no "io2 쿼터 이슈 문서화 누락"

echo "== Task 1: 브로커 템플릿 (치환 후 dry-run) =="
f="$KF/kafka-server.yaml"
yaml_ok "$f" && ok "YAML 파싱" || no "YAML 파싱"
grep -q "storageClassName: gp3-kafka" "$f" && ok "storageClassName: gp3-kafka" || no "storageClassName 확인"
for pair in "c8i.xlarge:amd64" "c8g.xlarge:arm64"; do
  inst="${pair%%:*}"; arch="${pair##*:}"; safe=$(echo "$inst"|tr '.' '-')
  out=$(cat "$f" | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${inst}/g" \
        | sed "s/KAFKA_VERSION/3.9.1/g" \
        | sed "s|kubernetes.io/arch: ARCH|kubernetes.io/arch: ${arch}|g")
  echo "$out" | python3 -c "import yaml,sys;list(yaml.safe_load_all(sys.stdin))" 2>/dev/null \
    && ok "치환 YAML ($inst)" || no "치환 YAML ($inst)"
  if echo "$out" | grep -Eq "INSTANCE_SAFE|INSTANCE_TYPE|KAFKA_VERSION|arch: ARCH"; then
    no "placeholder 잔류 ($inst)"; else ok "placeholder 잔류 0 ($inst)"; fi
  if kubectl version --client >/dev/null 2>&1 && kubectl get ns benchmark >/dev/null 2>&1; then
    echo "$out" | kubectl apply --dry-run=client -f - >/dev/null 2>&1 && ok "dry-run ($inst)" || no "dry-run ($inst)"
  fi
done
grep -q "podAntiAffinity" "$f" && ok "podAntiAffinity" || no "podAntiAffinity"
if awk '/limits:/{f=1;next} f&&/memory:/{print;exit}' "$f" | grep -q memory; then
  no "고정 메모리 limit 존재"; else ok "고정 메모리 limit 없음"; fi
grep -q "MEM_KB \* 25 / 100" "$f" && ok "힙 25%(RAM-relative) 계산" || no "힙 계산"
grep -q "benchmark.svc.cluster.local:9092" "$f" && ok "advertised.listeners = Service DNS (런타임 IP 치환 없음)" || no "advertised.listeners"
grep -qE "IPERF_SERVER_IP|_IP\"" "$f" && no "미치환 IP placeholder 흔적" || ok "IP placeholder 없음"

echo "== Task 2: 클라이언트 Job 템플릿 (치환 후 dry-run) =="
f="$KF/kafka-benchmark.yaml"
yaml_ok "$f" && ok "YAML 파싱" || no "YAML 파싱"
for inst in "c8i.xlarge" "c8g.xlarge"; do
  safe=$(echo "$inst"|tr '.' '-')
  out=$(cat "$f" | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${inst}/g" \
        | sed "s/RUN_NUMBER/1/g" | sed "s/KAFKA_VERSION/3.9.1/g")
  echo "$out" | python3 -c "import yaml,sys;list(yaml.safe_load_all(sys.stdin))" 2>/dev/null \
    && ok "치환 YAML ($inst)" || no "치환 YAML ($inst)"
  if echo "$out" | grep -Eq "INSTANCE_SAFE|INSTANCE_TYPE|RUN_NUMBER|KAFKA_VERSION"; then
    no "placeholder 잔류 ($inst)"; else ok "placeholder 잔류 0 ($inst)"; fi
  if kubectl version --client >/dev/null 2>&1 && kubectl get ns benchmark >/dev/null 2>&1; then
    echo "$out" | kubectl apply --dry-run=client -f - >/dev/null 2>&1 && ok "dry-run ($inst)" || no "dry-run ($inst)"
  fi
done
grep -q "podAntiAffinity" "$f" && ok "podAntiAffinity" || no "podAntiAffinity"
grep -q "podAffinity" "$f" && ok "podAffinity (같은 AZ 배치)" || no "podAffinity"
grep -q "backoffLimit: 0" "$f" && ok "backoffLimit 0" || no "backoffLimit"
grep -q "node-type: benchmark-client" "$f" && ok "benchmark-client 노드풀 지정" || no "benchmark-client nodeSelector"
grep -q "SERVER_VERSION:" "$f" && ok "SERVER_VERSION 라벨 (KAFKA_VERSION과 충돌 없음)" || no "SERVER_VERSION 라벨"

echo "== Task 3: 실행 스크립트 (베이스라인) =="
s="$BASE/scripts/generate-kafka-benchmark.sh"
bash -n "$s" 2>/dev/null && ok "bash -n" || no "bash -n"
ni=$(grep -vE '^\s*#|^\s*$' "$BASE/config/instances-4vcpu.txt" | awk '{print $1}' | grep -c xlarge)
[ "$ni" -eq 54 ] && ok "인스턴스 54개" || no "인스턴스=$ni"
grep -q '| sed ' "$s" && ok "chained-pipe sed 사용" || no "chained-pipe sed"
grep -qE '^\s*sed -e .*-e ' "$s" && no "multi -e sed 사용 (금지 패턴)" || ok "multi -e sed 없음"

echo "== Task 3b: 포화(max) 클라이언트 Job 템플릿 (치환 후 dry-run) =="
f="$KF/kafka-benchmark-max.yaml"
yaml_ok "$f" && ok "YAML 파싱" || no "YAML 파싱"
for inst in "c8i.xlarge" "c8g.xlarge"; do
  for codec in uncompressed lz4 zstd; do
    safe=$(echo "$inst"|tr '.' '-')
    out=$(cat "$f" | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${inst}/g" \
          | sed "s/RUN_NUMBER/1/g" | sed "s/KAFKA_VERSION/3.9.1/g" | sed "s/CODEC/${codec}/g")
    echo "$out" | python3 -c "import yaml,sys;list(yaml.safe_load_all(sys.stdin))" 2>/dev/null \
      && ok "치환 YAML ($inst/$codec)" || no "치환 YAML ($inst/$codec)"
    if echo "$out" | grep -Eq "INSTANCE_SAFE|INSTANCE_TYPE|RUN_NUMBER|KAFKA_VERSION|CODEC"; then
      no "placeholder 잔류 ($inst/$codec)"; else ok "placeholder 잔류 0 ($inst/$codec)"; fi
    if kubectl version --client >/dev/null 2>&1 && kubectl get ns benchmark >/dev/null 2>&1; then
      echo "$out" | kubectl apply --dry-run=client -f - >/dev/null 2>&1 && ok "dry-run ($inst/$codec)" || no "dry-run ($inst/$codec)"
    fi
  done
done
grep -q "podAntiAffinity" "$f" && ok "podAntiAffinity" || no "podAntiAffinity"
grep -q "podAffinity" "$f" && ok "podAffinity (같은 AZ 배치)" || no "podAffinity"
grep -q "backoffLimit: 0" "$f" && ok "backoffLimit 0" || no "backoffLimit"
grep -q 'compression.type="${CODEC}"' "$f" && ok "토픽 레벨 compression.type=CODEC (브로커측 압축)" || no "토픽 압축 설정 누락"
grep -vE '^\s*#' "$f" | grep -q -- "--producer-props.*compression" && no "producer-props에 compression 존재 (측정 목적 위반)" || ok "producer-props에 compression 없음"
grep -q '/opt/kafka/bin' "$f" && ok "PATH export (/opt/kafka/bin)" || no "PATH export 누락"
grep -q "payload-file" "$f" && ok "압축 가능한 payload-file 사용" || no "payload-file 누락"
grep -q "kafka-log-dirs.sh" "$f" && ok "압축률 계산용 kafka-log-dirs.sh 사용" || no "log-dirs 누락"

echo "== Task 3c: 포화(max) 실행 스크립트 =="
sm="$BASE/scripts/generate-kafka-max-benchmark.sh"
bash -n "$sm" 2>/dev/null && ok "bash -n" || no "bash -n"
grep -q '| sed ' "$sm" && ok "chained-pipe sed 사용" || no "chained-pipe sed"
grep -qE '^\s*sed -e .*-e ' "$sm" && no "multi -e sed 사용 (금지 패턴)" || ok "multi -e sed 없음"
grep -q "results/kafka-max" "$sm" && ok "결과 디렉터리 분리 (results/kafka-max)" || no "결과 디렉터리"
grep -q 'kubectl(){ command kubectl --context mall-apne2-mgmt' "$sm" && ok "kubectl context 고정 (공유 kubeconfig 대비)" || no "kubectl context 고정 누락"
grep -q 'kubectl(){ command kubectl --context mall-apne2-mgmt' "$BASE/scripts/generate-kafka-benchmark.sh" && ok "베이스라인 스크립트도 context 고정" || no "베이스라인 스크립트 context 고정 누락"

echo "== Task 3d: 램프업(ramp, Phase 3) 클라이언트 Job 템플릿 (치환 후 dry-run) =="
fr="$KF/kafka-benchmark-ramp.yaml"
yaml_ok "$fr" && ok "YAML 파싱" || no "YAML 파싱"
for inst in "c8i.xlarge" "c8g.xlarge"; do
  safe=$(echo "$inst"|tr '.' '-')
  out=$(cat "$fr" | sed "s/INSTANCE_SAFE/${safe}/g" | sed "s/INSTANCE_TYPE/${inst}/g" \
        | sed "s/RUN_NUMBER/1/g" | sed "s/KAFKA_VERSION/3.9.1/g" | sed "s/BASELINE_MB/285.5/g")
  echo "$out" | python3 -c "import yaml,sys;list(yaml.safe_load_all(sys.stdin))" 2>/dev/null \
    && ok "치환 YAML ($inst)" || no "치환 YAML ($inst)"
  if echo "$out" | grep -Eq "INSTANCE_SAFE|INSTANCE_TYPE|RUN_NUMBER|KAFKA_VERSION|BASELINE_MB"; then
    no "placeholder 잔류 ($inst)"; else ok "placeholder 잔류 0 ($inst)"; fi
  if kubectl version --client >/dev/null 2>&1 && kubectl get ns benchmark >/dev/null 2>&1; then
    echo "$out" | kubectl apply --dry-run=client -f - >/dev/null 2>&1 && ok "dry-run ($inst)" || no "dry-run ($inst)"
  fi
done
grep -q "podAntiAffinity" "$fr" && ok "podAntiAffinity" || no "podAntiAffinity"
grep -q "podAffinity" "$fr" && ok "podAffinity (같은 AZ 배치)" || no "podAffinity"
grep -q "backoffLimit: 0" "$fr" && ok "backoffLimit 0" || no "backoffLimit"
grep -q "SATURATION_REACHED" "$fr" && ok "포화점 정지조건 로그 라벨 존재" || no "SATURATION_REACHED 누락"
grep -q "0.995" "$fr" && ok "정지조건 임계값(99.5%) 존재" || no "정지조건 임계값 누락"
grep -q "DEPLETION_DURATION_S" "$fr" && ok "버스트크레딧 고갈 단계 존재" || no "크레딧 고갈 단계 누락"

echo "== Task 3e: 램프업 실행 스크립트 =="
srp="$BASE/scripts/generate-kafka-ramp-benchmark.sh"
bash -n "$srp" 2>/dev/null && ok "bash -n" || no "bash -n"
grep -q '| sed ' "$srp" && ok "chained-pipe sed 사용" || no "chained-pipe sed"
grep -qE '^\s*sed -e .*-e ' "$srp" && no "multi -e sed 사용 (금지 패턴)" || ok "multi -e sed 없음"
grep -q "results/kafka-ramp" "$srp" && ok "결과 디렉터리 분리 (results/kafka-ramp)" || no "결과 디렉터리"
grep -q 'kubectl(){ command kubectl --context mall-apne2-mgmt' "$srp" && ok "kubectl context 고정" || no "kubectl context 고정 누락"
grep -q "results/kafka-max" "$srp" && ok "Phase 2(kafka-max) 데이터를 기준점으로 참조" || no "Phase 2 참조 누락"

echo "== Task 3f: pod 조회 재시도 + 거짓양성 방지 (세 스크립트 공통) =="
for s in "$BASE/scripts/generate-kafka-benchmark.sh" "$BASE/scripts/generate-kafka-max-benchmark.sh" "$BASE/scripts/generate-kafka-ramp-benchmark.sh"; do
  n=$(basename "$s")
  grep -qE '^\s*find_pod\(\)\{' "$s" && ok "find_pod 재시도 헬퍼 존재 ($n)" || no "find_pod 헬퍼 누락 ($n)"
  grep -q '\[ -s "\$lf" \]' "$s" && ok "로그 파일 실제 내용 확인 후에만 성공 처리 ($n)" || no "빈 로그 거짓양성 방지 누락 ($n)"
done

echo "== Task 4: 리포트 파서 =="
p="$BASE/scripts/generate-kafka-report.py"
python3 -m py_compile "$p" 2>/dev/null && ok "py_compile" || no "py_compile"
python3 "$p" >/dev/null 2>&1 && ok "빈/부분 입력 graceful 실행" || no "실행 실패"

echo "== Task 5: 리포트 스캐폴드 =="
h="$BASE/results/kafka/report-charts.html"
grep -q 'cdn.jsdelivr.net/npm/chart.js' "$h" && ok "Chart.js CDN" || no "Chart.js 미참조"
sk=$(grep -n '^let sortKey' "$h" | head -1 | cut -d: -f1)
mn=$(grep -n '^main();' "$h" | head -1 | cut -d: -f1)
if [ -n "$sk" ] && [ -n "$mn" ] && [ "$sk" -lt "$mn" ]; then ok "module-state가 실행 전 선언(TDZ 안전)"; else no "TDZ 위험"; fi
grep -q "네트워크" "$h" && ok "네트워크 교란 명시" || no "네트워크 교란 미명시"
grep -q 'id="ramp"' "$h" && ok "램프업(Phase 3) 섹션 존재" || no "램프업 섹션 누락"
grep -q "renderRampSection" "$h" && ok "renderRampSection 함수 존재" || no "renderRampSection 누락"
python3 -c "import html.parser,sys
class P(html.parser.HTMLParser):
    pass
P().feed(open('$h').read())" 2>/dev/null && ok "HTML 파싱" || no "HTML 파싱"

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
