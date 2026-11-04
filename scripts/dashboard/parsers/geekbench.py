"""geekbench는 원시 재파싱하지 않는다(51개 그대로, 커버리지 이득 0 — 신규 3개 인스턴스의
원시 로그 자체가 없음). legacy/geekbench.json(extract_legacy.py 산출물)을 표준 봉투로
재구성만 한다.
"""
import json
import analysis
from common import PRICE

from common import LEGACY_DIR

SRC = LEGACY_DIR / "geekbench.json"


def build():
    rows = json.loads(SRC.read_text())
    instances = {r["instance"]: {"single": r["single"], "multi": r["multi"]} for r in rows}
    # 회차 값은 로컬에 없다: 로그의 SINGLE/MULTI_CORE_SCORE는 0(Preview 빌드가 Browser에만 업로드).
    # 레거시 평균 1개를 n=1로 넣으므로 변동계수는 0이고 신뢰도 경고는 산출되지 않는다.
    summaries, blocks = analysis.report(
        {"multi": {n: [v["multi"]] for n, v in instances.items()}, "single": {n: [v["single"]] for n, v in instances.items()}},
        {"multi": {"label": "Geekbench 멀티코어", "unit": "점", "direction": "max"},
         "single": {"label": "Geekbench 단일 코어", "unit": "점", "direction": "max"}}, PRICE)
    for _n, _r in summaries.items():
        instances[_n]["r"] = _r
    return {
        "benchmark": "geekbench",
        "coverage": len(instances),
        "headline": {"field": "multi", "direction": "max", "label": "Multi-core Score", "unit": "score"},
        "notes": {"coverage_caveat": "51/54 — 신규 3개 인스턴스(c8gn/r8gd/m8i-flex)는 원시 로그 없음"},
        "instances": instances,
        "analysis": blocks,
    }
