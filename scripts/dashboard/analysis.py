"""리포트형 분석 레이어 — 벤치마크 파서가 만든 '인스턴스별 회차 값'을 판단 가능한 숫자로 바꾼다.

graviton-intel-springboot-benchmark.pdf(외부 재측정 리포트)의 분석 구조를 54+개 인스턴스·전 벤치마크에
일반화한 것. 모든 비율은 여기서 한 번만 계산해 site/data/<name>.json의 `analysis`에 넣고, 탭 JS는
그리기만 한다(수치 검증 지점을 한 곳으로 모으기 위함).

용어
  - value: 회차 값들의 **중앙값**(평균 아님 — 호스트 변동 등 이상 회차에 덜 민감)
  - cv: 회차 간 변동계수(모표준편차/평균, %)
  - perf: 기준선 대비 성능 배수. direction='min'(지연·기동시간)이면 base/value로 뒤집어 항상 >1이 좋음
  - ppd: 가격 대비 성능 배수 = perf / (price / base_price)
  - 판정: ppd >= 1+BAND 이면 왼쪽(예: Graviton) 우위, <= 1-BAND 이면 오른쪽 우위, 사이는 '비슷'.
    BAND=5%의 근거: SpringBoot Graviton 16개를 같은 설정(C2 전용)으로 다른 세션에서 재측정한 결과
    |Δ| 중앙값 2.6%, p75 6.7%, 최대 12.1%(r6g), 16개 중 11개가 ±5% 이내였다(parsers/springboot.py
    session_drift). 즉 ±5%는 '대부분의 재측정 노이즈' 수준이며, 5~12% 차이도 단일 호스트 측정이면
    노이즈일 수 있다 — 판정은 방향 표시이고 확정이 아니다.
"""
import statistics

BASELINE = "c7i.xlarge"
BAND = 0.05
# 신뢰도 경고 임계값은 '지표 자신의 분포' 기준으로 정한다 — 기동 시간처럼 원래 흔들리는 지표(CV 중앙값
# 3.5%)와 처리량(중앙값 1% 안팎)에 같은 고정값을 쓰면 한쪽은 전부 경고, 다른 쪽은 경고가 안 걸린다.
#   CV 임계 = max(CV_WARN, 그 지표 CV 중앙값 x 2), 회차 max/min 임계 = max(SPREAD_WARN, 1 + (중앙값-1) x 2)
CV_WARN = 3.0
SPREAD_WARN = 1.10
PEER_WARN = 0.15       # 같은 프로세서 짝의 성능 차이가 ±15%를 넘으면 호스트 차이 의심

# 같은 세대·같은 패밀리 Graviton/Intel 짝 (xlarge 이름 규칙). 존재하는 것만 사용된다.
PAIR_SPECS = (
    [(f"{f}{g}g.xlarge", f"{f}{g}i.xlarge", f"{g}세대") for g in (6, 7, 8) for f in "cmr"]
    + [("c9g.xlarge", "c8i.xlarge", "최신(Graviton5 vs Intel 8세대)")]
)
AMD_PAIRS = [(f"{f}5a.xlarge", f"{f}5.xlarge", "5세대") for f in "cmr"]
FLEX_PAIRS = [("c7i-flex.xlarge", "c7i.xlarge", "7세대"), ("m7i-flex.xlarge", "m7i.xlarge", "7세대"),
              ("c8i-flex.xlarge", "c8i.xlarge", "8세대"), ("m8i-flex.xlarge", "m8i.xlarge", "8세대"),
              ("r8i-flex.xlarge", "r8i.xlarge", "8세대")]
# 세대 교체 체인 (패밀리별, 같은 벤더 계열)
UPLIFT_CHAINS = (
    [[f"{f}5.xlarge", f"{f}6i.xlarge", f"{f}7i.xlarge", f"{f}8i.xlarge"] for f in "cmr"]
    + [["c6g.xlarge", "c7g.xlarge", "c8g.xlarge", "c9g.xlarge"]]
    + [[f"{f}6g.xlarge", f"{f}7g.xlarge", f"{f}8g.xlarge"] for f in "mr"]
)
# 같은 프로세서의 C/M/R (메모리 2배씩, 가격 상승 대비 성능이 따라오는지)
FAMILY_SETS = [["c8i.xlarge", "m8i.xlarge", "r8i.xlarge"], ["c8g.xlarge", "m8g.xlarge", "r8g.xlarge"],
               ["c7i.xlarge", "m7i.xlarge", "r7i.xlarge"], ["c7g.xlarge", "m7g.xlarge", "r7g.xlarge"]]


def summarize(runs):
    """회차 값 리스트 -> {value(중앙값), cv, n, min, max, runs}. 비어 있으면 None."""
    runs = [float(v) for v in runs if v is not None]
    if not runs:
        return None
    mean = statistics.fmean(runs)
    cv = statistics.pstdev(runs) / mean * 100 if len(runs) > 1 and mean else 0.0
    return {"value": round(statistics.median(runs), 4), "cv": round(cv, 2), "n": len(runs),
            "min": round(min(runs), 4), "max": round(max(runs), 4), "runs": [round(v, 4) for v in runs]}


def _perf(value, base, direction):
    if value is None or base is None or value <= 0 or base <= 0:
        return None
    return value / base if direction == "max" else base / value


def verdict(ratio, left="Graviton", right="Intel"):
    if ratio is None:
        return None
    if ratio >= 1 + BAND:
        return f"{left} 우위"
    if ratio <= 1 - BAND:
        return f"{right} 우위"
    return "비슷"


def _ratio_row(a, b, stats, prices, direction):
    sa, sb = stats.get(a), stats.get(b)
    if not sa or not sb:
        return None
    perf = _perf(sa["value"], sb["value"], direction)
    price = prices[a] / prices[b]
    return {"left": a, "right": b, "perf": round(perf, 4), "price": round(price, 4),
            "ppd": round(perf / price, 4)}


def pair(stats, prices, left, right, direction="max", lname="Graviton", rname="Intel"):
    """기준선 없이 두 인스턴스만 비교할 때(부분 측정 세트 등). analyze()의 짝 비교와 같은 정의."""
    r = _ratio_row(left, right, stats, prices, direction)
    if r:
        r["verdict"] = verdict(r["ppd"], lname, rname)
        r["perf_verdict"] = verdict(r["perf"], lname, rname)
    return r


def analyze(stats, prices, metric, cost_unit=None, peer_families=True, known_suspects=None, baseline=None):
    """stats: {instance: summarize(...)}, prices: {instance: USD/hr}.

    metric: {field, label, unit, direction}. cost_unit: 처리량 지표일 때 '작업 1단위당 비용' 환산
    {per: 1e9, label: '요청 10억 건당'} — value가 초당 처리량이라고 가정(USD = price/3600/value*per).
    """
    direction = metric["direction"]
    baseline = baseline or BASELINE   # 지표별 기준선(spec "baseline") — 없으면 전 탭 공통 c7i.xlarge
    base = stats.get(baseline)
    base_value = base["value"] if base else None
    base_price = prices[baseline]

    present = [s for s in stats.values() if s]
    cv_thr = max(CV_WARN, 2 * statistics.median(s["cv"] for s in present)) if present else CV_WARN
    spreads = [s["max"] / s["min"] for s in present if s["n"] > 1 and s["min"] > 0]
    spread_thr = max(SPREAD_WARN, 1 + 2 * (statistics.median(spreads) - 1)) if spreads else SPREAD_WARN

    table = {}
    for name, s in stats.items():
        if not s:
            continue
        perf = _perf(s["value"], base_value, direction)
        row = {**s, "perf": round(perf, 4) if perf else None,
               "ppd": round(perf / (prices[name] / base_price), 4) if perf else None,
               "flags": []}
        if s["cv"] > cv_thr:
            row["flags"].append(f"회차 간 변동계수 {s['cv']:.1f}%")
        if s["n"] > 1 and s["min"] > 0 and s["max"] / s["min"] > spread_thr:
            row["flags"].append(f"회차 최대/최소 {s['max'] / s['min']:.2f}배")
        if cost_unit and direction == "max" and s["value"] > 0:
            row["cost"] = round(prices[name] / 3600 / s["value"] * cost_unit["per"], 4)
        table[name] = row

    def rows_for(specs, left, right):
        out = []
        for spec in specs:
            a, b = spec[0], spec[1]
            r = _ratio_row(a, b, stats, prices, direction)
            if r:
                r["group"] = spec[2] if len(spec) > 2 else ""
                r["verdict"] = verdict(r["ppd"], left, right)
                r["perf_verdict"] = verdict(r["perf"], left, right)
                out.append(r)
        return out

    uplift = []
    for chain in UPLIFT_CHAINS:
        present = [c for c in chain if stats.get(c)]
        steps = []
        for a, b in zip(present, present[1:]):
            r = _ratio_row(b, a, stats, prices, direction)   # 신세대 / 구세대
            steps.append({"from": a, "to": b, "perf": r["perf"], "price": r["price"], "ppd": r["ppd"]})
        if steps:
            uplift.append({"chain": present, "steps": steps})

    families = []
    for fam in FAMILY_SETS:
        present = [f for f in fam if stats.get(f)]
        if len(present) < 2:
            continue
        families.append([{"name": f, **_ratio_row(f, present[0], stats, prices, direction)} for f in present])

    # 같은 프로세서 짝(flex/표준, 같은 세대 C/M/R)은 성능이 비슷해야 정상 — ±PEER_WARN 밖이면
    # 회차 변동(CV)으로는 안 잡히는 '호스트 차이' 의심(예: SpringBoot c7i-flex 1.38배 vs c7i).
    peer_outliers = []
    # peer_families=False: 메모리 용량이 결과를 좌우하는 지표(ClickHouse 13.4GiB 데이터셋, ES 힙=RAM 60%,
    # Kafka page cache)는 C/M/R 차이가 정상이므로 같은 프로세서 C/M/R 검사를 끈다(flex/표준은 메모리가 같아 유지).
    same_proc = [(a, b) for a, b, _ in FLEX_PAIRS] + ([(f[0], o) for f in FAMILY_SETS for o in f[1:]] if peer_families else [])
    for a, b in same_proc:
        r = _ratio_row(a, b, stats, prices, direction)
        if r and abs(r["perf"] - 1) > PEER_WARN:
            peer_outliers.append({"left": a, "right": b, "perf": r["perf"]})
            for n in (a, b):
                table[n]["flags"].append(f"같은 프로세서 {b if n == a else a}와 {r['perf']:.2f}배 차이")

    suspects = {n for o in peer_outliers for n in (o["left"], o["right"])}
    # known_suspects = {"names": [...], "reason": "..."}: 문서화된 알려진 이상(예: Kafka 베이스라인 고지연 11개)
    if known_suspects:
        for n in known_suspects["names"]:
            if n in table:
                table[n]["flags"].append(known_suspects["reason"])
                suspects.add(n)

    def mark(pairs):
        """같은 프로세서 이상치가 낀 짝은 판정을 보류한다 — 호스트 차이를 아키텍처 차이로 읽지 않기 위해."""
        for q in pairs:
            if (q["left"] in suspects and q["right"] in suspects) or (known_suspects and (q["left"] in known_suspects["names"] or q["right"] in known_suspects["names"])):
                q["verdict"] = q["perf_verdict"] = "재측정 필요"
        return pairs

    ranked = sorted((n for n in table if table[n]["perf"] is not None),
                    key=lambda n: table[n]["perf"], reverse=True)
    ranked_ppd = sorted((n for n in table if table[n]["ppd"] is not None),
                        key=lambda n: table[n]["ppd"], reverse=True)
    return {
        "metric": metric,
        "baseline": baseline,
        "baseline_value": base_value,
        "band": BAND,
        "cost_unit": cost_unit,
        "table": table,
        "rank_perf": ranked,
        "rank_ppd": ranked_ppd,
        "pairs": mark(rows_for(PAIR_SPECS, "Graviton", "Intel")),
        "amd_pairs": mark(rows_for(AMD_PAIRS, "AMD", "Intel")),
        "flex_pairs": mark(rows_for(FLEX_PAIRS, "flex", "표준")),
        "uplift": uplift,
        "families": families,
        "peer_outliers": peer_outliers,
        "thresholds": {"cv": round(cv_thr, 2), "spread": round(spread_thr, 3), "peer": PEER_WARN},
        "memory_sensitive": not peer_families,
        "known_suspects": known_suspects,
        "flagged": sorted(n for n in table if table[n]["flags"]),
    }


def report(runs_by_metric, specs, prices):
    """파서용 헬퍼: 지표별 회차 리스트 -> (인스턴스별 요약, 지표별 analyze 결과).

    runs_by_metric = {key: {instance: [회차 값...]}}
    specs = {key: {"label", "unit", "direction", "cost_unit"?}}
    반환: summaries = {instance: {key: summarize(...)}}, blocks = {key: analyze(...)}
    파서는 instances[name]["r"] = summaries[name], envelope["analysis"] = blocks 로 붙인다.
    """
    summaries, blocks = {}, {}
    for key, per_inst in runs_by_metric.items():
        spec = specs[key]
        stats = {}
        for inst, runs in per_inst.items():
            s = summarize(runs)
            if s:
                stats[inst] = s
                summaries.setdefault(inst, {})[key] = s
        if stats:
            blocks[key] = analyze(stats, prices, {"field": f"r.{key}.value", **{k: spec[k] for k in ("label", "unit", "direction")}},
                                  cost_unit=spec.get("cost_unit"), peer_families=not spec.get("memory_sensitive", False),
                                  known_suspects=spec.get("known_suspects"), baseline=spec.get("baseline"))
    return summaries, blocks
