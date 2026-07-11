#!/usr/bin/env python3
"""원시 로그 -> site/data/*.json 빌드 드라이버.

각 벤치마크는 parsers/<name>.py의 build() -> dict(공통 봉투 스키마)를 site/data/<name>.json으로
저장. 커버리지가 기대치(54, 또는 51 — 레거시 3종)에 못 미치면 경고만 출력(원시 로그 자체가 51개뿐인
벤치마크가 있으므로 하드 실패시키지 않음 — 상세는 각 파서의 docstring 참고).
"""
import json
import sys

from common import SITE_DATA_DIR, build_instances, BASE_DIR

EXPECTED_COVERAGE = {
    "sysbench": 54,
    "iperf3": 54,
    "nginx": 54,
    "redis": 54,
    "elasticsearch": 54,  # coldstart 기준. rally는 51(파서 notes에 별도 표기)
    "kafka": 54,
    "clickhouse": 54,
    "geekbench": 51,  # 원시 로그 자체가 51개뿐(재파싱 대상 아님) — 51 미달이면만 경고
    "passmark": 51,
    "stress-ng": 51,
}


def write_instances_json():
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_instances()
    path = SITE_DATA_DIR / "instances.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"instances.json: {len(payload)}개 인스턴스 -> {path.relative_to(BASE_DIR)}")


def build_benchmark(name):
    module = __import__(f"parsers.{name.replace('-', '_')}", fromlist=["build"])
    data = module.build()
    path = SITE_DATA_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    expected = EXPECTED_COVERAGE.get(name)
    status = "OK"
    if expected and data["coverage"] < expected:
        status = f"WARN coverage {data['coverage']}/{expected}"
    print(f"{name}.json: coverage={data['coverage']} {status} -> {path.relative_to(BASE_DIR)}")


def main():
    write_instances_json()
    targets = sys.argv[1:] or [
        "sysbench", "iperf3", "nginx", "redis", "elasticsearch",
        "kafka", "clickhouse", "geekbench", "passmark", "stress-ng",
    ]
    for name in targets:
        build_benchmark(name)


if __name__ == "__main__":
    main()
