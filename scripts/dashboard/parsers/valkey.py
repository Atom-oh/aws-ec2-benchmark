"""Valkey 원시 로그 파서 (원격 client→server 토폴로지, io-threads 없음).

parsers/redis.py를 그대로 포팅(경로만 RESULTS_DIR/"valkey-remote"로 교체) — valkey-benchmark의
로그 포맷이 redis-benchmark와 완전히 동일하므로(Redis 포크, 동일 CLI/플래그) 정규식 무수정
재사용. Redis와 동일한 이유로 localhost 방식을 폐기하고 원격 토폴로지로 재측정함(자세한 이유는
parsers/redis.py docstring 참고). throughput은 Test 1/2(SET/GET 각 2000만 건)의 진행률 로그
마지막 "overall:" 값을 쓰고, latency percentile은 Test 5/6(--csv, 1M 요청 단발)에서 파싱.
원시 로그: results/valkey-remote/.
"""
import re

from common import RESULTS_DIR, canonical_instances, mean

TEST1_SET_PATTERN = re.compile(r'--- Test 1:.*?--- Test 2:', re.S)
TEST2_GET_PATTERN = re.compile(r'--- Test 2:.*?--- Test 5:', re.S)
OVERALL_RPS_PATTERN = re.compile(r'overall: ([\d.]+)\) avg_msec')

SET_LATENCY_PATTERN = re.compile(
    r'--- Test 5: Latency Test SET.*?\n"test","rps".*?\n"SET","[\d.]+","([\d.]+)","[\d.]+","[\d.]+","[\d.]+","([\d.]+)"',
    re.S,
)
GET_LATENCY_PATTERN = re.compile(
    r'--- Test 6: Latency Test GET.*?\n"test","rps".*?\n"GET","[\d.]+","([\d.]+)","[\d.]+","[\d.]+","[\d.]+","([\d.]+)"',
    re.S,
)


def _last_overall_rps(section_text):
    matches = OVERALL_RPS_PATTERN.findall(section_text)
    return float(matches[-1]) if matches else None


def parse_log(path):
    content = path.read_text(errors="replace")
    out = {"set_rps": None, "get_rps": None, "set_lat_ms": None, "get_lat_ms": None, "set_p99_ms": None, "get_p99_ms": None}

    m = TEST1_SET_PATTERN.search(content)
    if m:
        out["set_rps"] = _last_overall_rps(m.group(0))
    m = TEST2_GET_PATTERN.search(content)
    if m:
        out["get_rps"] = _last_overall_rps(m.group(0))

    m = SET_LATENCY_PATTERN.search(content)
    if m:
        out["set_lat_ms"], out["set_p99_ms"] = float(m.group(1)), float(m.group(2))
    m = GET_LATENCY_PATTERN.search(content)
    if m:
        out["get_lat_ms"], out["get_p99_ms"] = float(m.group(1)), float(m.group(2))
    return out


def build():
    base = RESULTS_DIR / "valkey-remote"
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
        "benchmark": "valkey",
        "coverage": coverage,
        "headline": {"field": "set_rps", "direction": "max", "label": "SET Throughput", "unit": "ops/s"},
        "notes": {
            "method": "valkey-benchmark SET/GET 각 2000만 건(200 connections, no pipeline, Test 1/2 지속 처리량) 반복 평균 — Redis와 동일 방법론(benchmarks/valkey/valkey-benchmark-remote.yaml). 원격 client→server 토폴로지(client=benchmark-client c6in.2xlarge, server=대상 인스턴스 전용). Latency percentile은 별도 Latency Test(1M, --csv)에서 파싱. set_rps_all/get_rps_all은 반복별 원시값(인스턴스 상세 모달의 CV 계산용).",
        },
        "instances": instances,
    }
