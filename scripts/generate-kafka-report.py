#!/usr/bin/env python3
"""
Kafka 벤치마크 리포트 데이터 파서 (베이스라인 + 포화 + 램프업 시나리오 종합).

- results/kafka/<instance>/runN.log: 베이스라인(싱글 producer/consumer, 무압축) 5회 중앙값.
- results/kafka-max/<instance>/<codec>-runN.log: 포화 시나리오(8-way 병렬, 토픽 압축
  uncompressed/lz4/zstd) 각 3회 중앙값. codec별로 instances[instance]["max"][codec]에 저장.
- results/kafka-ramp/<instance>/run1.log: 램프업/포화점/지연곡선 시나리오(Phase 3, 1회) —
  90초 버스트크레딧 고갈 후 8-way produce 목표치를 8단계로 올려 지연-대-처리량 곡선을 그리고
  실제/목표 비율 99.5% 미달 지점을 포화점으로 판정. instances[instance]["ramp"]에 저장.

세 데이터셋을 병합해 results/kafka/report-charts.html의 <script id="kafka-data"> 블록에 주입하고
results/kafka/data.json 으로도 저장. 빈 입력(로그 없음)에도 graceful — 빈 데이터로 처리.
"""
import json
import re
import statistics
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
RESULTS_DIR = BASE_DIR / "results" / "kafka"
MAX_RESULTS_DIR = BASE_DIR / "results" / "kafka-max"
RAMP_RESULTS_DIR = BASE_DIR / "results" / "kafka-ramp"
HTML_FILE = RESULTS_DIR / "report-charts.html"
JSON_FILE = RESULTS_DIR / "data.json"
INSTANCE_FILE = BASE_DIR / "config" / "instances-4vcpu.txt"

RECORDS = 5_000_000
RECORD_SIZE = 1024
DATASET_BYTES = RECORDS * RECORD_SIZE  # ~4.77 GiB per run (produce+consume 경로 통과량)

CODECS = ["uncompressed", "lz4", "zstd"]
MAX_FIELDS = {
    "PRODUCE_TOTAL_RECORDS_PER_SEC": "produce_records_per_sec",
    "PRODUCE_TOTAL_MB_PER_SEC": "produce_mb_per_sec",
    "PRODUCE_LAT_AVG_MS": "produce_lat_avg_ms",
    "PRODUCE_LAT_P99_MS": "produce_lat_p99_ms",
    "LOG_BYTES_ON_DISK": "log_bytes_on_disk",
    "COMPRESSION_RATIO": "compression_ratio",
    "CONSUME_TOTAL_MB_PER_SEC": "consume_mb_per_sec",
    "CONSUME_TOTAL_RECORDS_PER_SEC": "consume_records_per_sec",
}

# On-Demand 시간당 가격 (USD, ap-northeast-2) — clickhouse 리포트와 동일 출처
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

# 라인의 metric명 -> 저장 필드명 (숫자, FAILED/SKIPPED가 아닌 경우만 채움)
FIELDS = {
    "PRODUCE_RECORDS_PER_SEC": "produce_records_per_sec",
    "PRODUCE_MB_PER_SEC": "produce_mb_per_sec",
    "PRODUCE_LAT_AVG_MS": "produce_lat_avg_ms",
    "PRODUCE_LAT_P50_MS": "produce_lat_p50_ms",
    "PRODUCE_LAT_P95_MS": "produce_lat_p95_ms",
    "PRODUCE_LAT_P99_MS": "produce_lat_p99_ms",
    "PRODUCE_LAT_P999_MS": "produce_lat_p999_ms",
    "CONSUME_MB_PER_SEC": "consume_mb_per_sec",
    "CONSUME_RECORDS_PER_SEC": "consume_records_per_sec",
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
    """세대/패밀리/아키텍처 분류 (instance 이름 기반). clickhouse 리포트와 동일 규칙."""
    fam = instance[0].upper() if instance else "?"
    prefix = instance.split(".")[0]
    m = re.match(r"^([cmr])(\d+)([a-z\-]*)", prefix)
    gen = m.group(2) if m else "?"
    suffix = m.group(3) if m else ""
    if suffix.startswith("g"):
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
    """단일 runN.log -> dict(필드명 -> 숫자 값 또는 None), failed 카운트."""
    text = path.read_text(errors="replace")
    out = {v: None for v in FIELDS.values()}
    out["version"] = None
    failed = 0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("SERVER_VERSION:"):
            out["version"] = line.split(":", 1)[1].strip()
            continue
        for label, field in FIELDS.items():
            if line.startswith(label + ":"):
                val = line.split(":", 1)[1].strip()
                if val in ("SKIPPED",) or "FAILED" in val:
                    failed += 1
                else:
                    try:
                        out[field] = float(val)
                    except ValueError:
                        failed += 1
                break
    return out, failed


def aggregate():
    meta = load_instance_meta()
    instances = {}
    if not RESULTS_DIR.exists():
        return instances
    for inst_dir in sorted(RESULTS_DIR.iterdir()):
        if not inst_dir.is_dir():
            continue
        logs = sorted(inst_dir.glob("run*.log"))
        logs = [p for p in logs if p.stat().st_size > 0]
        if not logs:
            continue
        instance = inst_dir.name
        collected = {v: [] for v in FIELDS.values()}
        version = None
        failed_total = 0
        for lp in logs:
            r, failed = parse_log(lp)
            version = version or r["version"]
            failed_total += failed
            for field in FIELDS.values():
                if r[field] is not None:
                    collected[field].append(r[field])

        cls = gen_family(instance)
        mem_mb = meta.get(instance, {}).get("mem_mb")
        price = PRICE.get(instance)
        agg = {f: (round(statistics.median(v), 2) if v else None) for f, v in collected.items()}
        produce_mb = agg["produce_mb_per_sec"]
        value = round(produce_mb / price, 2) if (produce_mb and price) else None
        instances[instance] = {
            "instance": instance,
            "arch": cls["arch"],
            "label": cls["label"],
            "gen": cls["gen"],
            "family": cls["family"],
            "mem_mb": mem_mb,
            "fits_in_ram": (mem_mb * 1024 * 1024 * 0.75 > DATASET_BYTES) if mem_mb else None,
            "price": price,
            "version": version,
            "runs_measured": len(logs),
            "value": value,           # produce MB/s per $ (높을수록 좋음)
            "failed_count": failed_total,
            **agg,
        }
    return instances


def parse_max_log(path):
    """단일 <codec>-runN.log (results/kafka-max) -> dict(필드명 -> 숫자), failed 카운트."""
    text = path.read_text(errors="replace")
    out = {v: None for v in MAX_FIELDS.values()}
    failed = 0
    for line in text.splitlines():
        line = line.strip()
        for label, field in MAX_FIELDS.items():
            if line.startswith(label + ":"):
                val = line.split(":", 1)[1].strip()
                if val in ("SKIPPED",) or "FAILED" in val:
                    failed += 1
                else:
                    try:
                        out[field] = float(val)
                    except ValueError:
                        failed += 1
                break
    return out, failed


def aggregate_max():
    """results/kafka-max/<instance>/<codec>-run*.log -> {instance: {codec: {agg...}}}."""
    result = {}
    if not MAX_RESULTS_DIR.exists():
        return result
    for inst_dir in sorted(MAX_RESULTS_DIR.iterdir()):
        if not inst_dir.is_dir():
            continue
        instance = inst_dir.name
        by_codec = {}
        for codec in CODECS:
            logs = sorted(inst_dir.glob(f"{codec}-run*.log"))
            logs = [p for p in logs if p.stat().st_size > 0]
            if not logs:
                continue
            collected = {v: [] for v in MAX_FIELDS.values()}
            failed_total = 0
            for lp in logs:
                r, failed = parse_max_log(lp)
                failed_total += failed
                for field in MAX_FIELDS.values():
                    if r[field] is not None:
                        collected[field].append(r[field])
            agg = {f: (round(statistics.median(v), 3) if v else None) for f, v in collected.items()}
            agg["runs_measured"] = len(logs)
            agg["failed_count"] = failed_total
            by_codec[codec] = agg
        if by_codec:
            result[instance] = by_codec
    return result


def parse_ramp_log(path):
    """단일 results/kafka-ramp/<instance>/run1.log -> dict.

    STEP,pct,target_mb,achieved_mb,ratio,lat_avg_ms,lat_p99_ms 라인들을 curve 리스트로,
    SATURATION_*/DEPLETION_* 라인을 스칼라로 모은다. FAILED 단계는 curve에서 제외.
    """
    text = path.read_text(errors="replace")
    out = {
        "baseline_mb": None, "depletion_duration_s": None, "depletion_end_mb_per_sec": None,
        "saturation_reached": None, "saturation_mb_per_sec": None, "saturation_lat_p99_ms": None,
        "curve": [],
    }
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("REF_MB:"):
            try:
                out["baseline_mb"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("DEPLETION_DURATION_S:"):
            out["depletion_duration_s"] = line.split(":", 1)[1].strip()
        elif line.startswith("DEPLETION_END_MB_PER_SEC:"):
            try:
                out["depletion_end_mb_per_sec"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("SATURATION_REACHED:"):
            out["saturation_reached"] = line.split(":", 1)[1].strip()
        elif line.startswith("SATURATION_MB_PER_SEC:"):
            try:
                out["saturation_mb_per_sec"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("SATURATION_LAT_P99_MS:"):
            try:
                out["saturation_lat_p99_ms"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("STEP,"):
            cols = line.split(",")
            if len(cols) >= 7 and "FAILED" not in line:
                try:
                    out["curve"].append({
                        "pct": int(cols[1]), "target_mb": float(cols[2]), "achieved_mb": float(cols[3]),
                        "ratio": float(cols[4]), "lat_avg_ms": float(cols[5]), "lat_p99_ms": float(cols[6]),
                    })
                except ValueError:
                    pass
    return out


def aggregate_ramp():
    """results/kafka-ramp/<instance>/run1.log -> {instance: {...}} (1회 측정, 집계 없음)."""
    result = {}
    if not RAMP_RESULTS_DIR.exists():
        return result
    for inst_dir in sorted(RAMP_RESULTS_DIR.iterdir()):
        if not inst_dir.is_dir():
            continue
        logs = sorted(p for p in inst_dir.glob("run*.log") if p.stat().st_size > 0)
        if not logs:
            continue
        result[inst_dir.name] = parse_ramp_log(logs[-1])
    return result


def main():
    data = aggregate()
    max_data = aggregate_max()
    for instance, by_codec in max_data.items():
        entry = data.setdefault(instance, {"instance": instance, **gen_family(instance)})
        entry["max"] = by_codec
        base_mb = entry.get("produce_mb_per_sec")
        uncompressed_mb = by_codec.get("uncompressed", {}).get("produce_mb_per_sec")
        zstd_mb = by_codec.get("zstd", {}).get("produce_mb_per_sec")
        entry["scaling_8way"] = round(uncompressed_mb / base_mb, 2) if (uncompressed_mb and base_mb) else None
        entry["zstd_cost"] = round(zstd_mb / uncompressed_mb, 3) if (zstd_mb and uncompressed_mb) else None

    ramp_data = aggregate_ramp()
    for instance, r in ramp_data.items():
        entry = data.setdefault(instance, {"instance": instance, **gen_family(instance)})
        entry["ramp"] = r

    payload = {
        "dataset": f"produce/consume {RECORDS:,} records x {RECORD_SIZE}B (~{DATASET_BYTES / (1024**3):.2f} GiB/run)",
        "note_network": "produce/consume 각 ~4.8GB가 네트워크를 지나므로 인스턴스별 네트워크 baseline/burst 대역폭이 결과에 반영됨 (iperf3 결과와 교차 참조 권장).",
        "note_disk": "gp3 16000 IOPS/2000MB/s(gp3 절대 최대)로 스펙 통일. 1차 시도(1000MB/s)에서 gen6~8 "
                     "다수가 볼륨 캡 근처에 몰려 세대 순위가 역전되는 현상을 발견해 상향 — io2(4000MiB/s)로도 "
                     "전환을 시도했으나 계정 단위 io2 IOPS 쿼터(리전 전체 100,000)에 걸려 54개 병렬 실행이 "
                     "실패해 gp3 최대치로 재조정. 재측정 결과 전 인스턴스가 2000MB/s 캡의 90%에도 못 미쳐 "
                     "스토리지가 더 이상 병목이 아님을 확인(최고 c6in.xlarge 1123MB/s). "
                     "베이스라인(싱글, 200~300MB/s)은 캡과 무관.",
        "note_heap": "브로커 힙=RAM의 25%, 나머지는 OS page cache. 클라이언트는 항상 c6in.2xlarge(amd64)로 통일.",
        "max_dataset": "포화 시나리오: producer/consumer 8-way 병렬 x uncompressed/lz4/zstd 토픽 압축, 3회 중앙값. "
                        "압축은 producer-props가 아니라 토픽 설정(compression.type)으로 강제 — 압축 CPU 비용이 "
                        "클라이언트가 아닌 측정 대상 브로커(대상 인스턴스)에 실린다.",
        "ramp_dataset": "Phase 3 램프업: 90초 버스트크레딧 고갈 → 8-way produce 목표치를 Phase 2 uncompressed "
                         "실측치의 20~160%로 8단계 증가시키며 지연-대-처리량 곡선 측정. 실제/목표 비율이 99.5% "
                         "미달하는 첫 단계를 포화점으로 판정(1회 측정, AWS 공식 performance-testing-framework-"
                         "for-apache-kafka의 점진 램프업+정지조건 방법론을 축소 적용).",
        "instances": data,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    JSON_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"파싱 완료: {len(data)} 인스턴스 → {JSON_FILE}")

    if HTML_FILE.exists():
        html = HTML_FILE.read_text()
        blob = json.dumps(payload, ensure_ascii=False)
        pattern = re.compile(
            r'(<script id="kafka-data" type="application/json">)(.*?)(</script>)',
            re.DOTALL,
        )
        if pattern.search(html):
            html = pattern.sub(lambda m: m.group(1) + blob + m.group(3), html, count=1)
            HTML_FILE.write_text(html)
            print(f"리포트 데이터 주입 완료 → {HTML_FILE}")
            pub = BASE_DIR / "reports" / "kafka-report.html"
            if pub.parent.exists():
                # results/ 템플릿은 ../../reports/ 상대경로를 쓰지만, 발행본은 reports/의 형제 파일이므로 제거
                pub.write_text(html.replace("../../reports/", ""))
                print(f"발행본 생성 → {pub}")
        else:
            print("ⓘ report-charts.html 에 kafka-data 스크립트 없음 (주입 생략)")
    else:
        print("ⓘ report-charts.html 없음 (JSON만 생성)")


if __name__ == "__main__":
    main()
