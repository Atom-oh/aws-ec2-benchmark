#!/usr/bin/env python3
"""
ClickHouse ClickBench 리포트 데이터 파서.

results/clickhouse/<instance>/setN.log (설계 §10 포맷)를 파싱해 인스턴스별로 집계하고,
results/clickhouse/report-charts.html 의 __CLICKHOUSE_DATA__ placeholder에 JSON을 주입한다.
또한 results/clickhouse/data.json 으로도 저장.

빈 입력(로그 없음)에도 graceful — 빈 데이터로 처리.
"""
import json
import re
import statistics
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
RESULTS_DIR = BASE_DIR / "results" / "clickhouse"
HTML_FILE = RESULTS_DIR / "report-charts.html"
JSON_FILE = RESULTS_DIR / "data.json"
INSTANCE_FILE = BASE_DIR / "config" / "instances-4vcpu.txt"

DATASET_BYTES = 13.44 * 1024 * 1024 * 1024  # 13.44 GiB hits on-disk

NQUERIES = 43

# On-demand 시간당 가격 (USD, ap-northeast-2) — nginx/redis 리포트와 동일 출처
PRICE = {
    "c5.xlarge": 0.192, "c5a.xlarge": 0.172, "c5d.xlarge": 0.220, "c5n.xlarge": 0.244,
    "c6g.xlarge": 0.154, "c6gd.xlarge": 0.176, "c6gn.xlarge": 0.195, "c6i.xlarge": 0.192,
    "c6id.xlarge": 0.231, "c6in.xlarge": 0.256, "c7g.xlarge": 0.163, "c7gd.xlarge": 0.208,
    "c7i-flex.xlarge": 0.192, "c7i.xlarge": 0.202, "c8g.xlarge": 0.180, "c8gn.xlarge": 0.268,
    "c8i-flex.xlarge": 0.201, "r8gd.xlarge": 0.353, "m8i-flex.xlarge": 0.247,
    "c8i.xlarge": 0.212, "m5.xlarge": 0.236, "m5a.xlarge": 0.212, "m5ad.xlarge": 0.254,
    "m5d.xlarge": 0.278, "m5zn.xlarge": 0.406, "m6g.xlarge": 0.188, "m6gd.xlarge": 0.222,
    "m6i.xlarge": 0.236, "m6id.xlarge": 0.292, "m6idn.xlarge": 0.386, "m6in.xlarge": 0.337,
    "m7g.xlarge": 0.201, "m7gd.xlarge": 0.263, "m7i-flex.xlarge": 0.235, "m7i.xlarge": 0.248,
    "m8g.xlarge": 0.221, "m8i.xlarge": 0.260, "r5.xlarge": 0.304, "r5a.xlarge": 0.272,
    "r5ad.xlarge": 0.316, "r5b.xlarge": 0.356, "r5d.xlarge": 0.346, "r5dn.xlarge": 0.398,
    "r5n.xlarge": 0.356, "r6g.xlarge": 0.244, "r6gd.xlarge": 0.277, "r6i.xlarge": 0.304,
    "r6id.xlarge": 0.363, "r7g.xlarge": 0.258, "r7gd.xlarge": 0.327, "r7i.xlarge": 0.319,
    "r8g.xlarge": 0.284, "r8i-flex.xlarge": 0.318, "r8i.xlarge": 0.335,
}


def load_instance_meta():
    """instance -> {arch, mem_mb} (instances-4vcpu.txt: type<TAB>arch<TAB>mem_mb)."""
    meta = {}
    if not INSTANCE_FILE.exists():
        return meta
    for line in INSTANCE_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 3:
            meta[parts[0]] = {"arch": parts[1], "mem_mb": int(parts[2])}
    return meta


def gen_family(instance):
    """세대/패밀리/아키텍처 분류 (instance 이름 기반).

    prefix = '.' 앞부분 (예: c5ad, c8g, m7i-flex). [cmr]<gen><suffix-letters>.
    - suffix에 g 포함 → Graviton (gen 6/7/8 → Graviton2/3/4)
    - suffix가 a로 시작 → AMD
    - 그 외 → Intel
    """
    fam = instance[0].upper() if instance else "?"
    prefix = instance.split(".")[0]          # c5ad-... 형태 방지: '.' 기준
    m = re.match(r"^([cmr])(\d+)([a-z\-]*)", prefix)   # \d+ : 미래 두자리 세대 대비
    gen = m.group(2) if m else "?"
    suffix = m.group(3) if m else ""
    if suffix.startswith("g"):                          # Graviton suffix는 g/gd/gn
        arch = "Graviton"
        label = {"6": "Graviton2", "7": "Graviton3", "8": "Graviton4"}.get(gen, "Graviton")
    elif suffix.startswith("a"):
        arch = "AMD"
        label = "AMD"
    else:
        arch = "Intel"
        label = f"Intel {gen}th"
    return {"arch": arch, "label": label, "gen": gen, "family": fam}


def parse_log(path):
    """단일 setN.log → dict(per-query hot ms 리스트, insert_rps, join_ms, failed)."""
    text = path.read_text(errors="replace")
    out = {"queries": {}, "insert_rps": None, "join_ms": None, "failed": 0,
           "version": None, "arch": None}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("SERVER_VERSION:"):
            out["version"] = line.split(":", 1)[1].strip()
        elif line.startswith("ARCH:"):
            out["arch"] = line.split(":", 1)[1].strip()
        elif re.match(r"^q\d+,", line):
            # qNN,1,cold,hot1,hot2  (값이 FAILED:* 이면 실패)
            cols = line.split(",")
            qid = cols[0]
            vals = cols[2:]  # cold, hot1, hot2
            if any("FAILED" in v for v in vals) or any(v == "SKIPPED" for v in vals):
                out["failed"] += 1
                continue
            try:
                hot = [int(v) for v in vals[1:] if v.isdigit()]  # hot1, hot2
                if hot:
                    out["queries"].setdefault(qid, []).append(min(hot))
            except ValueError:
                out["failed"] += 1
        elif line.startswith("INSERT_ROWS_PER_SEC:"):
            v = line.split(":", 1)[1].strip()
            if v.isdigit() and int(v) > 0:
                out["insert_rps"] = int(v)
        elif line.startswith("JOIN_MS:"):
            v = line.split(":", 1)[1].strip()
            if v.isdigit():
                out["join_ms"] = int(v)
            else:
                out["failed"] += 1
    return out


def aggregate():
    meta = load_instance_meta()
    instances = {}
    if RESULTS_DIR.exists():
        for inst_dir in sorted(RESULTS_DIR.iterdir()):
            if not inst_dir.is_dir():
                continue
            logs = sorted(inst_dir.glob("set*.log"))
            logs = [p for p in logs if p.stat().st_size > 0]
            if not logs:
                continue
            instance = inst_dir.name
            q_hot = {}      # qid -> list of best-hot across sets
            insert_rps, join_ms, failed = [], [], 0
            version = None
            for lp in logs:
                r = parse_log(lp)
                version = version or r["version"]
                failed += r["failed"]
                for qid, vals in r["queries"].items():
                    q_hot.setdefault(qid, []).extend(vals)
                if r["insert_rps"]:
                    insert_rps.append(r["insert_rps"])
                if r["join_ms"] is not None:
                    join_ms.append(r["join_ms"])
            # per-query: median of best-hot across sets; total = sum
            per_q = {q: round(statistics.median(v)) for q, v in q_hot.items() if v}
            # 공정성: 43쿼리가 모두 측정된 경우에만 hot_total 산출 (잘린 로그가
            # 부분 합으로 인위적으로 빨라 보이는 것 방지). 누락분은 실패로 계상.
            if len(per_q) >= NQUERIES:
                hot_total_ms = sum(per_q.values())
            else:
                hot_total_ms = None
                failed += NQUERIES - len(per_q)
            cls = gen_family(instance)
            mem_mb = meta.get(instance, {}).get("mem_mb")
            price = PRICE.get(instance)
            hot_s = hot_total_ms / 1000 if hot_total_ms else None
            # speed score: 데이터셋(43쿼리) 처리율 환산 (높을수록 좋음). value = speed/price.
            speed = round(1000 / hot_s, 2) if hot_s else None
            value = round(speed / price, 2) if (speed and price) else None
            instances[instance] = {
                "instance": instance,
                "arch": cls["arch"],
                "label": cls["label"],
                "gen": cls["gen"],
                "family": cls["family"],
                "mem_mb": mem_mb,
                "fits_in_ram": (mem_mb * 1024 * 1024 > DATASET_BYTES) if mem_mb else None,
                "price": price,
                "version": version,
                "hot_total_ms": hot_total_ms,
                "hot_total_s": round(hot_s, 2) if hot_s else None,
                "speed": speed,              # 1000/hot_s (높을수록 빠름)
                "value": value,              # speed/$ (가성비, 높을수록 좋음)
                "queries_measured": len(per_q),
                "per_query_ms": per_q,
                "insert_rps": round(statistics.median(insert_rps)) if insert_rps else None,
                "join_ms": round(statistics.median(join_ms)) if join_ms else None,
                "failed_count": failed,
            }
    return instances


def load_queries():
    """queries.sql(43줄) + insert.sql + join.sql 원문을 리포트에 주입."""
    qdir = BASE_DIR / "benchmarks" / "clickhouse" / "queries"
    out = {"clickbench": [], "insert": "", "join": ""}
    qf = qdir / "queries.sql"
    if qf.exists():
        lines = [ln.strip() for ln in qf.read_text().splitlines() if ln.strip()]
        out["clickbench"] = [{"id": f"q{i:02d}", "sql": ln} for i, ln in enumerate(lines)]
    for k, fn in (("insert", "insert.sql"), ("join", "join.sql")):
        p = qdir / fn
        if p.exists():
            # 주석(--) 제외한 SQL 본문
            out[k] = "\n".join(ln for ln in p.read_text().splitlines() if not ln.strip().startswith("--")).strip()
    return out


def main():
    data = aggregate()
    payload = {
        "dataset": "ClickBench hits (~100M rows, 13.44GiB)",
        "note_ebs": "per-instance EBS 대역폭 상한이 교란변수. hot_total은 memory>=dataset(fits_in_ram=true) 인스턴스에서만 순수 page-cache-bound.",
        "instances": data,
        "queries": load_queries(),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    JSON_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"파싱 완료: {len(data)} 인스턴스 → {JSON_FILE}")

    if HTML_FILE.exists():
        html = HTML_FILE.read_text()
        blob = json.dumps(payload, ensure_ascii=False)
        # ch-data 스크립트 내용을 매번 교체 (재실행 가능 — placeholder 소진 방지)
        pattern = re.compile(
            r'(<script id="ch-data" type="application/json">)(.*?)(</script>)',
            re.DOTALL,
        )
        if pattern.search(html):
            html = pattern.sub(lambda m: m.group(1) + blob + m.group(3), html, count=1)
            HTML_FILE.write_text(html)
            print(f"리포트 데이터 주입 완료 → {HTML_FILE}")
            # 발행본 복사 (reports/ 컨벤션, 자체완결 — Chart.js 인라인 포함)
            pub = BASE_DIR / "reports" / "clickhouse-report.html"
            if pub.parent.exists():
                pub.write_text(html)
                print(f"발행본 생성 → {pub}")
        elif "__CLICKHOUSE_DATA__" in html:
            html = html.replace("__CLICKHOUSE_DATA__", blob)
            HTML_FILE.write_text(html)
            print(f"리포트 데이터 주입 완료 → {HTML_FILE}")
        else:
            print("ⓘ report-charts.html 에 ch-data 스크립트/placeholder 없음 (주입 생략)")
    else:
        print("ⓘ report-charts.html 없음 (JSON만 생성)")


if __name__ == "__main__":
    main()
