"""Elasticsearch Rally + Coldstart 원시 로그 파서.

rally 필드(throughput/latency/gc/indexing/merge)는 rally<N>.log의 "index-append" 태스크
요약 테이블에서, coldstart 필드는 coldstart<N>.log의 "=== Results ==="/"=== Final Summary ==="
블록에서 파싱. 5회 평균이 legacy 값과 검증 완료(상대오차 <0.01%).

nullable 규약: c8gn/r8gd.xlarge는 rally 로그가 없음(coldstart만 존재) — rally는 None으로
남기고 coldstart는 채운다. build_data.py의 커버리지 assert는 이 벤치마크를 51 기대치로 등록.
"""
import re

from common import RESULTS_DIR, canonical_instances, mean

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

    rally_coverage = sum(1 for v in instances.values() if v["rally"] is not None)
    cold_coverage = sum(1 for v in instances.values() if v["coldstart"] is not None)
    return {
        "benchmark": "elasticsearch",
        "coverage": cold_coverage,
        "headline": {"field": "coldstart.avg_ms", "direction": "min", "label": "Cold Start", "unit": "ms"},
        "notes": {
            "method": "Rally(index-append 태스크) 5회 평균 + Coldstart(시작~ready) 5회 평균",
            "rally_coverage": f"rally는 {rally_coverage}개 인스턴스만 커버(c8gn/r8gd.xlarge는 coldstart 로그만 존재)",
        },
        "instances": instances,
    }
