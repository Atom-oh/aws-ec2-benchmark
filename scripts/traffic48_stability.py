#!/usr/bin/env python3
"""Reproduce the Flex stability supplement from the archived final observations.

Never modifies canonical flags. Comparisons pool request histograms on identical
phase intersections. The six cycles describe one host, not six independent trials.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import re
import statistics
from html.parser import HTMLParser
from pathlib import Path

from traffic48_report import pool, qualify

ROOT = Path(__file__).resolve().parents[1]
FLEX = {"m7i-flex.xlarge": "m7i.xlarge", "m8i-flex.xlarge": "m8i.xlarge"}
MODES = ("observed", "strict", "idle_qualified")
AWS_REFERENCE = "https://docs.aws.amazon.com/ec2/latest/instancetypes/instance-types.html#instance-performance"


def select(phases, cycles, seconds=None):
    result = []
    for p in phases:
        match = re.fullmatch(r"d2-c(\d+)-l(\d+)-s\d+", p["name"])
        if not match or not p["finished"] or int(match[1]) not in cycles:
            continue
        if (seconds is None and match[2] == "40") or (
                seconds is not None and match[2] == "100" and p["duration_seconds"] == seconds):
            result.append(p)
    return result


def paired(phases, name, baseline, mode):
    selected = [p for p in phases if mode == "observed" or all(
        p["instances"][n]["valid"] if mode == "strict"
        else p["instances"][n]["qualification"]["qualified"] for n in (name, baseline))]
    target = pool([p["instances"][name] for p in selected])
    base = pool([p["instances"][baseline] for p in selected])
    return dict(instance=name, baseline_instance=baseline, mode=mode,
                phase_names=[p["name"] for p in selected], target=target, baseline=base,
                rps_ratio=target["success_rps"]/base["success_rps"] if target and base["success_rps"] else None,
                p99_ratio=target["p99_ms"]/base["p99_ms"] if target and base["p99_ms"] else None)


def probe_window(rows, start, end):
    selected = [r for r in rows if start < float(r["elapsed_sec"]) <= end]
    if not selected:
        return None
    rps = [float(r["probe_rps"]) for r in selected]
    return dict(start_hour=start/3600, end_hour=end/3600, samples=len(selected),
                probe_rps_mean=statistics.mean(rps),
                probe_rps_cv_pct=100*statistics.pstdev(rps)/statistics.mean(rps),
                probe_rps_min=min(rps), probe_rps_max=max(rps),
                per_probe_p99_median_ms=statistics.median(float(r["p99_latency_ms"]) for r in selected),
                per_probe_p99_max_ms=max(float(r["p99_latency_ms"]) for r in selected),
                socket_errors=sum(int(r["socket_errors"]) for r in selected),
                http_errors=sum(int(r["http_errors"]) for r in selected))


def drop_onset(rows, first_hour_mean):
    """Descriptive threshold, not a Flex mechanism, outage or SLA detector."""
    for i in range(len(rows)-4):
        frames = rows[i:i+5]
        times = [float(r["elapsed_sec"]) for r in frames]
        if (times[0] > 3600 and all(0 < b-a <= 90 for a,b in zip(times,times[1:]))
                and all(float(r["probe_rps"]) < .9*first_hour_mean for r in frames)):
            return dict(first_frame_end_seconds=times[0], confirmed_at_seconds=times[-1],
                        threshold_rps=.9*first_hour_mean, consecutive_samples=5,
                        max_allowed_gap_seconds=90)
    return None


def build(run, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    expected = {f["path"]: f["sha256"] for f in manifest["files"]}
    hashes = {}

    def verified(path):
        relative = str(path.relative_to(run.parents[2]))
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if expected.get(relative) != digest:
            raise ValueError(f"Archived input checksum mismatch: {relative}")
        hashes[relative] = digest
        return content

    data = json.loads(verified(run/"progress-latest.json"))
    meta = json.loads(verified(run/"metadata.json"))
    schedules = {p["name"]: p for p in meta["boost"]["phases"]}
    for p in data["phases"]:
        for name, r in p["instances"].items():
            r["qualification"] = qualify(r, schedules.get(p["name"]), data["quality"][name])
    phases = data["phases"]
    windows = []
    cycles = []
    for name, standard in FLEX.items():
        for baseline in dict.fromkeys(["m7i.xlarge", standard]):
            for seconds in [None, 60, 300, 900, 3600]:
                for label, cs in [("24–36h", [1, 2, 3]), ("36–48h", [4, 5, 6]), ("24–48h", list(range(1, 7)))]:
                    for mode in MODES:
                        item = paired(select(phases, cs, seconds), name, baseline, mode)
                        windows.append(dict(window=label, peak_seconds=seconds, **item))
                for c in range(1, 7):
                    item = paired(select(phases, [c], seconds), name, baseline, "observed")
                    cycles.append(dict(cycle=c, peak_seconds=seconds, **item))
    health = {}
    for name in FLEX:
        q = data["quality"][name]
        rows = [p["instances"][name] for p in phases]
        drops = Counter()
        for source in q["sources"].values():
            drops.update(source.get("drop_reasons", {}))
        total = pool(rows)
        coverage = sum(p["duration_seconds"] * (p["instances"][name]["memory_gc"].get(
            "gc_log_coverage_fraction") or 0) for p in phases)/sum(p["duration_seconds"] for p in phases)
        health[name] = dict(
            **total, uptime_resets=q["uptime_resets"], metrics_errors=q["metrics_errors"],
            source_outcomes={s:v["outcome"] for s,v in q["sources"].items()},
            source_errors={s:dict(accounting=v["accounting_errors"], validation=v["validation_errors"])
                           for s,v in q["sources"].items()},
            drop_reasons=dict(drops), gc_preservation_estimate_pct=100*coverage,
            recovery_valid=sum(r["valid"] for r in data["recovery"][name]),
            recovery_total=len(data["recovery"][name]),
            flags=dict(Counter(f for r in rows for f in r["validation_errors"])))
    sustained = {}
    for name in FLEX:
        folder = run.parents[1]/"springboot-flex48/20261104t0120"/name
        probes = list(csv.DictReader(verified(folder/"samples.csv").decode().splitlines()))
        probe_log = verified(folder/"probes.log").decode()
        durations = Counter(int(v) for v in re.findall(r"^--- .* duration=(\d+) ---$", probe_log, re.MULTILINE))
        if sum(durations.values()) != len(probes):
            raise ValueError(f"Probe log/CSV sample count mismatch: {name}")
        end = max(float(r["elapsed_sec"]) for r in probes)
        times = sorted(float(r["elapsed_sec"]) for r in probes)
        bounds = [0, 3600, 6*3600, 12*3600, 24*3600, 36*3600, end]
        sustained[name] = dict(
            status=verified(folder/"status.txt").decode().strip(), samples=len(probes),
            probe_duration_seconds=dict(durations),
            last_elapsed_seconds=end, unobserved_tail_seconds=172800-end,
            max_sample_gap_seconds=max(b-a for a,b in zip(times,times[1:])),
            nonpositive_probe_samples=sum(float(r["probe_rps"]) <= 0 for r in probes),
            drop_onset=drop_onset(probes, probe_window(probes,0,3600)["probe_rps_mean"]),
            windows=[probe_window(probes,a,b) for a,b in zip(bounds,bounds[1:])],
            last30=probe_window(probes,end-1800,end),
            hourly=[probe_window(probes,h*3600,min((h+1)*3600,end)) for h in range(int(end//3600)+1)])
    return dict(
        source_sha256=hashes[str((run/"progress-latest.json").relative_to(run.parents[2]))],
        input_hashes=hashes, aws_reference=AWS_REFERENCE, run_id=meta["run_id"],
        canonical_complete=data["complete"], comparison_valid=data["comparison_valid"],
        windows=windows, cycles=cycles, health=health, sustained=sustained,
        method=dict(early_cycles=[1,2,3], late_cycles=[4,5,6],
                    quantiles="Pooled scheduled-to-completion request histograms; dropped excluded",
                    cv="Population SD / mean of six phase success-RPS observations, descriptive only",
                    sustained_quantiles="Median/max of per-probe p99; never pooled request p99"))


def markdown_report(data):
    """Reuse the page's editorial text so the downloadable report cannot drift."""
    def f(value, digits=3):
        return "—" if value is None else f"{value:,.{digits}f}"

    def table(head, rows):
        return "\n\n" + "\n".join([
            "| " + " | ".join(head) + " |",
            "|" + "|".join("---" for _ in head) + "|",
            *("| " + " | ".join(str(v) for v in row) + " |" for row in rows)]) + "\n\n"

    def window(name, base, duration, when, mode="observed"):
        return next(r for r in data["windows"] if r["instance"] == name and
                    r["baseline_instance"] == base and r["peak_seconds"] == duration
                    and r["window"] == when and r["mode"] == mode)

    early_late = []
    low = []
    for name, base in FLEX.items():
        for seconds in [60, 300, 900, 3600]:
            a = window(name, base, seconds, "24–36h")["target"]
            b = window(name, base, seconds, "36–48h")["target"]
            qs = [window(name, base, seconds, when, "strict")["target"]
                  for when in ["24–36h", "36–48h"]]
            early_late.append([name, seconds//60, f(a["success_rps"], 0)+" → "+f(b["success_rps"], 0),
                               f(a["p99_ms"])+" → "+f(b["p99_ms"]), f(b["drop_pct"], 2),
                               " / ".join(str(q["phases"] if q else 0) for q in qs)])
        a = window(name, base, None, "24–36h", "idle_qualified")["target"]
        b = window(name, base, None, "36–48h", "idle_qualified")
        low.append([name+" ÷ "+base, f'{a["phases"]} / {b["target"]["phases"]}',
                    f(a["success_rps"], 0)+" → "+f(b["target"]["success_rps"], 0),
                    f(a["p99_ms"])+" → "+f(b["target"]["p99_ms"]), f(b["p99_ratio"])])
    cycle_rows = []
    for cycle in range(1, 7):
        cells = [cycle]
        for name, base in FLEX.items():
            target = next(r["target"] for r in data["cycles"] if r["instance"] == name and
                          r["baseline_instance"] == base and r["peak_seconds"] == 3600 and r["cycle"] == cycle)
            cells += [f(target["success_rps"], 0), f(target["p99_ms"])]
        cycle_rows.append(cells)
    sustained_rows = []
    for a, b in zip(*(data["sustained"][n]["windows"] for n in FLEX)):
        sustained_rows.append([f'{a["start_hour"]:.0f}–{a["end_hour"]:.2f}h',
                               f(a["probe_rps_mean"], 0), f(a["per_probe_p99_median_ms"]),
                               f(b["probe_rps_mean"], 0), f(b["per_probe_p99_median_ms"])])
    tables = {
        "early-late": table(["Flex", "피크 분", "성공 RPS 전반 → 후반 ↑",
                             "p99 ms 전반 → 후반 ↓", "후반 미발생 % ↓",
                             "strict 교집합 전반 / 후반 (각 3개 중)"], early_late),
        "low": table(["같은 구간 비교", "통과 구간 전반 / 후반", "성공 RPS 전반 → 후반 ↑",
                      "p99 ms 전반 → 후반 ↓", "후반 p99 ÷ 기준 ↓"], low),
        "cycles": table(["60분 피크 반복", "m7i-flex RPS ↑", "p99 ms ↓",
                         "m8i-flex RPS ↑", "p99 ms ↓"], cycle_rows),
        "health": table(["Flex", "JVM 재시작", "HTTP / 전송 오류", "timeout",
                         "전체 미발생 %", "최대 힙 GiB", "최대 GC pause ms ↓"], [
                             [n, h["uptime_resets"], f'{h["http_errors"]} / {h["transport_errors"]}',
                              f(h["timeouts"], 0), f(h["drop_pct"], 2), f(h["heap_max_gib"]), f(h["gc_pause_max_ms"])]
                             for n, h in data["health"].items()]),
        "sustained": table(["별도 지속 부하 경과", "m7i-flex probe RPS ↑", "probe p99 중앙값 ms ↓",
                            "m8i-flex probe RPS ↑", "probe p99 중앙값 ms ↓"], sustained_rows),
    }

    class Markdown(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.href = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag in ("h2", "h3"):
                self.parts.append("\n\n"+("#" if tag == "h2" else "##")+" ")
            elif tag == "p":
                self.parts.append("\n\n")
            elif tag == "strong":
                self.parts.append("**")
            elif tag == "code":
                self.parts.append("`")
            elif tag == "a":
                self.parts.append("[")
                self.href = attrs["href"].replace("data/springboot-flex-stability.json", "flex-stability.json")
            elif tag == "div" and "data-stability" in attrs:
                self.parts.append(tables[attrs["data-stability"]])

        def handle_endtag(self, tag):
            if tag == "strong":
                self.parts.append("**")
            elif tag == "code":
                self.parts.append("`")
            elif tag == "a":
                self.parts.append("]("+self.href+")")

        def handle_data(self, text):
            if text.strip():
                self.parts.append(text)

    source = (ROOT/"site/tabs/springboot-traffic48.html").read_text()
    section = source.split('<section class="section" id="traffic48-flex-stability">', 1)[1].split("</section>", 1)[0]
    parser = Markdown()
    parser.feed(section)
    text = "".join(parser.parts).strip()
    text += """

## 분석 기준과 재현

분석 기준: 최종 traffic48 `20261104t0900`, UTC 2026-11-04 10:17:51–11-06 10:17:51.
준비 부하는 제외했다. 표본은 타입당 호스트 1대·JVM 1개이며 6주기는 독립 반복이 아니다.
초기 76,291 RPS 피크와 ramp가 있는 첫날을 전반·후반 비교에 섞지 않았다.
`observed`는 완료 구간 전체의 기술 통계, `strict`는 원래 판정을 양쪽 모두 통과한 교집합,
`idle_qualified`는 기존 리포트의 엄격한 0도착 휴지 예외만 적용한 교집합이다.
피크의 전반·후반 strict 표본은 부족하므로 표본이 없는 칸은 null로 유지했다.
0도착 예외는 GC/CPU telemetry 보존이나 회복 초 판정에 확장하지 않았다.
처리량 변동계수는 6개 구간 RPS의 모집단 표준편차 ÷ 평균이며 신뢰구간·유의성 검정이 아니다.
p99는 미발생 요청을 제외하므로 미발생 비율과 함께 해석해야 한다.

- [전체 시간창 CSV](flex-stability-windows.csv): 135개 대상·기준·시간창·판정 조합과 정확한 구간 이름.
- [분석 JSON](flex-stability.json): 위 비교, 90개 주기 비교, 지속 부하 시간창/시간별 통계, 실패·품질·출처.
- [원본 manifest](raw/manifest.json): 기존 아카이브를 변경하지 않았다.

```bash
# 기존 raw 아카이브를 별도 디렉터리에 복원한 뒤, 저장소 루트에서 실행
python3 scripts/traffic48_stability.py /path/to/restore/results/springboot-traffic48/20261104t0900
python3 -m unittest discover -s tests/traffic48-report -p 'test_stability.py' -v
```

입력 8개(최종 집계·metadata·Flex별 CSV/status/probes.log)를 기존 manifest의 SHA-256과 대조한 뒤 계산한다.
둘째 날 phase의 p99를 평균내지 않고 원본 요청 히스토그램을 합친다.
마지막 반시간 probe의 p99는 요청 합산값이 아니므로 별도 표기로 유지한다.
페이지의 안정성 본문과 표에서 이 Markdown을 생성해 두 리포트의 표현과 수치를 일치시킨다.
AWS 공식 문서의 성능 설명은 2026-11-08 재확인했다.
"""
    return text + "\n\n최종 집계 SHA-256: `" + data["source_sha256"] + "`.\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    result = build(args.run.resolve(), ROOT/"reports/traffic48-final/raw/manifest.json")
    output = ROOT/"reports/traffic48-final"
    (output/"flex-stability.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    (ROOT/"site/data/springboot-flex-stability.json").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"))+"\n")
    (output/"flex-stability.md").write_text(markdown_report(result))
    fields = ["instance", "baseline_instance", "peak_seconds", "window", "mode", "phase_names",
              "phases", "hours", "success_rps", "p99_ms", "drop_pct", "rps_ratio", "p99_ratio",
              "baseline_success_rps", "baseline_p99_ms", "original_valid_phases"]
    with (output/"flex-stability-windows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in result["windows"]:
            row = {k:item.get(k) for k in fields}
            row["phase_names"] = ";".join(item["phase_names"])
            for k in ["phases", "hours", "success_rps", "p99_ms", "drop_pct", "original_valid_phases"]:
                row[k] = (item["target"] or {}).get(k)
            for k in ["success_rps", "p99_ms"]:
                row["baseline_"+k] = (item["baseline"] or {}).get(k)
            writer.writerow(row)
    print(json.dumps(dict(verified_inputs=len(result["input_hashes"]),
                          window_comparisons=len(result["windows"]),
                          cycle_comparisons=len(result["cycles"]),
                          source_sha256=result["source_sha256"])))


if __name__ == "__main__":
    main()
