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
    "springboot": 54,
    "valkey": 54,
    "redis-io4": 54,
    "valkey-io4": 54,
    "web": 54,
    "springboot-memory": 24,  # C·M·R 6~9세대 기본형+flex(d/n 제외)
}


# 종합 탭 '종합 분석'의 워크로드 유형 분류(벤치마크 → 유형). 판정 매트릭스 행에 같이 실린다.
CATEGORY = {
    "sysbench": "CPU 연산", "geekbench": "CPU 연산", "passmark": "CPU 연산", "stress-ng": "CPU 연산",
    "iperf3": "네트워크", "nginx": "웹 서버·프록시",
    "redis": "인메모리 캐시", "valkey": "인메모리 캐시", "redis-io4": "인메모리 캐시", "valkey-io4": "인메모리 캐시",
    "springboot": "웹 프레임워크(런타임)", "web": "웹 프레임워크(런타임)", "springboot-memory": "웹 프레임워크(메모리 압박)",
    "elasticsearch": "검색·분석", "clickhouse": "검색·분석", "kafka": "스트리밍",
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
    # 리포트 분석이 있으면 기본 분석 블록 키(= analysis의 첫 키)를 headline에 명시 — overview가 벤치마크별
    # 분기 없이 Graviton/Intel 판정표를 만들 때 이 키만 읽는다.
    if data.get("analysis") and "analysis_key" not in data["headline"]:
        data["headline"]["analysis_key"] = next(iter(data["analysis"]))
    if name in CATEGORY:
        data["headline"]["category"] = CATEGORY[name]
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
        "springboot", "valkey", "redis-io4", "valkey-io4",
        "web",  # 측정 중인 스택은 parsers/web.py가 자동 제외(pending_stacks)
        "springboot-memory",
    ]
    for name in targets:
        build_benchmark(name)


if __name__ == "__main__":
    main()
