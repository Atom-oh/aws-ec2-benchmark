#!/usr/bin/env python3
"""통합 대시보드 데이터 파이프라인 공통 유틸.

instances.json 빌더 + 벤치마크별 파서가 공유하는 인스턴스 분류/가격 로직.
gen_family()는 scripts/generate-kafka-report.py, scripts/generate-clickhouse-report.py와
동일 규칙(검증됨: 54개 인스턴스 전수 확인) — 그대로 포팅, 재작성 아님.
"""
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent.parent
RESULTS_DIR = BASE_DIR / "results"
LEGACY_DIR = BASE_DIR / "legacy"
SITE_DATA_DIR = BASE_DIR / "site" / "data"
INSTANCE_FILE = BASE_DIR / "config" / "instances-4vcpu.txt"
REPORTS_DIR = BASE_DIR / "reports"

# On-Demand 시간당 가격 (USD, ap-northeast-2) — scripts/generate-kafka-report.py의 PRICE dict과
# 동일(54개 완비, aws pricing get-products 소스). 이 파일이 canonical — 다른 스크립트는 재사용.
PRICE = {
    "c5.xlarge": 0.192, "c5a.xlarge": 0.172, "c5d.xlarge": 0.220, "c5n.xlarge": 0.244,
    "c6g.xlarge": 0.154, "c6gd.xlarge": 0.176, "c6gn.xlarge": 0.195, "c6i.xlarge": 0.192,
    "c6id.xlarge": 0.231, "c6in.xlarge": 0.256, "c7g.xlarge": 0.163, "c7gd.xlarge": 0.208,
    "c7i-flex.xlarge": 0.192, "c7i.xlarge": 0.202, "c8g.xlarge": 0.180, "c9g.xlarge": 0.19568, "c8gn.xlarge": 0.268,
    "c8i-flex.xlarge": 0.201, "r8gd.xlarge": 0.353, "m8i-flex.xlarge": 0.247,
    "c8i.xlarge": 0.212, "m5.xlarge": 0.236, "m5a.xlarge": 0.212, "m5ad.xlarge": 0.254,
    "m5d.xlarge": 0.278, "m5zn.xlarge": 0.406, "m6g.xlarge": 0.188, "m6gd.xlarge": 0.222,
    "m6i.xlarge": 0.236, "m6id.xlarge": 0.292, "m6idn.xlarge": 0.386, "m6in.xlarge": 0.337,
    "m7g.xlarge": 0.201, "m7gd.xlarge": 0.263, "m7i-flex.xlarge": 0.235, "m7i.xlarge": 0.248,
    "m8g.xlarge": 0.221, "m8i.xlarge": 0.260, "r5.xlarge": 0.304, "r5a.xlarge": 0.272,
    "r5ad.xlarge": 0.316, "r5b.xlarge": 0.356, "r5d.xlarge": 0.346, "r5dn.xlarge": 0.398,
    "r5n.xlarge": 0.356, "r6g.xlarge": 0.244, "r6gd.xlarge": 0.277, "r6i.xlarge": 0.304,
    "r6id.xlarge": 0.363, "r7g.xlarge": 0.258, "r7gd.xlarge": 0.327, "r7i.xlarge": 0.319,
    "r8g.xlarge": 0.284, "r8i-flex.xlarge": 0.318, "r8i.xlarge": 0.335,
}

# EC2 세대(6/7/8/9) -> Graviton 칩 세대(2/3/4/5). 예: c8g.xlarge는 EC2 8세대이자 Graviton4.
# c9g.xlarge(Graviton5)는 2026-11 추가 — 가격은 aws pricing get-products(ap-northeast-2 Linux OD) 조회값.
GRAVITON_GEN_NUM = {6: 2, 7: 3, 8: 4, 9: 5}


def load_instance_meta():
    """instances-4vcpu.txt: 'name<TAB>arch<TAB>mem_mb' -> {name: {arch(x86_64/arm64), mem_mb}}."""
    meta = {}
    for line in INSTANCE_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 3:
            meta[parts[0]] = {"raw_arch": parts[1], "mem_mb": int(parts[2])}
    return meta


def gen_family(instance):
    """세대/패밀리/아키텍처 분류 — kafka/clickhouse 리포트 스크립트와 동일 규칙."""
    fam = instance[0].upper() if instance else "?"
    prefix = instance.split(".")[0]
    m = re.match(r"^([cmr])(\d+)([a-z\-]*)", prefix)
    gen = int(m.group(2)) if m else None
    suffix = m.group(3) if m else ""
    if suffix.startswith("g"):
        arch = "graviton"
        graviton_gen = GRAVITON_GEN_NUM.get(gen)
    elif suffix.startswith("a"):
        arch = "amd"
        graviton_gen = None
    else:
        arch = "intel"
        graviton_gen = None
    flex = "-flex" in instance
    return {"arch": arch, "gen": gen, "family": fam, "graviton_gen": graviton_gen, "flex": flex}


HARDWARE_FILE = BASE_DIR / "config" / "hardware-4vcpu.json"


def build_instances():
    """instances.json 페이로드 생성: {name: {arch, gen, family, mem_mb, price, flex, graviton_gen, hw}}.

    hw = config/hardware-4vcpu.json(fetch_hardware.py가 EC2/Pricing API로 생성)의 사양 — 없으면 생략.
    """
    import json
    hardware = json.loads(HARDWARE_FILE.read_text())["instances"] if HARDWARE_FILE.exists() else {}
    meta = load_instance_meta()
    out = {}
    for name, info in sorted(meta.items()):
        cls = gen_family(name)
        price = PRICE.get(name)
        if price is None:
            raise ValueError(f"PRICE missing for {name} — canonical dict is out of sync")
        out[name] = {
            "arch": cls["arch"],
            "gen": cls["gen"],
            "family": cls["family"],
            "mem_mb": info["mem_mb"],
            "price": round(price, 4),
            "flex": cls["flex"],
            "graviton_gen": cls["graviton_gen"],
        }
        if name in hardware:
            out[name]["hw"] = hardware[name]
    return out


def canonical_instances():
    """정본 54개 인스턴스명 리스트 (config/instances-4vcpu.txt 순서 보존 X, 정렬됨)."""
    return sorted(load_instance_meta().keys())


def mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


# ---- wrk 출력 파싱 (web/proxy 파서 공용) ----
_WRK_UNIT_MS = {"us": 0.001, "ms": 1.0, "s": 1000.0, "m": 60000.0}


def wrk_time_ms(value, unit):
    """wrk 지연 표기('585.27us', '1.83ms', '2.01s')를 ms float로 정규화."""
    return float(value) * _WRK_UNIT_MS[unit]


def parse_wrk_block(text):
    """wrk 단일 실행 출력 -> {rps, lat_avg_ms, p50_ms, p90_ms, p99_ms, requests, errors}.

    errors = Socket errors(connect+read+write+timeout) + Non-2xx/3xx 응답 수. --latency 없이 돌린
    블록은 분위수가 None. Requests/sec 줄이 없으면(실행 실패) None 반환.
    """
    rps = re.search(r"Requests/sec:\s+([\d.]+)", text)
    if not rps:
        return None
    out = {"rps": float(rps.group(1))}
    lat = re.search(r"Latency\s+([\d.]+)(us|ms|s|m)\b", text)
    out["lat_avg_ms"] = wrk_time_ms(*lat.groups()) if lat else None
    for pct in ("50", "90", "99"):
        m = re.search(rf"^\s+{pct}%\s+([\d.]+)(us|ms|s|m)\b", text, re.M)
        out[f"p{pct}_ms"] = wrk_time_ms(*m.groups()) if m else None
    req = re.search(r"(\d+) requests in", text)
    out["requests"] = int(req.group(1)) if req else None
    errors = 0
    sock = re.search(r"Socket errors: connect (\d+), read (\d+), write (\d+), timeout (\d+)", text)
    if sock:
        errors += sum(int(x) for x in sock.groups())
    non2xx = re.search(r"Non-2xx or 3xx responses:\s+(\d+)", text)
    if non2xx:
        errors += int(non2xx.group(1))
    out["errors"] = errors
    return out


def geomean(values):
    """양수 값들의 기하평균(하나라도 None/<=0이면 None) — 스택/프록시별 처리량을 한 headline으로 합칠 때 사용."""
    import math
    if not values or any(v is None or v <= 0 for v in values):
        return None
    return round(math.exp(sum(math.log(v) for v in values) / len(values)), 4)
