"""passmark는 원시 재파싱하지 않는다(51개 그대로). 정본은 legacy/passmark.json의
HTML 51행 테이블 파싱 결과(extract_legacy.py가 이미 `priceData` 배열을 버리고 테이블을
파싱함 — 콘텐츠 명세 §3에서 결정한 "정본=HTML 테이블"). int/float/encryption/compression은
detailData(Top-15만 커버)에서 온 값으로, cpu_mark 비율 추정치라는 캐비어트를 notes에 명시.
"""
import json
import re

import analysis
from common import PRICE, RESULTS_DIR, canonical_instances

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
    # 레거시 JSON(51개)에 없는 신규 인스턴스(c8gn/r8gd/m8i-flex 이후, c9g 등)는 원시 로그로 엔트리를 만든다
    for name in canonical_instances():
        if name in instances or not (RESULTS_DIR / "passmark" / name).is_dir():
            continue
        cm, sg = [], []
        for lp in sorted((RESULTS_DIR / "passmark" / name).glob("run*.log")):
            t = lp.read_text(errors="replace")
            a, b = re.search(r"SUMM_CPU:\s*([\d.]+)", t), re.search(r"CPU_SINGLETHREAD:\s*([\d.]+)", t)
            if a and float(a.group(1)) > 0:
                cm.append(float(a.group(1)))
            if b and float(b.group(1)) > 0:
                sg.append(float(b.group(1)))
        if cm:
            instances[name] = {"cpu_mark": round(sum(cm) / len(cm), 1), "single": round(sum(sg) / len(sg), 1) if sg else None,
                               "int": None, "float": None, "encryption": None, "compression": None}
    # 세부 점수는 원시 로그(PerformanceTest 결과의 CPU_* 항목)에서 회차 평균 — 레거시 JSON은 Top-15만 값이 있고 일부는
    # cpu_mark 비율 추정이었음(2026-11-12 원시 로그로 교체, 51→전 인스턴스). cpu_mark/single은 validate.py가 레거시와 대조.
    SUBS = {"int": "CPU_INTEGER_MATH", "float": "CPU_FLOATINGPOINT_MATH", "encryption": "CPU_ENCRYPTION", "compression": "CPU_COMPRESSION"}
    for name in instances:
        acc = {k: [] for k in SUBS}
        for lp in sorted((RESULTS_DIR / "passmark" / name).glob("run*.log")):
            t = lp.read_text(errors="replace")
            if not re.search(r"SUMM_CPU:\s*[1-9]", t):
                continue
            for k, lab in SUBS.items():
                m = re.search(rf"^\s+{lab}:\s*([\d.]+)", t, re.M)
                if m:
                    acc[k].append(float(m.group(1)))
        for k, v in acc.items():
            if v:
                instances[name][k] = round(sum(v) / len(v), 1)
    rep = {"cpu_mark": {}, "single": {}}
    for name in instances:
        for lp in sorted((RESULTS_DIR / "passmark" / name).glob("run*.log")):
            t = lp.read_text(errors="replace")
            for key, pat in (("cpu_mark", r"SUMM_CPU:\s*([\d.]+)"), ("single", r"CPU_SINGLETHREAD:\s*([\d.]+)")):
                m = re.search(pat, t)
                if m and float(m.group(1)) > 0:
                    rep[key].setdefault(name, []).append(float(m.group(1)))
    # 세부 항목: Graviton/Intel 격차가 어디서 나오는지(정수 연산 vs 암호화·확장 명령어). arm64 빌드는
    # AVX/AVX-512 항목이 0점으로 기록된다 — x86 전용 경로라 ARM 대응 항목(SVE 등)이 없다.
    sub_keys = ("CPU_INTEGER_MATH", "CPU_FLOATINGPOINT_MATH", "CPU_ENCRYPTION", "CPU_COMPRESSION", "CPU_avx512", "CPU_SINGLETHREAD")
    subscores = {}
    for name in ("c8g.xlarge", "c8i.xlarge", "c7g.xlarge", "c7i.xlarge"):
        vals = {k: [] for k in sub_keys}
        for lp in sorted((RESULTS_DIR / "passmark" / name).glob("run*.log")):
            t = lp.read_text(errors="replace")
            if not re.search(r"SUMM_CPU:\s*[1-9]", t):
                continue
            for k in sub_keys:
                m = re.search(rf"^\s+{k}:\s*([\d.]+)", t, re.M)
                if m:
                    vals[k].append(float(m.group(1)))
        subscores[name] = {k: analysis.summarize(v)["value"] if v else None for k, v in vals.items()}
    summaries, blocks = analysis.report(rep, {
        "cpu_mark": {"label": "PassMark CPU Mark", "unit": "점", "direction": "max"},
        "single": {"label": "PassMark 단일 스레드", "unit": "점", "direction": "max"}}, PRICE)
    for _n, _r in summaries.items():
        instances[_n]["r"] = _r
    return {
        "benchmark": "passmark",
        "coverage": len(instances),
        "headline": {"field": "cpu_mark", "direction": "max", "label": "CPU Mark", "unit": "score",
                     "caveat": "x86 전용 확장 명령어(AVX/AVX-512) 항목이 arm64에서 0점이고 압축·암호화 경로가 x86에 유리 — 아키텍처 비교에는 부적합(PassMark 탭)"},
        "notes": {
            "coverage_caveat": "레거시 51개 + 원시 로그로 보충한 인스턴스(c9g, 2026-11 백필 c8gn/m8i-flex/r8gd)",
            "subscores_source": "int/float/encryption/compression은 원시 로그(CPU_INTEGER_MATH 등) 회차 평균 — 레거시 Top-15 추정값을 대체(2026-11-12)",
        },
        "instances": instances,
        "analysis": blocks,
        "subscores": subscores,
    }
