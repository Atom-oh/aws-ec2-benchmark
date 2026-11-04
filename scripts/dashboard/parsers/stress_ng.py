"""stress-ng는 원시 재파싱하지 않는다(51개 그대로). legacy/stress-ng.json을 표준 봉투로
재구성. 레거시 필드 `switch`는 JS 예약어 인상을 피하려 `ctx_switch`로 개명(데이터 스키마
설계 §3 결정).
"""
import json
import math
import re

import analysis
from common import PRICE, RESULTS_DIR, canonical_instances

from common import LEGACY_DIR

SRC = LEGACY_DIR / "stress-ng.json"


def build():
    rows = json.loads(SRC.read_text())
    instances = {
        r["instance"]: {
            "matrix": r["matrix"], "float": r["float"], "int": r["int"],
            "memcpy": r["memcpy"], "cache": r["cache"], "ctx_switch": r["switch"],
            "branch": r["branch"], "total": r["total"],
        }
        for r in rows
    }
    names7 = ["matrix", "float", "int", "memcpy", "cache", "ctx_switch", "branch"]  # 로그의 스트레서 출력 순서
    row0 = re.compile(r"stress-ng: info:\s+\[\d+\]\s+([a-z]+)\s+\d+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)\s+[\d.]+")
    for name in canonical_instances():
        if name in instances or not (RESULTS_DIR / "stress-ng" / name).is_dir():
            continue
        per = []
        for lp in sorted((RESULTS_DIR / "stress-ng" / name).glob("run*.log")):
            vals = [float(v) for _, v in row0.findall(lp.read_text(errors="replace"))]
            if len(vals) == 7:
                per.append(vals)
        if per:
            instances[name] = {k: round(sum(r[i] for r in per) / len(per)) for i, k in enumerate(names7)}
            instances[name]["total"] = None
    rep = {"geomean": {}}
    row = re.compile(r"stress-ng: info:\s+\[\d+\]\s+([a-z]+)\s+\d+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)\s+[\d.]+")
    for name in instances:
        for lp in sorted((RESULTS_DIR / "stress-ng" / name).glob("run*.log")):
            vals = [float(v) for _, v in row.findall(lp.read_text(errors="replace"))]
            if len(vals) == 7 and all(v > 0 for v in vals):
                rep["geomean"].setdefault(name, []).append(math.exp(sum(math.log(v) for v in vals) / 7))
    summaries, blocks = analysis.report(rep, {
        "geomean": {"label": "stress-ng 종합 지수 (7종 기하평균)", "unit": "bogo ops/s", "direction": "max"}}, PRICE)
    for _n, _r in summaries.items():
        instances[_n]["r"] = _r
    return {
        "benchmark": "stress-ng",
        "coverage": len(instances),
        "headline": {"field": "total", "direction": "max", "label": "종합 점수", "unit": "score"},
        "notes": {"coverage_caveat": "51/54 — 신규 3개 인스턴스는 원시 로그 없음"},
        "instances": instances,
        "analysis": blocks,
    }
