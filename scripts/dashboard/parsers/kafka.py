"""kafka는 재파싱하지 않는다 — 기존 generate-kafka-report.py가 만든 results/kafka/data.json을
그대로 읽어 공통 봉투 필드(headline/coverage)만 추가한다. 스키마(중첩 max/ramp 등)는 절대
변경하지 않는다 — 상위 설계 §3.5 "재사용 우선" 정책.
"""
import importlib.util
import json

import analysis
from common import PRICE

from common import BASE_DIR

SRC = BASE_DIR / "results" / "kafka" / "data.json"


def _load_script(fname):
    """하이픈 이름의 리포트 스크립트(scripts/<fname>)를 모듈로 로드 — main()은 실행하지 않는다."""
    spec = importlib.util.spec_from_file_location(fname.replace("-", "_")[:-3], BASE_DIR / "scripts" / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build():
    data = json.loads(SRC.read_text())
    data["benchmark"] = "kafka"
    data["coverage"] = len(data["instances"])
    data["headline"] = {
        "field": "produce_mb_per_sec", "direction": "max",
        "label": "Produce Throughput (Baseline)", "unit": "MB/s",
    }
    # 회차 값: 베이스라인(results/kafka/runN.log)과 포화 8-way 무압축(results/kafka-max/uncompressed-runN.log)의
    # produce MB/s. 파싱은 scripts/generate-kafka-report.py parse_log/parse_max_log를 그대로 불러 쓴다.
    gen = _load_script("generate-kafka-report.py")
    rep = {"max_produce_mb": {}, "produce_mb": {}}  # 첫 키 = 기본 지표(headline.analysis_key)
    for name in data["instances"]:
        for lp in sorted((BASE_DIR / "results" / "kafka" / name).glob("run*.log")):
            r, failed = gen.parse_log(lp)
            if r.get("produce_mb_per_sec"):
                rep["produce_mb"].setdefault(name, []).append(r["produce_mb_per_sec"])
        for lp in sorted((BASE_DIR / "results" / "kafka-max" / name).glob("uncompressed-run*.log")):
            r, failed = gen.parse_max_log(lp)
            if r.get("produce_mb_per_sec"):
                rep["max_produce_mb"].setdefault(name, []).append(r["produce_mb_per_sec"])
    summaries, data["analysis"] = analysis.report(rep, {
        "produce_mb": {"label": "Kafka produce (베이스라인, 단일 producer)", "unit": "MB/s", "direction": "max", "memory_sensitive": True,
                       "known_suspects": {"names": [f"{n}.xlarge" for n in ("c7g", "c7i", "c8i", "m7i-flex", "m7gd", "m8i", "m8i-flex", "r7gd", "r8i", "r8i-flex", "r8gd")],
                                          "reason": "베이스라인 고지연(5/5회 70~150ms) 재현 인스턴스 — 원인 미확정(CLAUDE.md Kafka 알려진 이슈)"}},
        "max_produce_mb": {"label": "Kafka produce (포화, 8-way 무압축)", "unit": "MB/s", "direction": "max", "memory_sensitive": True}}, PRICE)
    for _n, _r in summaries.items():
        data["instances"][_n]["r"] = _r
    return data
