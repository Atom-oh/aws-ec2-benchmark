"""Spring Boot wrk + Coldstart 원시 로그 파서.

wrk<N>.log의 50/100/200 connections 블록에서 Requests/sec를 파싱하고, 200 connections
블록의 Latency Distribution에서 P50/P99(ms)를 파싱한다. coldstart<N>.log는 Spring Boot
started 라인의 "in X.XXX seconds" 값을 사용한다.
"""
import csv
import re

import analysis
from common import BASE_DIR, PRICE, RESULTS_DIR, canonical_instances, gen_family, mean

WRK_SECTIONS = {
    "rps50": "--- Main Page - 2 threads, 50 connections, 60s ---",
    "rps100": "--- Main Page - 2 threads, 100 connections, 60s ---",
    "rps200": "--- High Load - 2 threads, 200 connections, 30s ---",
}
REQUESTS_PATTERN = re.compile(r"Requests/sec:\s+([\d.]+)")
LATENCY_50_PATTERN = re.compile(r"^\s*50%\s+([\d.]+)ms\s*$", re.M)
LATENCY_99_PATTERN = re.compile(r"^\s*99%\s+([\d.]+)ms\s*$", re.M)
COLDSTART_PATTERN = re.compile(r"Started PetClinicApplication in ([\d.]+) seconds")
TIMESERIES_CSV = BASE_DIR / "results" / "springboot-flex" / "timeseries-all.csv"
TIMESERIES_INSTANCES = [
    "c7i-flex.xlarge",
    "c8i-flex.xlarge",
    "m7i-flex.xlarge",
    "r8i-flex.xlarge",
    "c8i.xlarge",
    "c8g.xlarge",
]


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

    for key, header in WRK_SECTIONS.items():
        m = LATENCY_99_PATTERN.search(section_body(content, header))
        out[f"p99_{key}"] = float(m.group(1)) if m else None

    high_load = section_body(content, WRK_SECTIONS["rps200"])
    lat50 = LATENCY_50_PATTERN.search(high_load)
    lat99 = LATENCY_99_PATTERN.search(high_load)
    out["lat50_ms"] = float(lat50.group(1)) if lat50 else None
    out["lat99_ms"] = float(lat99.group(1)) if lat99 else None
    return out


# 콜드스타트 템플릿의 JVM 플래그 이력(git): aef8bca(2026-01-20) = JVM 기본값(Tiered 켜짐),
# 6357488(2026-04-12)부터 = -XX:-TieredCompilation(C2 전용). 로그의 Timestamp로 어느 쪽인지 판별한다.
# 51개는 2026-01-20 수집(기본값), 2026-07 백필 3개(c8gn/r8gd/m8i-flex)는 C2 전용 — C2 전용은 C1 없이
# 인터프리터로 시작해 기동이 느리므로(외부 리포트 실측 +14~27%) 같은 표에서 비교하면 안 된다.
C2_ONLY_SINCE = "2026-04-12"
TIMESTAMP_PATTERN = re.compile(r"^Timestamp:\s*(\d{4}-\d{2}-\d{2})", re.M)


def parse_coldstart_log(path):
    content = path.read_text(errors="replace")
    m = COLDSTART_PATTERN.search(content)
    return float(m.group(1)) if m else None


def coldstart_profile(inst_dir):
    # 백필 스크립트(scripts/backfill-springboot.sh)가 남긴 명시적 마커가 날짜 규칙보다 우선
    marker = inst_dir / "COLDSTART_PROFILE"
    if marker.exists():
        dates = sorted(m.group(1) for lp in inst_dir.glob("coldstart*.log")
                       if (m := TIMESTAMP_PATTERN.search(lp.read_text(errors="replace"))))
        return marker.read_text().strip() or None, (dates[-1] if dates else None)
    dates = set()
    for lp in inst_dir.glob("coldstart*.log"):
        m = TIMESTAMP_PATTERN.search(lp.read_text(errors="replace"))
        if m:
            dates.add(m.group(1))
    if not dates:
        return None, None
    profile = "c2only" if min(dates) >= C2_ONLY_SINCE else "default"
    return profile, max(dates)


def sustained_jvm_default():
    """results/springboot-flex/timeseries-all.csv — 10분 지속 부하(wrk -t2 -c100, 10초 샘플 60개) x 5회.

    수집 시점(2026-01, scripts/run-springboot-flex-timeseries.sh @ 9ecbf03)의 springboot-server.yaml에는
    -XX:-TieredCompilation이 없었다 → JVM 기본값(Tiered 켜짐) 프로파일. 본 처리량(C2 전용)과 프로파일이
    다르므로 '운영 기본 JVM 설정' 시나리오로 따로 판정한다. 회차 값 = 회차 60샘플 평균, 인스턴스 값 = 5회 중앙값.
    """
    per = {}
    with TIMESERIES_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                v = float(row["requests_per_sec"])
            except (TypeError, ValueError):
                continue
            per.setdefault(row["instance"], {}).setdefault(row["run"], []).append(v)
    stats = {n: analysis.summarize([sum(v) / len(v) for v in runs.values()]) for n, runs in per.items()}
    pairs = [analysis.pair(stats, PRICE, a, b, lname=ln, rname=rn) for a, b, ln, rn in (
        ("c8g.xlarge", "c8i.xlarge", "Graviton", "Intel"),
        ("c8i-flex.xlarge", "c8i.xlarge", "flex", "표준"))]
    return {"profile": "JVM 기본값 (Tiered 켜짐)", "load": "wrk -t2 -c100, 10분(10초 x 60샘플) x 5회",
            "stats": stats, "pairs": [q for q in pairs if q]}


def jvm_profile_effect(instances, sustained):
    """같은 커넥션 수(100)끼리: JVM 기본값(지속 측정) ÷ C2 전용(본 측정 c100 단계 중앙값).

    두 값은 다른 세션이라 ±5% 안팎의 재측정 편차(session_drift)가 섞여 있다 — 그보다 큰 변화만 해석한다.
    """
    out = []
    for n, s in sustained["stats"].items():
        c2 = instances.get(n, {}).get("steps", {}).get("rps100")
        if c2 and s:
            out.append({"name": n, "arch": gen_family(n)["arch"], "c2only_c100": c2["value"],
                        "default_c100": s["value"], "change": round(s["value"] / c2["value"] - 1, 4)})
    return sorted(out, key=lambda r: r["change"])


def build_timeseries():
    rows_by_instance = {name: [] for name in TIMESERIES_INSTANCES}
    with TIMESERIES_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            instance = row["instance"]
            if row["run"] == "2" and instance in rows_by_instance:
                rows_by_instance[instance].append(row)

    series = {}
    for instance in TIMESERIES_INSTANCES:
        rows = sorted(rows_by_instance[instance], key=lambda row: int(row["elapsed_sec"]))
        series[instance] = {
            "throughput": [float(row["requests_per_sec"]) for row in rows],
            "lat_avg_ms": [float(row["avg_latency_ms"]) for row in rows],
            "lat_p99_ms": [float(row["p99_latency_ms"]) for row in rows],
        }

    return {
        "interval_s": 10,
        "points": 60,
        "series": series,
    }


def peak_runs(inst_dir):
    """회차마다 커넥션 단계(50/100/200) 중 최대 처리량과 그 단계의 p99를 뽑는다.

    PDF 방식: 커넥션이 적은 단계는 왕복 지연이 처리량을 제한해 인스턴스 간 차이가 줄어들므로,
    비교에는 '엔드포인트별 최대 처리량'(=포화 단계)을 쓴다.
    """
    peaks, p99s, steps = [], [], []
    if not inst_dir.is_dir():
        return peaks, p99s, steps
    for lp in sorted(inst_dir.glob("wrk*.log")):
        parsed = parse_wrk_log(lp)
        levels = [(parsed[k], k) for k in ("rps50", "rps100", "rps200") if parsed.get(k)]
        if not levels:
            continue
        rps, key = max(levels)
        peaks.append(rps)
        p99s.append(parsed.get(f"p99_{key}"))
        steps.append(key.replace("rps", ""))
    return peaks, p99s, steps


def session_drift(instances):
    """같은 앱·같은 템플릿을 다른 세션(results/springboot-optimal, 커밋 6357488)에서 측정한 값과 비교.

    springboot-optimal은 Graviton=C2 전용(현재 세트와 동일 설정), Intel/AMD=Tiered 기본값(켜짐)으로
    측정됐다(커밋 메시지 근거). 따라서 Graviton 쪽 차이는 순수 '재측정 드리프트'이고, 이것이
    analysis.BAND(±5%)의 실측 근거다. Intel 쪽 차이는 Tiered 효과+드리프트가 섞여 분리할 수 없다.
    """
    out = []
    for name, rec in instances.items():
        cur = rec.get("peak")
        opt, _, _ = peak_runs(RESULTS_DIR / "springboot-optimal" / name)
        if not cur or not opt:
            continue
        o = analysis.summarize(opt)
        arch = gen_family(name)["arch"]
        out.append({"name": name, "arch": arch, "current": cur["value"], "other": o["value"],
                    "change": round(o["value"] / cur["value"] - 1, 4),
                    "other_profile": "C2 전용 (동일 설정)" if arch == "graviton" else "Tiered 기본값"})
    return sorted(out, key=lambda r: (r["arch"] != "graviton", r["name"]))


def build():
    out = _build()
    sd = next((q for q in out["sustained_default"]["pairs"] if q["left"] == "c8g.xlarge"), None)
    if sd:
        out["headline"]["caveat"] = (f"C2 전용 JVM 플래그 조건입니다. JVM 기본값(Tiered 켜짐)에서는 c8g/c8i 가격 대비 성능 "
                                     f"{sd['ppd']:.2f}배({sd['verdict']}) — SpringBoot 탭 §10")
    return out


def _build():
    base = RESULTS_DIR / "springboot"
    instances = {}
    for name in canonical_instances():
        inst_dir = base / name
        if not inst_dir.is_dir():
            continue

        wrk_runs = {k: [] for k in ["rps50", "rps100", "rps200", "lat50_ms", "lat99_ms"]}
        legacy_keys = set(wrk_runs)
        for lp in sorted(inst_dir.glob("wrk*.log")):
            parsed = parse_wrk_log(lp)
            for key, value in parsed.items():
                if value is not None and key in legacy_keys:
                    wrk_runs[key].append(value)

        cold_runs = []
        for lp in sorted(inst_dir.glob("coldstart*.log")):
            cold_s = parse_coldstart_log(lp)
            if cold_s is not None:
                cold_runs.append(cold_s)

        if not wrk_runs["rps200"] and not cold_runs:
            continue
        # 레거시 호환 필드(평균) — validate.py가 legacy 리포트와 비교하므로 유지
        wrk = {key: mean(values) for key, values in wrk_runs.items()}
        peaks, p99s, steps = peak_runs(inst_dir)
        instances[name] = {
            "wrk": wrk,
            "cold_s": mean(cold_runs),
            # 리포트 필드(회차 중앙값 + 변동계수 + 회차 값) — analysis.summarize
            "peak": analysis.summarize(peaks),
            "peak_p99_ms": analysis.summarize(p99s),
            "peak_step": max(set(steps), key=steps.count) if steps else None,
            "cold": analysis.summarize(cold_runs),
            "cold_profile": coldstart_profile(inst_dir)[0],
            "cold_date": coldstart_profile(inst_dir)[1],
            "steps": {k: analysis.summarize(wrk_runs[k]) for k in ("rps50", "rps100", "rps200")},
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
            "field": "peak.value",
            "direction": "max",
            "label": "최대 처리량 (회차 중앙값)",
            "unit": "req/s",
        },
        "notes": {
            "method": ("wrk 2 threads, 50/100 connections 60s + 200 connections 30s, 5회. 최대 처리량 = 회차마다 "
                       "커넥션 단계 중 최댓값, 인스턴스 값 = 회차 중앙값. Spring Boot coldstart 5회 중앙값"),
        },
        "analysis": {
            "throughput": analysis.analyze(
                {n: v["peak"] for n, v in instances.items()}, PRICE,
                {"field": "peak.value", "label": "최대 처리량", "unit": "req/s", "direction": "max"},
                cost_unit={"per": 1e9, "label": "요청 10억 건당 (USD)"}),
            "coldstart": analysis.analyze(
                {n: v["cold"] for n, v in instances.items() if v["cold_profile"] == "default"}, PRICE,
                {"field": "cold.value", "label": "PetClinic 기동 시간", "unit": "s", "direction": "min"}),
            "p99": analysis.analyze(
                {n: v["peak_p99_ms"] for n, v in instances.items()}, PRICE,
                {"field": "peak_p99_ms.value", "label": "최대 처리량 구간 p99", "unit": "ms", "direction": "min"}),
        },
        "session_drift": session_drift(instances),
        "sustained_default": (sus := sustained_jvm_default()),
        "jvm_profile_effect": jvm_profile_effect(instances, sus),
        "coldstart_excluded": sorted(n for n, v in instances.items() if v["cold_profile"] != "default"),
        "instances": instances,
        "timeseries": build_timeseries(),
    }
