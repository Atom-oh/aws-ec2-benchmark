"""Spring Boot wrk + Coldstart 원시 로그 파서.

wrk<N>.log의 50/100/200 connections 블록에서 Requests/sec를 파싱하고, 200 connections
블록의 Latency Distribution에서 P50/P99(ms)를 파싱한다. coldstart<N>.log는 Spring Boot
started 라인의 "in X.XXX seconds" 값을 사용한다.
"""
import re

from common import RESULTS_DIR, canonical_instances, mean

WRK_SECTIONS = {
    "rps50": "--- Main Page - 2 threads, 50 connections, 60s ---",
    "rps100": "--- Main Page - 2 threads, 100 connections, 60s ---",
    "rps200": "--- High Load - 2 threads, 200 connections, 30s ---",
}
REQUESTS_PATTERN = re.compile(r"Requests/sec:\s+([\d.]+)")
LATENCY_50_PATTERN = re.compile(r"^\s*50%\s+([\d.]+)ms\s*$", re.M)
LATENCY_99_PATTERN = re.compile(r"^\s*99%\s+([\d.]+)ms\s*$", re.M)
COLDSTART_PATTERN = re.compile(r"Started PetClinicApplication in ([\d.]+) seconds")


def section_body(content, header):
    start = content.find(header)
    if start == -1:
        return ""
    body_start = start + len(header)
    next_section = content.find("\n--- ", body_start)
    if next_section == -1:
        return content[body_start:]
    return content[body_start:next_section]


def parse_wrk_log(path):
    content = path.read_text(errors="replace")
    out = {}
    for key, header in WRK_SECTIONS.items():
        body = section_body(content, header)
        m = REQUESTS_PATTERN.search(body)
        out[key] = float(m.group(1)) if m else None

    high_load = section_body(content, WRK_SECTIONS["rps200"])
    lat50 = LATENCY_50_PATTERN.search(high_load)
    lat99 = LATENCY_99_PATTERN.search(high_load)
    out["lat50_ms"] = float(lat50.group(1)) if lat50 else None
    out["lat99_ms"] = float(lat99.group(1)) if lat99 else None
    return out


def parse_coldstart_log(path):
    content = path.read_text(errors="replace")
    m = COLDSTART_PATTERN.search(content)
    return float(m.group(1)) if m else None


def build():
    base = RESULTS_DIR / "springboot"
    instances = {}
    for name in canonical_instances():
        inst_dir = base / name
        if not inst_dir.is_dir():
            continue

        wrk_runs = {k: [] for k in ["rps50", "rps100", "rps200", "lat50_ms", "lat99_ms"]}
        for lp in sorted(inst_dir.glob("wrk*.log")):
            parsed = parse_wrk_log(lp)
            for key, value in parsed.items():
                if value is not None:
                    wrk_runs[key].append(value)

        cold_runs = []
        for lp in sorted(inst_dir.glob("coldstart*.log")):
            cold_s = parse_coldstart_log(lp)
            if cold_s is not None:
                cold_runs.append(cold_s)

        if not wrk_runs["rps200"] and not cold_runs:
            continue
        wrk = {key: mean(values) for key, values in wrk_runs.items()}
        instances[name] = {
            "wrk": wrk,
            "cold_s": mean(cold_runs),
        }

    coverage = sum(
        1
        for v in instances.values()
        if v["wrk"]["rps200"] is not None and v["cold_s"] is not None
    )
    return {
        "benchmark": "springboot",
        "coverage": coverage,
        "headline": {
            "field": "wrk.rps200",
            "direction": "max",
            "label": "Requests/sec (200 conn)",
            "unit": "req/s",
        },
        "notes": {
            "method": "wrk 2 threads, 50/100 connections 60s + 200 connections 30s, 5회 평균; Spring Boot coldstart 5회 평균",
        },
        "instances": instances,
    }
