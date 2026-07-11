"""clickhouse는 재파싱하지 않는다 — 기존 generate-clickhouse-report.py가 만든
results/clickhouse/data.json을 그대로 읽어 공통 봉투 필드(headline/coverage)만 추가한다.
스키마(per_query_ms, queries 등)는 절대 변경하지 않는다 — 상위 설계 §3.5 "재사용 우선" 정책.
"""
import json

from common import BASE_DIR

SRC = BASE_DIR / "results" / "clickhouse" / "data.json"


def build():
    data = json.loads(SRC.read_text())
    data["benchmark"] = "clickhouse"
    data["coverage"] = len(data["instances"])
    data["headline"] = {
        "field": "hot_total_s", "direction": "min",
        "label": "Hot Query Total", "unit": "s",
    }
    return data
