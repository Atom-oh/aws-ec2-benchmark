"""Spring Boot 메모리 부하 벤치마크 파서 — results/sbmem-remote/<instance>/run<N>.log.

설계(benchmarks/springboot-memory/mem-{server,benchmark}-remote.yaml):
  힙 = RAM x 60%, 상주 캐시 = 전 인스턴스 동일 2GB(조건 통일 — 차이는 처리량이 쌓는 작업 객체만). 클라이언트가 이론 최대 처리 중 요청 수 K = (힙 - 상주) / 작업 객체(1MB)를
  구해 커넥션을 K의 25/50/60/70/80/90/100/110%로 늘린다(각 60s, 2단계 연속 실패 시 중단).
로그: Server-Version(heap_max_mb·entries) / INFLIGHT_MAX_THEORY: K / === Stage connections=<C> pct=<P> === <wrk> END_C<C> / STATS_C<C>.

단계 통과 = p99 <= 대기 + 1초(로그 SLO_P99_MS), 오류·타임아웃·non-2xx 0, 서버 /stats 응답(OOM 재시작 아님).
'버틴 커넥션'(capacity) = 연속으로 통과한 가장 높은 단계의 커넥션 수(5회 중앙값), '힙 활용률' = 그 단계의 pct.
(2026-11-05 1차 설계 results/sbmem{12,24}-remote — 힙 12/24GB 절대값 고정 — 는 R이 RAM의 39%만 써 폐기, 파서 미참조.)
"""
import json
import re
import statistics

import analysis
from common import PRICE, RESULTS_DIR, canonical_instances, parse_wrk_block, wrk_time_ms

CPU_LIMIT_PCT = 70     # 첫 실패 단계(오류 없음)의 서버 CPU가 이 이상이면 'CPU 한계'(메모리는 남음), 미만이면 'GC 정지 누적'(CPU 여유)
SLO_DEFAULT_MS = 11000  # 대기(HOLD_MS 10초) + 처리 여유 1초 — 로그의 SLO_P99_MS가 우선
# 변형: 결과 디렉터리 → 설명. 단계(이론 최대 대비 %)는 각 변형의 로그에서 읽는다(sbmem2는 75~96%를 더 세밀하게).
VARIANTS = {
    "sbmem": {"label": "요청당 garbage 없음", "note": "요청은 1MB 작업 객체만 만든다(2026-11-06 측정)"},
    "sbmem2": {"label": "요청당 garbage 4MB", "note": "요청마다 금방 버려지는 객체 4MB(파싱·DTO·직렬화 버퍼 흉내)를 더 만든다 — 처리량에 비례해 GC 작업 증가(이미지 1.3)"},
}
FULL_COVERAGE = 24   # 주 변형으로 쓰려면 이만큼의 인스턴스가 있어야 함(부분 측정 중에는 이전 변형 유지)
STAGE = re.compile(r"=== Stage connections=(\d+) pct=(\d+) .*?===\n(.*?)(?=^END_C)", re.S | re.M)


def parse_log(path):
    text = path.read_text(errors="replace")
    if "Benchmark Complete" not in text:
        return None
    v = (re.search(r"^Server-Version: (.+)$", text, re.M) or [None, ""])[1]
    num = lambda k: int(m.group(1)) if (m := re.search(rf"{k} (\d+)", v)) else None  # noqa: E731
    k = re.search(r"^INFLIGHT_MAX_THEORY: (\d+)", text, re.M)
    slo_m = re.search(r"^SLO_P99_MS: (\d+)", text, re.M)
    slo = int(slo_m.group(1)) if slo_m else SLO_DEFAULT_MS
    entries, ekb = num("entries"), num("entry_kb") or 4
    out = {"heap_mb": num("heap_max_mb"), "live_mb": entries * ekb // 1024 if entries else None,
           "k": int(k.group(1)) if k else None, "slo_ms": slo, "hold_ms": num("hold_ms"), "stages": {}}
    for c, pct, body in STAGE.findall(text):
        w = parse_wrk_block(body) or {}
        st = re.search(rf"^STATS_C{c}: (\{{.*\}})$", text, re.M)
        try:
            s = json.loads(st.group(1)) if st else {}
        except json.JSONDecodeError:
            s = {}
        timeouts = re.search(r"timeout (\d+)", body)
        # p95·p99.9는 wrk 기본 출력에 없어 클라이언트 lua done()이 'LAT_P95_MS: <ms>' 형식으로 찍은 경우에만(2026-11-06 이후)
        extra = {k: float(m.group(1)) for k, pat in (("p95_ms", r"^LAT_P95_MS: ([\d.]+)"), ("p999_ms", r"^LAT_P999_MS: ([\d.]+)"))
                 if (m := re.search(pat, body, re.M))}
        p75 = re.search(r"^\s+75%\s+([\d.]+)(us|ms|s|m)\b", body, re.M)   # parse_wrk_block은 50/90/99만 — p75는 이 탭에서만
        if p75:
            extra["p75_ms"] = wrk_time_ms(*p75.groups())
        stage = {"conn": int(c), "rps": w.get("rps"), "p99_ms": w.get("p99_ms"), "p50_ms": w.get("p50_ms"),
                 "p90_ms": w.get("p90_ms"), **extra,
                 "errors": w.get("errors"), "timeouts": int(timeouts.group(1)) if timeouts else 0,
                 "gc_max_ms": s.get("gc_pause_max_ms"), "gc_total_ms": s.get("gc_pause_total_ms"),
                 "gc_over100": s.get("gc_pause_over100ms"), "old_after_gc_mb": s.get("old_after_gc_mb"),
                 "inflight_peak": s.get("inflight_peak"), "cpu_pct": s.get("proc_cpu_pct"),
                 "window_s": s.get("window_s"), "stats_ok": "error" not in s and bool(s)}
        stage["slo_ok"] = bool(stage["rps"] and stage["p99_ms"] is not None and stage["p99_ms"] <= slo
                               and not stage["errors"] and stage["stats_ok"])
        out["stages"][int(pct)] = stage
    return out


def _capacity(run, pcts):
    """연속 통과한 최고 단계 → (커넥션, pct). 중간 실패 후 우연 통과는 무시."""
    conn, pct = 0, 0
    for p in pcts:
        st = run["stages"].get(p)
        if not (st and st["slo_ok"]):
            break
        conn, pct = st["conn"], p
    return conn, pct


def _build_variant(var):
    insts = {}
    for name in canonical_instances():
        d = RESULTS_DIR / f"{var}-remote" / name
        runs = [r for r in (parse_log(lp) for lp in sorted(d.glob("run*.log"))) if r] if d.is_dir() else []
        if not runs:
            continue
        PCTS = sorted({p for r in runs for p in r["stages"]})
        caps = [_capacity(r, PCTS) for r in runs]
        stage_med = {}
        for p in PCTS:
            vals = [r["stages"][p] for r in runs if p in r["stages"]]
            if not vals:
                continue
            med = lambda k: (round(statistics.median([v[k] for v in vals if v.get(k) is not None]), 1)  # noqa: E731
                             if any(v.get(k) is not None for v in vals) else None)
            gc_share = [v["gc_total_ms"] / (v["window_s"] * 10) for v in vals if v.get("gc_total_ms") is not None and v.get("window_s")]
            stage_med[str(p)] = {"conn": med("conn"), "rps": med("rps"), "p99_ms": med("p99_ms"), "p50_ms": med("p50_ms"),
                                 "p75_ms": med("p75_ms"), "p90_ms": med("p90_ms"), "p95_ms": med("p95_ms"), "p999_ms": med("p999_ms"), "gc_max_ms": med("gc_max_ms"),
                                 "gc_pct": round(statistics.median(gc_share), 1) if gc_share else None,
                                 "old_after_gc_mb": med("old_after_gc_mb"), "inflight_peak": med("inflight_peak"),
                                 "cpu_pct": med("cpu_pct"), "errors": sum((v.get("errors") or 0) for v in vals),
                                 "slo_pass": sum(1 for v in vals if v["slo_ok"]), "runs": len(vals)}
        nxt = next((p for p in PCTS if p > statistics.median([p for _, p in caps])), None)
        fst = stage_med.get(str(nxt), {}) if nxt else {}
        # 첫 실패 단계의 원인: 오류(소켓 오류·OOM 재시작 — 그 단계의 /stats는 재시작한 서버라 CPU 무의미) → 'oom',
        # 오류 없이 p99만 초과 + CPU >= 기준 → 'cpu'(메모리는 남음), 오류 없이 p99 초과 + CPU 여유 → 'gc'(GC 정지 누적)
        if not fst:
            limit, fail_cpu = None, None
        elif fst.get("errors"):
            limit, fail_cpu = "oom", None
        else:
            fail_cpu = fst.get("cpu_pct")
            limit = "cpu" if (fail_cpu or 0) >= CPU_LIMIT_PCT else "gc"
        insts[name] = {"limit": limit, "fail_cpu_pct": fail_cpu, "heap_mb": runs[0]["heap_mb"], "hold_ms": runs[0]["hold_ms"], "slo_ms": runs[0]["slo_ms"], "live_mb": runs[0]["live_mb"], "k": runs[0]["k"],
                       "capacity": int(statistics.median([c for c, _ in caps])), "capacity_runs": [c for c, _ in caps],
                       "util_pct": int(statistics.median([p for _, p in caps])), "util_runs": [p for _, p in caps],
                       "stages": stage_med}

    pcts = sorted({int(p) for v in insts.values() for p in v["stages"]})
    key = f"{var}_capacity"
    rep = {key: {n: v["capacity_runs"] for n, v in insts.items() if any(v["capacity_runs"])}}
    rep = {k: v for k, v in rep.items() if v}
    specs = {key: {"label": "버틴 동시 커넥션 (힙 = RAM 60%)", "unit": "커넥션", "direction": "max", "memory_sensitive": True,
                   # 메모리 압박 탭은 범용(M) 인스턴스를 기준선으로(사용자 요청 2026-11-06) — 다른 탭은 c7i.xlarge 유지
                   "baseline": "m7i.xlarge"}}
    summaries, blocks = analysis.report(rep, specs, PRICE) if rep else ({}, {})
    return insts, pcts, summaries, blocks


def build():
    built = {v: _build_variant(v) for v in VARIANTS}
    built = {v: b for v, b in built.items() if b[0]}
    primary = "sbmem2" if len(built.get("sbmem2", ({},))[0]) >= FULL_COVERAGE else "sbmem"
    insts, PCTS, summaries, blocks = built[primary]
    instances = {n: {"sbmem": v} for n, v in insts.items()}
    for n, r in summaries.items():
        instances[n]["r"] = r
    first = next(iter(blocks), None)
    key = first
    return {
        "benchmark": "springboot-memory",
        "coverage": len(instances),
        "headline": {"field": f"r.{first}.value" if first else "sbmem.capacity", "direction": "max",
                     "label": "버틴 동시 커넥션 (힙 = RAM 60%)", "unit": "커넥션",
                     # 메모리 크기 자체가 비교 변수라 같은 패밀리(M) 짝으로 종합 판정 — C/M/R 간 차이는 탭 본문에서
                     "matrix_rows": [{"key": key, "name": "웹 · Spring Boot 메모리 압박", "family": "m"}]},
        "notes": {
            "method": ("힙 = RAM x 60%(-Xms=-Xmx), 상주 캐시 = 전 인스턴스 동일 2GB, 운영형 요청(8KB 본문 → 1MB 작업 객체, 상주 캐시 1항목 교체, 10초 대기). "
                       "커넥션 = 이론 최대 처리 중 요청 수 K=(힙-상주)/1MB의 25~110%, 각 90s. G1GC, AlwaysPreTouch, 가상 스레드."),
            "slo": "단계 통과 = p99 <= 대기 + 1초(11초), 오류·타임아웃 0, OOM 재시작 없음. 버틴 커넥션 = 연속 통과한 최고 단계",
        },
        "pcts": PCTS,
        "cpu_limit_pct": CPU_LIMIT_PCT,
        "slo_ms": next((v["slo_ms"] for v in insts.values()), SLO_DEFAULT_MS),
        "tier": insts,
        "variant": primary,
        "variants": {v: {"label": VARIANTS[v]["label"], "note": VARIANTS[v]["note"], "coverage": len(b[0]), "pcts": b[1], "tier": b[0], "analysis": b[3]}
                     for v, b in built.items()},
        "analysis": blocks,
        "instances": instances,
    }
