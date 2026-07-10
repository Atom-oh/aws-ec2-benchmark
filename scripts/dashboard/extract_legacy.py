#!/usr/bin/env python3
"""레거시 reports/*.html의 인라인 데이터 배열을 legacy/<benchmark>.json으로 추출.

validate.py가 이 파일들을 "51개 인스턴스 정답지"로 사용해 새 파서(build_data.py) 출력을 검증한다.
kafka/clickhouse는 재파싱 대상이 아니라(기존 data.json 재사용) 여기 포함하지 않는다.
"""
import json
import re
from pathlib import Path

from common import REPORTS_DIR, LEGACY_DIR


def _quote_keys_and_strings(text):
    text = re.sub(r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', text)
    text = re.sub(r"'([^']*)'", r'"\1"', text)
    text = re.sub(r",(\s*[\]}])", r"\1", text)  # trailing comma
    return text


def extract_js_literal(html, pattern):
    """HTML에서 `pattern`(캡처그룹 1개)으로 잡은 JS 배열/객체 리터럴을 파싱."""
    m = re.search(pattern, html, re.S)
    if not m:
        raise ValueError(f"pattern not found: {pattern!r}")
    return json.loads(_quote_keys_and_strings(m.group(1)))


def extract_sysbench():
    html = (REPORTS_DIR / "sysbench-report.html").read_text()
    return extract_js_literal(html, r"const data = (\[.*?\]);")


def extract_redis():
    html = (REPORTS_DIR / "redis-report.html").read_text()
    return extract_js_literal(html, r"const benchmarkData = (\[.*?\]);")


def extract_nginx():
    html = (REPORTS_DIR / "nginx-report.html").read_text()
    return extract_js_literal(html, r"const allInstances = (\[.*?\]);")


def extract_springboot():
    html = (REPORTS_DIR / "springboot-report.html").read_text()
    rows = extract_js_literal(html, r"const data = (\[.*?\]);")
    out = {"rows": rows}
    # time-series 사이드카 (6인스턴스 x 60pt) — flexTimeseriesData/latencyAvgData/latencyP99Data.
    # 각 객체의 `labels` 필드는 `Array.from({length:60}, (_, i) => (i+1)*10)` 같은 JS 식이라
    # JSON으로 못 파싱 — 값 자체는 사용하지 않으므로(60포인트 등간격 10s는 스키마 쪽에서 재생성) 제거만.
    for var, key in [
        ("flexTimeseriesData", "throughput"),
        ("latencyAvgData", "lat_avg_ms"),
        ("latencyP99Data", "lat_p99_ms"),
    ]:
        m = re.search(rf"const {var} = (\{{.*?\n        \}});", html, re.S)
        if m:
            body = re.sub(r"labels:\s*Array\.from\([^)]*\([^)]*\)\s*=>\s*[^,]+,\s*", "", m.group(1))
            out.setdefault("timeseries", {})[key] = json.loads(_quote_keys_and_strings(body))
    return out


def extract_geekbench():
    html = (REPORTS_DIR / "geekbench-report.html").read_text()
    return extract_js_literal(html, r"const data = (\[.*?\]);")


def extract_stress_ng():
    html = (REPORTS_DIR / "stress-ng-report.html").read_text()
    return extract_js_literal(html, r"const data = (\[.*?\]);")


def extract_elasticsearch():
    html = (REPORTS_DIR / "elasticsearch-report.html").read_text()
    return extract_js_literal(html, r"const benchmarkData = (\[.*?\]);")


def extract_iperf3():
    html = (REPORTS_DIR / "iperf3-report.html").read_text()
    rows = extract_js_literal(html, r"const rawData = (\[.*?\]);")
    pricing = extract_js_literal(html, r"const instancePricing = (\{.*?\});")
    return {"rows": rows, "pricing": pricing}


def extract_passmark():
    html = (REPORTS_DIR / "passmark-report.html").read_text()
    m = re.search(r'<table id="resultsTable">.*?<tbody>(.*?)</tbody>', html, re.S)
    tbody = m.group(1)
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.S):
        tds = re.findall(r"<td>(.*?)</td>", tr, re.S)
        name = re.sub(r"<[^>]+>", "", tds[1]).strip()
        arch = re.sub(r"<[^>]+>", "", tds[2]).strip()
        gen = re.sub(r"[^\d]", "", tds[3])
        cpu_mark = float(re.sub(r"<[^>]+>|,", "", tds[4]))
        single = float(tds[5].replace(",", ""))
        price = float(tds[6].replace("$", ""))
        rows.append({
            "instance": name, "arch": arch, "gen": int(gen),
            "cpu_mark": cpu_mark, "single": single, "price": price,
        })

    detail = extract_js_literal(html, r"const detailData = (\{.*?\n        \});")
    detail_by_instance = {}
    field_map = {"integer": "int", "float": "float", "encryption": "encryption", "compression": "compression"}
    for src_key, field in field_map.items():
        for d in detail[src_key]["data"]:
            detail_by_instance.setdefault(d["instance"], {})[field] = d["value"]

    for row in rows:
        row.update(detail_by_instance.get(row["instance"], {}))
    return rows


EXTRACTORS = {
    "sysbench": extract_sysbench,
    "redis": extract_redis,
    "nginx": extract_nginx,
    "springboot": extract_springboot,
    "geekbench": extract_geekbench,
    "stress-ng": extract_stress_ng,
    "elasticsearch": extract_elasticsearch,
    "iperf3": extract_iperf3,
    "passmark": extract_passmark,
}


def main():
    LEGACY_DIR.mkdir(exist_ok=True)
    for name, fn in EXTRACTORS.items():
        data = fn()
        out_path = LEGACY_DIR / f"{name}.json"
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        count = len(data) if isinstance(data, list) else len(data.get("rows", data))
        print(f"{name}: {count} rows -> {out_path.relative_to(LEGACY_DIR.parent)}")


if __name__ == "__main__":
    main()
