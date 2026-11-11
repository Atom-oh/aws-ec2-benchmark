"""Elasticsearch Rally + Coldstart 원시 로그 파서.

rally 필드(throughput/latency/gc/indexing/merge)는 rally<N>.log의 "index-append" 태스크
요약 테이블에서, coldstart 필드는 coldstart<N>.log의 "=== Results ==="/"=== Final Summary ==="
블록에서 파싱. 5회 평균이 legacy 값과 검증 완료(상대오차 <0.01%).

nullable 규약: rally 로그가 없는 인스턴스는 rally=None, coldstart만 채운다(2026-11-11 c9g/c8gn/r8gd/m8i-flex를
scripts/backfill-es-rally.sh로 백필 — 같은 템플릿·같은 순서). analysis: cold_ms(기동, 첫 키 = 종합 headline) +
rally_tput(index-append 평균 처리량 docs/s) + rally_p99(index-append p99 지연 ms).
"""
import re

import analysis
from common import PRICE, RESULTS_DIR, canonical_instances, mean

RALLY_PATTERNS = {
    "throughput": r"Mean Throughput \| index-append \|\s*([\d.]+)",
    "lat_p50": r"50th percentile latency \| index-append \|\s*([\d.]+)",
    "lat_p99": r"99th percentile latency \| index-append \|\s*([\d.]+)",
    "gc_young": r"Total Young Gen GC time\s*\|\s*\|\s*([\d.]+)\s*\|\s*s",
    "indexing_s": r"Cumulative indexing time of primary shards\s*\|\s*\|\s*([\d.]+)\s*\|\s*min",
    "merge_s": r"Cumulative merge time of primary shards\s*\|\s*\|\s*([\d.]+)\s*\|\s*min",
}
COLDSTART_PATTERNS = {
    "avg_ms": r"COLD_START_MS:\s*(\d+)",
    "sequential_index_ms": r"SEQUENTIAL_INDEX_100_MS:\s*(\d+)",
    "bulk_index_ms": r"BULK_INDEX_1000_MS:\s*(\d+)",
    "search_match_all_ms": r"SEARCH_MATCH_ALL_AVG_MS:\s*(\d+)",
    "search_term_ms": r"SEARCH_TERM_AVG_MS:\s*(\d+)",
}


def parse_rally_log(path):
    content = path.read_text(errors="replace")
    out = {}
    for key, pattern in RALLY_PATTERNS.items():
        m = re.search(pattern, content)
        out[key] = float(m.group(1)) if m else None
    return out


def parse_coldstart_log(path):
    content = path.read_text(errors="replace")
    out = {}
    for key, pattern in COLDSTART_PATTERNS.items():
        m = re.search(pattern, content)
        out[key] = float(m.group(1)) if m else None
    return out


def build():
    base = RESULTS_DIR / "elasticsearch"
    instances = {}
    rep = {"cold_ms": {}, "rally_tput": {}, "rally_p99": {}}
    for name in canonical_instances():
        inst_dir = base / name
        if not inst_dir.is_dir():
            continue

        rally_runs = {k: [] for k in RALLY_PATTERNS}
        for lp in sorted(inst_dir.glob("rally*.log")):
            r = parse_rally_log(lp)
            for k, v in r.items():
                if v is not None:
                    rally_runs[k].append(v)
        rally = None
        if rally_runs["throughput"]:
            rally = {
                "throughput": mean(rally_runs["throughput"]), "lat_p50": mean(rally_runs["lat_p50"]),
                "lat_p99": mean(rally_runs["lat_p99"]), "gc_young": mean(rally_runs["gc_young"]),
                "indexing_s": mean(rally_runs["indexing_s"]), "merge_s": mean(rally_runs["merge_s"]),
            }

        cold_runs = {k: [] for k in COLDSTART_PATTERNS}
        for lp in sorted(inst_dir.glob("coldstart*.log")):
            r = parse_coldstart_log(lp)
            for k, v in r.items():
                if v is not None:
                    cold_runs[k].append(v)
        coldstart = None
        if cold_runs["avg_ms"]:
            coldstart = {k: mean(v) for k, v in cold_runs.items()}

        if rally is None and coldstart is None:
            continue
        instances[name] = {"rally": rally, "coldstart": coldstart}
        rep["cold_ms"][name] = cold_runs["avg_ms"]
        if rally_runs["throughput"]:
            rep["rally_tput"][name] = rally_runs["throughput"]
            rep["rally_p99"][name] = rally_runs["lat_p99"]

    rally_coverage = sum(1 for v in instances.values() if v["rally"] is not None)
    cold_coverage = sum(1 for v in instances.values() if v["coldstart"] is not None)
    specs = {
        "cold_ms": {"label": "Elasticsearch 기동 시간", "unit": "ms", "direction": "min", "memory_sensitive": True},
        "rally_tput": {"label": "Rally 색인 처리량 (index-append)", "unit": "docs/s", "direction": "max", "memory_sensitive": True},
        "rally_p99": {"label": "Rally 색인 p99 지연", "unit": "ms", "direction": "min", "memory_sensitive": True},
    }
    rep = {k: v for k, v in rep.items() if v}
    summaries, blocks = analysis.report(rep, {k: specs[k] for k in rep}, PRICE)
    for _n, _r in summaries.items():
        if _n in instances:
            instances[_n]["r"] = _r
    return {
        "benchmark": "elasticsearch",
        "coverage": cold_coverage,
        "headline": {"field": "coldstart.avg_ms", "direction": "min", "label": "Cold Start", "unit": "ms",
                     "matrix_rows": [{"key": "cold_ms", "name": "Elasticsearch · 기동 시간"},
                                     {"key": "rally_tput", "name": "Elasticsearch · Rally 색인 처리량"}]},
        "notes": {
            "method": "Rally(index-append 태스크) 5회 평균 + Coldstart(시작~ready) 5회 평균",
            "rally_coverage": f"rally {rally_coverage}개 · coldstart {cold_coverage}개 인스턴스"
                              + ("" if rally_coverage == cold_coverage else f" (rally 없음: {', '.join(n for n, v in instances.items() if v['rally'] is None)})"),
        },
        "instances": instances,
        "analysis": blocks,
    }
