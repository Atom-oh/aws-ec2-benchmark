#!/usr/bin/env python3
"""build_data.py 산출물을 legacy/<benchmark>.json(레거시 리포트에서 추출한 51개 인스턴스
정답지)과 대조 검증. 필드별 상대오차 0.5% 초과 시 실패로 보고.

파생 효율 필드(사이트 JSON엔 없음)는 여기서 legacy의 자체 가격으로 재계산해 legacy 값과 비교.
"""
import json
import sys

from common import LEGACY_DIR, SITE_DATA_DIR

TOLERANCE = 0.005  # 0.5%

# 알려진 원본 데이터 결손 — 파서 버그가 아니라 원시 로그 자체가 5회 중 1회 완전 실패
# ("iperf3: error - unable to send control message: Broken pipe")해 그 run의 값이 로그에
# 없음(4/5 표본). 이 3개는 headline 필드인 parallel_gbps는 0건 불일치로 완벽히 검증되지만,
# single_gbps만 유실된 5번째 run을 복원할 수 없어 legacy(5-run 평균)와 값이 갈린다.
KNOWN_INCOMPLETE_SAMPLES = {
    ("iperf3", "c7g.xlarge", "single_gbps"),
    ("iperf3", "c7i.xlarge", "single_gbps"),
    ("iperf3", "m8i.xlarge", "single_gbps"),
}

# redis: legacy 리포트의 opsSec/setLatency/getLatency는 이 저장소의 results/redis/<inst>/run*.log
# (2026-01-21 수집)로 재현되지 않는다 — legacy 값은 commit 1d9994d("Redis cleanup", 2026-01-22)에서
# 처음 등장했고, 그 세션이 참조한 원본 실행 기록이 남아있지 않다(예: r8g.xlarge legacy opsMax=248864는
# 현재 원시 로그 5회 값의 최대치 235294보다도 높아 같은 실행이 아님이 확정적). 이 저장소의 원시
# 로그만으로 만드는 새 파서는 legacy를 재현할 수 없는 게 당연하므로 3필드 전부 화이트리스트 —
# validate.py 통과가 "새 파서가 맞다"는 뜻이지 "legacy와 같은 실행"이라는 뜻은 아님을 이 주석으로 남긴다.
KNOWN_DIFFERENT_SOURCE = {
    ("redis", inst, field)
    for inst in [  # legacy/redis.json 51개 인스턴스 전체 — 같은 원인이므로 개별 나열 대신 전체 화이트리스트
        "c5.xlarge", "c5a.xlarge", "c5d.xlarge", "c5n.xlarge", "c6g.xlarge", "c6gd.xlarge", "c6gn.xlarge",
        "c6i.xlarge", "c6id.xlarge", "c6in.xlarge", "c7g.xlarge", "c7gd.xlarge", "c7i-flex.xlarge", "c7i.xlarge",
        "c8g.xlarge", "c8i-flex.xlarge", "c8i.xlarge", "m5.xlarge", "m5a.xlarge", "m5ad.xlarge", "m5d.xlarge",
        "m5zn.xlarge", "m6g.xlarge", "m6gd.xlarge", "m6i.xlarge", "m6id.xlarge", "m6idn.xlarge", "m6in.xlarge",
        "m7g.xlarge", "m7gd.xlarge", "m7i-flex.xlarge", "m7i.xlarge", "m8g.xlarge", "m8i.xlarge", "r5.xlarge",
        "r5a.xlarge", "r5ad.xlarge", "r5b.xlarge", "r5d.xlarge", "r5dn.xlarge", "r5n.xlarge", "r6g.xlarge",
        "r6gd.xlarge", "r6i.xlarge", "r6id.xlarge", "r7g.xlarge", "r7gd.xlarge", "r7i.xlarge", "r8g.xlarge",
        "r8i-flex.xlarge", "r8i.xlarge",
    ]
    for field in ["set_rps", "set_lat_ms", "get_lat_ms"]
}

# site 필드명 -> legacy 필드명, 그리고 legacy 레코드의 인스턴스 식별 키
FIELD_MAPS = {
    "sysbench": {
        "id_key": "name",
        "fields": {
            "cpu_mt": "cpu_mt", "cpu_st": "cpu_st",
            "mem_seq_write": "mem_seq_write", "mem_seq_read": "mem_seq_read",
            "mem_rnd_write": "mem_rnd_write", "mem_rnd_read": "mem_rnd_read",
            "mem_large_block": "mem_large_block",
        },
    },
    "iperf3": {
        "id_key": "instance",
        "fields": {
            "single_gbps": "single", "parallel_gbps": "parallel", "reverse_gbps": "reverse",
        },
        # udp/jitter/loss는 legacy도 sparse(일부 run 실패)해서 스케일만 sanity-check, 엄격 비교 제외
    },
    "nginx": {
        "id_key": "name",
        "fields": {"req_sec": "reqSec", "latency_ms": "latency"},
    },
    "redis": {
        "id_key": "name",
        "fields": {"set_rps": "opsSec", "set_lat_ms": "setLatency", "get_lat_ms": "getLatency"},
        # get_rps는 legacy 리포트가 SET 값을 재사용한 필드(opsSec만 존재, GET 실측 없음)라 비교 대상 아님
        # — 새 파서는 실측 GET을 별도로 저장(스키마 설계 §3의 "GET 실측 교체" 결정).
    },
    "elasticsearch": {
        "id_key": "instance",
        "fields": {
            "rally.throughput": "rally_throughput_avg", "rally.lat_p50": "rally_latency_50_avg",
            "rally.lat_p99": "rally_latency_99_avg", "rally.gc_young": "rally_gc_young_avg",
            "rally.indexing_s": "indexing_time_avg", "rally.merge_s": "merge_time_avg",
            "coldstart.avg_ms": "coldstart_avg", "coldstart.sequential_index_ms": "sequential_index_avg",
            "coldstart.bulk_index_ms": "bulk_index_avg", "coldstart.search_match_all_ms": "search_match_all_avg",
            "coldstart.search_term_ms": "search_term_avg",
        },
    },
}


def dget(obj, path):
    for k in path.split("."):
        if obj is None:
            return None
        obj = obj.get(k)
    return obj


def relative_diff(a, b):
    if a is None and b is None:
        return 0.0  # 양쪽 다 결측 = 일치(예: ES search_* 필드가 일부 run에서 미측정)
    if a is None or b is None:
        return None
    if b == 0:
        return 0.0 if a == 0 else float("inf")
    return abs(a - b) / abs(b)


def load_legacy_rows(name):
    raw = json.loads((LEGACY_DIR / f"{name}.json").read_text())
    rows = raw["rows"] if isinstance(raw, dict) and "rows" in raw else raw
    return rows


def validate_benchmark(name):
    site_path = SITE_DATA_DIR / f"{name}.json"
    if not site_path.exists():
        print(f"[{name}] SKIP — {site_path} 없음(파서 미실행)")
        return True

    site = json.loads(site_path.read_text())
    legacy_rows = load_legacy_rows(name)
    spec = FIELD_MAPS[name]
    id_key = spec["id_key"]

    mismatches = []
    checked = 0
    for row in legacy_rows:
        inst = row[id_key]
        site_inst = site["instances"].get(inst)
        if site_inst is None:
            mismatches.append((inst, "—", "인스턴스 자체가 site 데이터에 없음"))
            continue
        for site_field, legacy_field in spec["fields"].items():
            legacy_val = row.get(legacy_field)
            site_val = dget(site_inst, site_field)
            checked += 1
            diff = relative_diff(site_val, legacy_val)
            known = (name, inst, site_field) in KNOWN_INCOMPLETE_SAMPLES or (name, inst, site_field) in KNOWN_DIFFERENT_SOURCE
            if (diff is None or diff > TOLERANCE) and not known:
                mismatches.append((inst, site_field, f"site={site_val} legacy={legacy_val} diff={diff}"))

    print(f"[{name}] {len(legacy_rows)}개 인스턴스 × 필드 {checked}건 검사, coverage={site.get('coverage')}")
    if mismatches:
        print(f"  FAIL — {len(mismatches)}건 불일치:")
        for inst, field, detail in mismatches[:20]:
            print(f"    {inst} {field}: {detail}")
        if len(mismatches) > 20:
            print(f"    ... 외 {len(mismatches) - 20}건")
        return False
    print("  OK")
    return True


def main():
    targets = sys.argv[1:] or list(FIELD_MAPS.keys())
    ok = True
    for name in targets:
        if name not in FIELD_MAPS:
            print(f"[{name}] 검증 규칙 없음 — 스킵")
            continue
        ok = validate_benchmark(name) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
