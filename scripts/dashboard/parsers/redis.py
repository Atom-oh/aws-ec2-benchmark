"""Redis 원시 로그 파서.

파싱 로직은 scripts/parse_redis_for_report.py를 그대로 포팅(경로만 canonical RESULTS_DIR로
교체) — Test 5(SET)/Test 6(GET) latency test의 CSV 요약 줄에서 rps/avg_latency/p99_latency를 읽는다.
GET/Mixed 효율 차트는 레거시 리포트에서 조작값(SET×1.1/×1.05)이었던 문제를 여기서 근본
해결: get_rps는 이 파서가 직접 파싱한 실측값이며 site 스키마에는 애초에 파생 효율 필드를
저장하지 않으므로(클라이언트 계산) 조작값이 재생산될 여지가 없다.
"""
import re

from common import RESULTS_DIR, canonical_instances, mean

SET_PATTERN = re.compile(
    r'--- Test 5: Latency Test SET.*?\n"test","rps".*?\n"SET","([\d.]+)","([\d.]+)","[\d.]+","[\d.]+","[\d.]+","([\d.]+)"',
    re.S,
)
GET_PATTERN = re.compile(
    r'--- Test 6: Latency Test GET.*?\n"test","rps".*?\n"GET","([\d.]+)","([\d.]+)","[\d.]+","[\d.]+","[\d.]+","([\d.]+)"',
    re.S,
)


def parse_log(path):
    content = path.read_text(errors="replace")
    out = {"set_rps": None, "get_rps": None, "set_lat_ms": None, "get_lat_ms": None, "set_p99_ms": None, "get_p99_ms": None}
    m = SET_PATTERN.search(content)
    if m:
        out["set_rps"], out["set_lat_ms"], out["set_p99_ms"] = float(m.group(1)), float(m.group(2)), float(m.group(3))
    m = GET_PATTERN.search(content)
    if m:
        out["get_rps"], out["get_lat_ms"], out["get_p99_ms"] = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return out


def build():
    base = RESULTS_DIR / "redis"
    instances = {}
    for name in canonical_instances():
        inst_dir = base / name
        if not inst_dir.is_dir():
            continue
        runs = {k: [] for k in ["set_rps", "get_rps", "set_lat_ms", "get_lat_ms", "set_p99_ms", "get_p99_ms"]}
        for lp in sorted(inst_dir.glob("run*.log")):
            r = parse_log(lp)
            for k, v in r.items():
                if v is not None:
                    runs[k].append(v)
        if not runs["set_rps"]:
            continue
        instances[name] = {
            "set_rps": mean(runs["set_rps"]), "get_rps": mean(runs["get_rps"]),
            "set_lat_ms": mean(runs["set_lat_ms"]), "get_lat_ms": mean(runs["get_lat_ms"]),
            "set_p99_ms": mean(runs["set_p99_ms"]), "get_p99_ms": mean(runs["get_p99_ms"]),
            "set_rps_all": [round(v, 2) for v in runs["set_rps"]],
            "get_rps_all": [round(v, 2) for v in runs["get_rps"]],
        }

    coverage = sum(1 for v in instances.values() if v["set_rps"] is not None)
    return {
        "benchmark": "redis",
        "coverage": coverage,
        "headline": {"field": "set_rps", "direction": "max", "label": "SET Throughput", "unit": "ops/s"},
        "notes": {
            "method": "redis-benchmark/memtier SET/GET 100M requests, Latency Test(1M) 5회 평균. set_rps_all/get_rps_all은 5회 원시값(인스턴스 상세 모달의 CV 계산용).",
        },
        "instances": instances,
    }
