"""passmark는 원시 재파싱하지 않는다(51개 그대로). 정본은 legacy/passmark.json의
HTML 51행 테이블 파싱 결과(extract_legacy.py가 이미 `priceData` 배열을 버리고 테이블을
파싱함 — 콘텐츠 명세 §3에서 결정한 "정본=HTML 테이블"). int/float/encryption/compression은
detailData(Top-15만 커버)에서 온 값으로, cpu_mark 비율 추정치라는 캐비어트를 notes에 명시.
"""
import json

from common import LEGACY_DIR

SRC = LEGACY_DIR / "passmark.json"


def build():
    rows = json.loads(SRC.read_text())
    instances = {}
    for r in rows:
        instances[r["instance"]] = {
            "cpu_mark": r["cpu_mark"], "single": r["single"],
            "int": r.get("int"), "float": r.get("float"),
            "encryption": r.get("encryption"), "compression": r.get("compression"),
        }
    return {
        "benchmark": "passmark",
        "coverage": len(instances),
        "headline": {"field": "cpu_mark", "direction": "max", "label": "CPU Mark", "unit": "score"},
        "notes": {
            "coverage_caveat": "51/54 — 신규 3개 인스턴스는 원시 로그 없음",
            "estimated": "int/float/encryption/compression은 Top-15만 커버하는 상세테스트 결과(cpu_mark 비율 추정 섞임) — 51개 전체에 값이 있는 것은 cpu_mark/single뿐",
        },
        "instances": instances,
    }
