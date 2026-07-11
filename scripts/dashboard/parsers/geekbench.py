"""geekbench는 원시 재파싱하지 않는다(51개 그대로, 커버리지 이득 0 — 신규 3개 인스턴스의
원시 로그 자체가 없음). legacy/geekbench.json(extract_legacy.py 산출물)을 표준 봉투로
재구성만 한다.
"""
import json

from common import LEGACY_DIR

SRC = LEGACY_DIR / "geekbench.json"


def build():
    rows = json.loads(SRC.read_text())
    instances = {r["instance"]: {"single": r["single"], "multi": r["multi"]} for r in rows}
    return {
        "benchmark": "geekbench",
        "coverage": len(instances),
        "headline": {"field": "multi", "direction": "max", "label": "Multi-core Score", "unit": "score"},
        "notes": {"coverage_caveat": "51/54 — 신규 3개 인스턴스(c8gn/r8gd/m8i-flex)는 원시 로그 없음"},
        "instances": instances,
    }
