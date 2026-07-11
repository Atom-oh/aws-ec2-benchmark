"""stress-ng는 원시 재파싱하지 않는다(51개 그대로). legacy/stress-ng.json을 표준 봉투로
재구성. 레거시 필드 `switch`는 JS 예약어 인상을 피하려 `ctx_switch`로 개명(데이터 스키마
설계 §3 결정).
"""
import json

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
    return {
        "benchmark": "stress-ng",
        "coverage": len(instances),
        "headline": {"field": "total", "direction": "max", "label": "종합 점수", "unit": "score"},
        "notes": {"coverage_caveat": "51/54 — 신규 3개 인스턴스는 원시 로그 없음"},
        "instances": instances,
    }
