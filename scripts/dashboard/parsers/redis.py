"""Redis 원시 로그 파서 (원격 client→server 토폴로지, io-threads 없음).

2026-07 1차 재측정은 server+client를 같은 파드(localhost, 4 vCPU 공유)에서 실행했으나, 이
방식은 io-threads 비교축을 왜곡시킴이 확인됨(아래 redis_io4.py 참고 — CPU 경합으로 -26%
역효과). 실무에서 Redis/Valkey를 localhost로 붙여 쓰는 경우는 없고 항상 별도 서버로 운용하므로,
server를 대상 인스턴스에 단독 배포하고 client를 별도 고네트워크 인스턴스(benchmark-client
nodepool, c6in.2xlarge)에서 실행하는 원격 토폴로지로 전면 교체했다(2차 재측정,
benchmarks/redis/redis-server-remote.yaml + redis-benchmark-remote.yaml). SET/GET 각 2000만
건(200 connections, no pipeline)의 진행률 로그 마지막 "overall:" 값을 throughput으로 쓴다 —
redis-benchmark CSV 요약(--csv)의 duration이 0.25초 단위로만 반올림돼 짧은 테스트에서 양자화
노이즈가 크다는 문제(1차 재측정에서 발견)를 피하기 위해 진행률 로그 방식을 유지.

Test 5/6은 latency percentile(min/p50/p95/p99/max)의 유일한 소스라 여전히 1M 건 --csv로
파싱하되, throughput 필드(set_rps/get_rps)에는 쓰지 않는다. 원시 로그: results/redis-remote/.
"""
import re

import analysis
from common import PRICE, RESULTS_DIR, canonical_instances, mean

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
    base = RESULTS_DIR / "redis-remote"
    instances = {}
    rep = {"set_rps": {}, "get_rps": {}}
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
        rep["set_rps"][name], rep["get_rps"][name] = runs["set_rps"], runs["get_rps"]

    coverage = sum(1 for v in instances.values() if v["set_rps"] is not None)
    summaries, blocks = analysis.report(rep, {"set_rps": {"label": "Redis SET 처리량", "unit": "ops/s", "direction": "max"}, "get_rps": {"label": "Redis GET 처리량", "unit": "ops/s", "direction": "max"}}, PRICE)
    for _n, _r in summaries.items():
        if _n in instances:
            instances[_n]["r"] = _r
    return {
        "benchmark": "redis",
        "coverage": coverage,
        "headline": {"field": "set_rps", "direction": "max", "label": "SET Throughput", "unit": "ops/s"},
        "notes": {
            "method": "redis-benchmark SET/GET 각 2000만 건(200 connections, no pipeline, Test 1/2 지속 처리량) 반복 평균. 원격 client→server 토폴로지(client=benchmark-client c6in.2xlarge, server=대상 인스턴스 전용 — 4 vCPU를 client와 공유하지 않음). Latency percentile은 별도 Latency Test(1M, --csv)에서 파싱. set_rps_all/get_rps_all은 반복별 원시값(인스턴스 상세 모달의 CV 계산용).",
        },
        "instances": instances,
        "analysis": blocks,
    }
