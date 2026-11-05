"""Spring Boot 메모리 부하 벤치마크 파서 — results/sbmem{12,24}-remote/<instance>/run<N>.log.

로그 구조(benchmarks/springboot-memory/mem-benchmark-remote.yaml):
  Server-Version: ... entries <N> ... heap_max_mb <H> ...
  === Stage connections=<C> (process, ...) ===  <wrk --latency 출력>
  MIX_RPS_C<C>: <캐시 혼합 트래픽 req/s>
  STATS_C<C>: {서버 /stats JSON — GC 정지·heap·old_after_gc·inflight·proc_cpu}

단계별 SLO 판정(운영형 요청 /process, 하위 시스템 대기 1초 포함):
  p99 <= SLO_P99_MS, 소켓 오류·타임아웃·non-2xx = 0  (GC 정지 시간 비율·최대 정지는 참고값)
'버틴 커넥션 수'(capacity) = SLO를 지킨 가장 높은 단계. 가성비 = capacity / 시간당 가격(동시 사용자 1,000명당 비용도 함께).
메모리가 부족한 인스턴스는 기동 스크립트가 힙·상주 데이터를 줄이므로(fit=reduced) 결과에 그대로 표시한다.
"""
import json
import re
import statistics

import analysis
from common import PRICE, RESULTS_DIR, canonical_instances, mean, parse_wrk_block

SLO_P99_MS = 2000      # 대기 1초 + 처리 여유 1초
# 판정은 사용자가 체감하는 값(p99·오류)으로만 — GC 정지 비율·최대 정지는 원인 설명용 참고값(10% 기준은 스모크에서
# 1024 단계부터 전 인스턴스가 11% 안팎으로 걸려 변별력이 없었음)
STAGES = [256, 1024, 2048, 3072, 4096, 6144]
TIERS = {"sbmem12": 12, "sbmem24": 24}
STAGE = re.compile(r"=== Stage connections=(\d+) .*?===\n(.*?)(?=^END_C)", re.S | re.M)


def parse_log(path):
    text = path.read_text(errors="replace")
    if "Benchmark Complete" not in text:
        return None
    ver = re.search(r"^Server-Version: (.+)$", text, re.M)
    v = ver.group(1) if ver else ""
    heap = re.search(r"heap_max_mb (\d+)", v)
    entries = re.search(r"entries (\d+)", v)
    out = {"heap_mb": int(heap.group(1)) if heap else None,
           "live_mb": int(entries.group(1)) * 4 // 1024 if entries else None, "stages": {}}
    for c, body in STAGE.findall(text):
        w = parse_wrk_block(body) or {}
        st = re.search(rf"^STATS_C{c}: (\{{.*\}})$", text, re.M)
        try:
            s = json.loads(st.group(1)) if st else {}
        except json.JSONDecodeError:
            s = {}
        timeouts = re.search(r"timeout (\d+)", body)
        stage = {"rps": w.get("rps"), "p99_ms": w.get("p99_ms"), "p50_ms": w.get("p50_ms"), "errors": w.get("errors"),
                 "timeouts": int(timeouts.group(1)) if timeouts else 0,
                 "gc_max_ms": s.get("gc_pause_max_ms"), "gc_total_ms": s.get("gc_pause_total_ms"),
                 "gc_over100": s.get("gc_pause_over100ms"), "old_after_gc_mb": s.get("old_after_gc_mb"),
                 "inflight_peak": s.get("inflight_peak"), "cpu_pct": s.get("proc_cpu_pct"), "stats_ok": "error" not in s and bool(s)}
        stage["slo_ok"] = bool(stage["rps"] and stage["p99_ms"] is not None and stage["p99_ms"] <= SLO_P99_MS
                               and not stage["errors"] and stage["stats_ok"])
        out["stages"][int(c)] = stage
    return out


def build():
    tiers = {}
    for tier, heap_gb in TIERS.items():
        insts = {}
        for name in canonical_instances():
            d = RESULTS_DIR / f"{tier}-remote" / name
            runs = [r for r in (parse_log(lp) for lp in sorted(d.glob("run*.log"))) if r] if d.is_dir() else []
            if not runs:
                continue
            caps = []
            for r in runs:
                ok = [c for c in STAGES if r["stages"].get(c, {}).get("slo_ok")]
                # 단계는 순서대로 커지므로 '연속으로' 통과한 최댓값(중간 실패 후 우연 통과는 무시)
                cap = 0
                for c in STAGES:
                    if c in ok:
                        cap = c
                    else:
                        break
                caps.append(cap)
            stage_med = {}
            for c in STAGES:
                vals = [r["stages"][c] for r in runs if c in r["stages"]]
                if not vals:
                    continue
                med = lambda k: (round(statistics.median([v[k] for v in vals if v.get(k) is not None]), 1)  # noqa: E731
                                 if any(v.get(k) is not None for v in vals) else None)
                stage_med[str(c)] = {"rps": med("rps"), "p99_ms": med("p99_ms"), "gc_max_ms": med("gc_max_ms"),
                                     "gc_total_ms": med("gc_total_ms"), "old_after_gc_mb": med("old_after_gc_mb"),
                                     "inflight_peak": med("inflight_peak"), "cpu_pct": med("cpu_pct"),
                                     "errors": sum((v.get("errors") or 0) for v in vals),
                                     "slo_pass": sum(1 for v in vals if v["slo_ok"]), "runs": len(vals)}
            insts[name] = {"heap_mb": runs[0]["heap_mb"], "live_mb": runs[0]["live_mb"],
                           "fit": "full" if (runs[0]["heap_mb"] or 0) >= heap_gb * 1024 * 0.97 else "reduced",
                           "capacity": int(statistics.median(caps)), "capacity_runs": caps, "stages": stage_med}
        tiers[tier] = insts

    # analysis 블록: 지표 = 버틴 커넥션 수(회차별) — 판정·짝 비교·가격 대비 성능을 다른 탭과 같은 틀로
    rep, specs = {}, {}
    for tier, insts in tiers.items():
        key = f"{tier}_capacity"
        rep[key] = {n: v["capacity_runs"] for n, v in insts.items() if any(v["capacity_runs"])}
        specs[key] = {"label": f"힙 {TIERS[tier]}GB · 버틴 동시 커넥션", "unit": "커넥션", "direction": "max", "memory_sensitive": True}
    rep = {k: v for k, v in rep.items() if v}
    summaries, blocks = analysis.report(rep, {k: specs[k] for k in rep}, PRICE) if rep else ({}, {})
    instances = {}
    for tier, insts in tiers.items():
        for n, v in insts.items():
            instances.setdefault(n, {})[tier] = v
    for n, r in summaries.items():
        instances[n]["r"] = r
    first = next(iter(blocks), None)
    return {
        "benchmark": "springboot-memory",
        "coverage": len(instances),
        "headline": {"field": f"r.{first}.value" if first else "sbmem12.capacity", "direction": "max",
                     "label": "버틴 동시 커넥션 (힙 12GB)", "unit": "커넥션",
                     # 종합 판정표: 메모리가 충분한 패밀리끼리 비교(C는 힙을 줄인 상태라 기준으로 부적합)
                     "matrix_rows": [{"key": "sbmem12_capacity", "name": "웹 · Spring Boot 메모리 (힙 12GB)", "family": "m"},
                                     {"key": "sbmem24_capacity", "name": "웹 · Spring Boot 메모리 (힙 24GB)", "family": "r"}]},
        "notes": {
            "method": ("상주 캐시(힙의 50%) + 운영형 요청(64KB 본문 → 1MB 작업 객체, 상주 캐시 1항목 교체, 1초 대기) — 커넥션 256/1024/2048/3072/4096/6144 각 60s. G1GC, 힙 고정(-Xms=-Xmx), AlwaysPreTouch, 가상 스레드."),
            "slo": f"단계 통과 = p99 <= {SLO_P99_MS}ms, 오류·타임아웃 0(사용자 체감 기준). GC 정지 비율·최대 정지는 참고값. 버틴 커넥션 = 연속 통과한 최고 단계",
            "fit": "fit=reduced: RAM이 부족해 기동 스크립트가 힙(RAM - 2.5GB)과 상주 캐시(힙의 50%)를 줄인 인스턴스",
        },
        "tiers": tiers,
        "analysis": blocks,
        "instances": instances,
    }
