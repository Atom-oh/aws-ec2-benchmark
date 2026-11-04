"""Nginx wrk 원시 로그 파서.

로그는 wrk 3단계(100/200/400 커넥션)를 포함하지만 레거시 리포트의 headline
(reqSec/latency)은 8 threads/400 connections 블록의 5회 평균임을 검증으로 확인
(legacy c8g.xlarge: reqSec=258617.09, latency=1.542 — 둘 다 일치).
"""
import re

import analysis
from common import PRICE, RESULTS_DIR, canonical_instances, mean

SECTION_PATTERN = re.compile(
    r"=== wrk Test \((\d+) threads, (\d+) connections, 30s\) ===\n(.*?)(?=\n===|\Z)", re.S
)


def parse_log(path):
    content = path.read_text(errors="replace")
    for threads, conns, body in SECTION_PATTERN.findall(content):
        if threads == "8" and conns == "400":
            req_sec = re.search(r"Requests/sec:\s+([\d.]+)", body)
            latency = re.search(r"Latency\s+([\d.]+)ms", body)
            return (
                float(req_sec.group(1)) if req_sec else None,
                float(latency.group(1)) if latency else None,
            )
    return None, None


def build():
    base = RESULTS_DIR / "nginx"
    instances = {}
    rep = {"req_sec": {}, "latency_ms": {}}
    for name in canonical_instances():
        inst_dir = base / name
        if not inst_dir.is_dir():
            continue
        req_runs, lat_runs = [], []
        for lp in sorted(inst_dir.glob("run*.log")):
            req_sec, latency = parse_log(lp)
            if req_sec is not None:
                req_runs.append(req_sec)
            if latency is not None:
                lat_runs.append(latency)
        if not req_runs:
            continue
        instances[name] = {"req_sec": mean(req_runs), "latency_ms": mean(lat_runs)}
        rep["req_sec"][name], rep["latency_ms"][name] = req_runs, lat_runs

    coverage = sum(1 for v in instances.values() if v["req_sec"] is not None)
    summaries, blocks = analysis.report(rep, {"req_sec": {"label": "Nginx 처리량 (8t/400c)", "unit": "req/s", "direction": "max", "cost_unit": {"per": 1e9, "label": "요청 10억 건당 (USD)"}}, "latency_ms": {"label": "Nginx 평균 지연", "unit": "ms", "direction": "min"}}, PRICE)
    for _n, _r in summaries.items():
        if _n in instances:
            instances[_n]["r"] = _r
    return {
        "benchmark": "nginx",
        "coverage": coverage,
        "headline": {"field": "req_sec", "direction": "max", "label": "Requests/sec", "unit": "req/s"},
        "notes": {
            "method": "wrk -t8 -c400 -d30s, 5회 평균 (100/200커넥션 warm-up 단계도 로그에 있으나 헤드라인은 8t/400c)",
        },
        "instances": instances,
        "analysis": blocks,
    }
