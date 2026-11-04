"""다언어 웹 프레임워크(TechEmpower 방식) wrk 원시 로그 파서.

results/web-<stack>-remote/<instance>/run<N>.log (stack = fastapi/django/node/go/dotnet).
로그는 benchmarks/web/web-benchmark-remote.yaml이 생성 — 섹션 4개:
  endpoint=plaintext|json|compute (6 threads, 128 connections) + endpoint=json (512 connections).
`Benchmark Complete` 마커가 없는 로그(타임아웃 등으로 중간에 끊김)는 제외.

headline = json_geomean: 5개 스택 /json(128c) req/s의 기하평균. 스택마다 처리량 규모가 10배 이상
달라(Go/.NET ≫ Django) 산술평균이면 빠른 스택이 점수를 독점하므로 기하평균으로 각 스택을 동등 가중.
5개 스택이 모두 있어야 계산(하나라도 빠지면 None → coverage에서 제외).
"""
import re
from collections import defaultdict

import analysis
from common import PRICE, RESULTS_DIR, canonical_instances, geomean, mean, parse_wrk_block

ALL_STACKS = ["fastapi", "django", "node", "go", "dotnet"]
RUNS = 5


def complete_stacks():
    """모든 정본 인스턴스가 RUNS회 완료(`Benchmark Complete`)된 스택만 반환 — 측정 중인 스택이 일부
    인스턴스만으로 종합 지수·판정에 섞이지 않게 한다. 측정이 끝나면 재빌드만으로 자동 포함된다."""
    names = canonical_instances()
    done = []
    for st in ALL_STACKS:
        base = RESULTS_DIR / f"web-{st}-remote"
        ok = all(sum(1 for lp in (base / n).glob("run*.log") if "Benchmark Complete" in lp.read_text(errors="replace")) >= RUNS
                 for n in names) if base.is_dir() else False
        if ok:
            done.append(st)
    return done


STACKS = complete_stacks()
PENDING = [s for s in ALL_STACKS if s not in STACKS]
STACK_LABELS = {
    "fastapi": "FastAPI + uvicorn",
    "django": "Django + gunicorn",
    "node": "Node.js + Fastify",
    "go": "Go net/http",
    "dotnet": "ASP.NET Core",
}
SECTION = re.compile(
    r"=== wrk Test \(endpoint=(\w+), \d+ threads, (\d+) connections, 30s\) ===\n(.*?)(?=\n===|\nBenchmark Complete|\Z)",
    re.S,
)
# (endpoint, connections) -> 출력 키
KEYS = {("plaintext", "128"): "plaintext", ("json", "128"): "json",
        ("compute", "128"): "compute", ("json", "512"): "json512"}


def parse_log(path):
    text = path.read_text(errors="replace")
    if "Benchmark Complete" not in text:
        return None, None
    version = re.search(r"^Server-Version:\s*(.+)$", text, re.M)
    out = {}
    for ep, conns, body in SECTION.findall(text):
        key = KEYS.get((ep, conns))
        block = parse_wrk_block(body) if key else None
        if block:
            out[key] = block
    return out, (version.group(1).strip() if version else None)


def build_stack(stack, instance):
    inst_dir = RESULTS_DIR / f"web-{stack}-remote" / instance
    if not inst_dir.is_dir():
        return None, None
    runs = defaultdict(lambda: defaultdict(list))
    version = None
    for lp in sorted(inst_dir.glob("run*.log")):
        parsed, ver = parse_log(lp)
        if not parsed:
            continue
        version = version or ver
        for key, block in parsed.items():
            for metric, value in block.items():
                runs[key][metric].append(value)
    if "json" not in runs:
        return None, version
    rec = {k: mean(runs[k]["rps"]) for k in KEYS.values() if k in runs}
    rec["lat_json_ms"] = mean(runs["json"]["lat_avg_ms"])
    rec["p99_json_ms"] = mean(runs["json"]["p99_ms"])
    if "json512" in runs:
        rec["p99_json512_ms"] = mean(runs["json512"]["p99_ms"])
    rec["errors"] = sum(sum(v for v in runs[k]["errors"] if v) for k in runs)
    rec["runs"] = len(runs["json"]["rps"])
    rec["_json_runs"] = runs["json"]["rps"]  # 회차 순서 유지(run1..5) — 종합 지수 회차별 기하평균용
    rec["_compute_runs"] = runs["compute"]["rps"] if "compute" in runs else []
    rec["_plain_runs"] = runs["plaintext"]["rps"] if "plaintext" in runs else []
    return rec, version


def build():
    instances = {}
    versions = {}
    for name in canonical_instances():
        rec = {}
        for stack in STACKS:
            s, ver = build_stack(stack, name)
            if s:
                rec[stack] = s
            if ver and stack not in versions:
                versions[stack] = ver
        if not rec:
            continue
        rec["json_geomean"] = geomean([rec.get(s, {}).get("json") for s in STACKS])
        rec["plaintext_geomean"] = geomean([rec.get(s, {}).get("plaintext") for s in STACKS])
        rec["compute_geomean"] = geomean([rec.get(s, {}).get("compute") for s in STACKS])
        instances[name] = rec

    # 리포트 분석: 스택별 /json(128c) 회차 값 + 종합 지수(회차 i마다 5개 스택 run i의 기하평균 — 스택별 측정은
    # 별개 세션이므로 회차 번호끼리 짝짓는 근사이며, 5개 스택이 모두 있는 회차만 사용)
    rep = {"json_geomean": {}, **{s: {} for s in STACKS},
           **{f"{s}_compute": {} for s in STACKS}, **{f"{s}_plaintext": {} for s in STACKS}}
    for name, rec in instances.items():
        for st in STACKS:
            if st in rec:
                rep[st][name] = rec[st]["_json_runs"]
                rep[f"{st}_compute"][name] = rec[st].pop("_compute_runs")
                rep[f"{st}_plaintext"][name] = rec[st].pop("_plain_runs")
        per = [rec[st]["_json_runs"] for st in STACKS if st in rec]
        if len(per) == len(STACKS):
            n = min(len(r) for r in per)
            rep["json_geomean"][name] = [geomean([r[i] for r in per]) for i in range(n)]
        for st in STACKS:
            rec.get(st, {}).pop("_json_runs", None)
    summaries, blocks = analysis.report(rep, {
        "json_geomean": {"label": f"웹 프레임워크 종합 지수 ({len(STACKS)}개 스택 /json 기하평균)", "unit": "req/s", "direction": "max"},
        **{st: {"label": f"{STACK_LABELS[st]} /json", "unit": "req/s", "direction": "max",
                "cost_unit": {"per": 1e9, "label": "요청 10억 건당 (USD)"}} for st in STACKS},
        **{f"{st}_compute": {"label": f"{STACK_LABELS[st]} /compute", "unit": "req/s", "direction": "max"} for st in STACKS},
        **{f"{st}_plaintext": {"label": f"{STACK_LABELS[st]} /plaintext", "unit": "req/s", "direction": "max"} for st in STACKS},
    }, PRICE)
    for _n, _r in summaries.items():
        instances[_n]["r"] = _r

    coverage = sum(1 for v in instances.values() if v["json_geomean"] is not None)
    return {
        "benchmark": "web",
        "coverage": coverage,
        "headline": {"field": "json_geomean", "direction": "max",
                     "label": f"JSON req/s ({len(STACKS)}개 스택 기하평균)", "unit": "req/s",
                     # 종합 탭 판정표는 이 벤치마크를 한 행이 아니라 스택별 행으로 그린다(스택마다 독립 워크로드)
                     "matrix_rows": [{"key": st, "name": f"웹 · {STACK_LABELS[st]}"} for st in STACKS]},
        "notes": {
            "method": ("TechEmpower 방식 /plaintext, /json, /compute(SHA-256 2000회 체인) — wrk -t6 -c128 -d30s "
                       "(+ /json -c512), 파이프라이닝 없음, 5회 평균. 서버=대상 인스턴스 단독(워커=4 vCPU), "
                       "클라이언트=c6in.2xlarge 같은 AZ"),
            "stacks": {k: STACK_LABELS[k] for k in STACKS},
            "pending_stacks": {k: STACK_LABELS[k] for k in PENDING},
            "versions": versions,
            "az": ("서버·클라이언트 기본 AZ ap-northeast-2c(2a의 클라이언트 c6in.2xlarge가 InsufficientInstanceCapacity). "
                   "2c에 오퍼링이 없는 c7i-flex/m6gd/m7gd/r6gd/r8gd와, 2c 용량 부족으로 기동 실패한 c8gn은 2b에서 측정"),
            "caveat": ("스택 간 절대값 비교는 프레임워크 오버헤드 비교이고, 인스턴스 비교는 같은 스택 안에서 할 것. "
                       f"headline 기하평균은 {len(STACKS)}개 스택을 동등 가중"),
        },
        "instances": instances,
        "analysis": blocks,
    }
