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

from common import RESULTS_DIR, canonical_instances, geomean, mean, parse_wrk_block

STACKS = ["fastapi", "django", "node", "go", "dotnet"]
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

    coverage = sum(1 for v in instances.values() if v["json_geomean"] is not None)
    return {
        "benchmark": "web",
        "coverage": coverage,
        "headline": {"field": "json_geomean", "direction": "max",
                     "label": "JSON req/s (5개 스택 기하평균)", "unit": "req/s"},
        "notes": {
            "method": ("TechEmpower 방식 /plaintext, /json, /compute(SHA-256 2000회 체인) — wrk -t6 -c128 -d30s "
                       "(+ /json -c512), 파이프라이닝 없음, 5회 평균. 서버=대상 인스턴스 단독(워커=4 vCPU), "
                       "클라이언트=c6in.2xlarge 같은 AZ"),
            "stacks": STACK_LABELS,
            "versions": versions,
            "caveat": ("스택 간 절대값 비교는 프레임워크 오버헤드 비교이고, 인스턴스 비교는 같은 스택 안에서 할 것. "
                       "headline 기하평균은 5개 스택을 동등 가중"),
        },
        "instances": instances,
    }
