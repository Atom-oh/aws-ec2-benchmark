#!/bin/bash
# Geekbench 결과 수집 스크립트
# Rate limiting: 2초 간격으로 요청

cd /home/ec2-user/benchmark
RESULTS_DIR="results/geekbench"
OUTPUT_FILE="results/geekbench/scores.csv"
SLEEP_INTERVAL=2

# CSV 헤더 생성
echo "instance,run,url,single_core,multi_core,model" > "$OUTPUT_FILE"

total=0
success=0
failed=0

# 모든 인스턴스 디렉토리 순회
for inst_dir in "$RESULTS_DIR"/*/; do
    instance=$(basename "$inst_dir")
    [[ "$instance" == "scores.csv" ]] && continue

    # 각 run 파일 처리
    for log_file in "$inst_dir"run*.log; do
        [[ ! -f "$log_file" ]] && continue

        run=$(basename "$log_file" .log | sed 's/run//')

        # URL 추출
        url=$(grep -oE "https://browser.geekbench.com/v6/cpu/[0-9]+" "$log_file" | head -1)

        if [[ -z "$url" ]]; then
            echo "[SKIP] $instance run$run - No URL found"
            continue
        fi

        total=$((total + 1))

        echo -n "[$(date '+%H:%M:%S')] $instance run$run ... "

        # HTML 가져오기
        html=$(curl -s --max-time 30 "$url")

        if [[ -z "$html" ]]; then
            echo "FAILED (no response)"
            failed=$((failed + 1))
            sleep $SLEEP_INTERVAL
            continue
        fi

        # 점수 추출 (score 클래스에서)
        scores=$(echo "$html" | grep -oE "<div class='score'>[0-9]+</div>" | grep -oE "[0-9]+" | head -2)
        single_core=$(echo "$scores" | head -1)
        multi_core=$(echo "$scores" | tail -1)

        # 모델명 추출
        model=$(echo "$html" | grep -oE "Model.*Amazon EC2 [^<]+" | sed 's/.*Amazon EC2 //' | head -1)

        if [[ -n "$single_core" && -n "$multi_core" ]]; then
            echo "OK (SC:$single_core, MC:$multi_core)"
            echo "$instance,$run,$url,$single_core,$multi_core,$model" >> "$OUTPUT_FILE"
            success=$((success + 1))
        else
            echo "FAILED (parse error)"
            failed=$((failed + 1))
        fi

        # Rate limiting
        sleep $SLEEP_INTERVAL
    done
done

echo ""
echo "=== 완료 ==="
echo "총: $total, 성공: $success, 실패: $failed"
echo "결과 파일: $OUTPUT_FILE"
