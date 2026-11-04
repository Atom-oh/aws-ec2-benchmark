"""clickhouse는 재파싱하지 않는다 — 기존 generate-clickhouse-report.py가 만든
results/clickhouse/data.json을 그대로 읽어 공통 봉투 필드(headline/coverage)만 추가한다.
스키마(per_query_ms, queries 등)는 절대 변경하지 않는다 — 상위 설계 §3.5 "재사용 우선" 정책.
"""
import importlib.util
import json

import analysis
from common import PRICE

from common import BASE_DIR

SRC = BASE_DIR / "results" / "clickhouse" / "data.json"


def _load_script(fname):
    """하이픈 이름의 리포트 스크립트(scripts/<fname>)를 모듈로 로드 — main()은 실행하지 않는다."""
    spec = importlib.util.spec_from_file_location(fname.replace("-", "_")[:-3], BASE_DIR / "scripts" / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build():
    data = json.loads(SRC.read_text())
    data["benchmark"] = "clickhouse"
    data["coverage"] = len(data["instances"])
    data["headline"] = {
        "field": "hot_total_s", "direction": "min",
        "label": "Hot Query Total", "unit": "s",
    }
    # 회차(세트) 값: 세트마다 43쿼리 hot(min(hot1,hot2)) 합계 — 쿼리 하나라도 실패한 세트는 제외.
    # 파싱은 scripts/generate-clickhouse-report.py parse_log를 그대로 불러 쓴다(재작성 아님).
    gen = _load_script("generate-clickhouse-report.py")
    rep = {"hot_total_s": {}}
    for name in data["instances"]:
        for lp in sorted((BASE_DIR / "results" / "clickhouse" / name).glob("set*.log")):
            if lp.stat().st_size == 0:
                continue
            r = gen.parse_log(lp)
            if r["failed"] == 0 and len(r["queries"]) == 43:
                rep["hot_total_s"].setdefault(name, []).append(sum(v[0] for v in r["queries"].values()) / 1000)
    summaries, data["analysis"] = analysis.report(rep, {
        "hot_total_s": {"label": "ClickBench 43쿼리 hot 합계", "unit": "s", "direction": "min", "memory_sensitive": True}}, PRICE)
    for _n, _r in summaries.items():
        data["instances"][_n]["r"] = _r
    return data
