#!/usr/bin/env python3
"""클럭 조사 분석: results/springboot-clock/round*/<inst>/wrk<N>.log × results/node-sampler/<type>/<node>.log.

회차마다 RUN_START~RUN_END 구간에서
  - 서버 노드: 부하 중(util > 50%) cpu MHz 중앙값, 서버 노드 CPU 사용률 중앙값, EC2 인스턴스 ID
  - 클라이언트: CLIENT_CPU(1초 간격 노드 CPU%) 중앙값/최대
  - 처리량: 커넥션 단계(50/100/200) 중 최대 req/s (parsers/springboot.py peak 정의와 동일)
를 뽑아 표로 출력하고, --json이면 results/springboot-clock/clock.json에 저장한다.
flex 인스턴스는 /proc/cpuinfo에 고정값(2400 MHz)만 노출돼 클럭 비교에서 제외 표시한다.
"""
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS_DIR  # noqa: E402

SEC = re.compile(r"^--- [^\n]*?(\d+) threads, (\d+) connections[^\n]*\n(.*?)(?=^--- |^=====)", re.M | re.S)


def peak_any(text):
    """스레드 수와 무관하게 커넥션 단계별 Requests/sec 중 최댓값(-t2/-t6 공용)."""
    vals = [float(m.group(1)) for _, _, body in SEC.findall(text) if (m := re.search(r"Requests/sec:\s+([\d.]+)", body))]
    return max(vals) if vals else None

CLOCK_DIR = RESULTS_DIR / "springboot-clock"
SAMPLER_DIR = RESULTS_DIR / "node-sampler"
LINE = re.compile(r"^ts=(\d+) node=(\S+) mhz_med=(\S+) mhz_min=\S+ mhz_max=\S+ util=(\S+)")


def load_sampler():
    """node -> {"meta": {...}, "samples": {ts: (mhz|None, util)}} (수집기 겹침은 ts로 중복 제거)."""
    nodes = {}
    for f in SAMPLER_DIR.glob("*/*.log"):
        meta, samples = {}, {}
        for line in f.read_text(errors="replace").splitlines():
            if line.startswith("# "):
                meta = dict(kv.split("=", 1) for kv in line[2:].split() if "=" in kv)
                continue
            m = LINE.match(line)
            if m:
                ts, _, mhz, util = m.groups()
                try:
                    samples[int(ts)] = (float(mhz) if mhz != "NA" else None, float(util))
                except ValueError:
                    pass
        nodes[meta.get("node", f.stem)] = {"meta": meta, "samples": samples}
    return nodes


def med(v):
    return round(statistics.median(v), 1) if v else None


def analyze():
    nodes = load_sampler()
    rows = []
    for lp in sorted(list(CLOCK_DIR.glob("round*/*/wrk*.log")) + list((RESULTS_DIR / "springboot-threads").glob("*/wrk*.log"))):
        text = lp.read_text(errors="replace")
        g = lambda k: (re.search(rf"^{k}:\s*(\S+)", text, re.M) or [None, None])[1]  # noqa: E731
        t0, t1, node = g("RUN_START"), g("RUN_END"), g("SERVER_NODE")
        if not (t0 and t1):
            continue
        t0, t1 = int(t0), int(t1)
        peak = peak_any(text)
        if peak is None:
            continue
        s = nodes.get(node, {"meta": {}, "samples": {}})
        win = [v for ts, v in s["samples"].items() if t0 <= ts <= t1]
        loaded = [v for v in win if v[1] > 50]
        cli = [float(x) for ts, x in re.findall(r"^CLIENT_CPU: (\d+) ([\d.]+)", text, re.M) if t0 <= int(ts) <= t1]
        inst = lp.parent.name
        rows.append({
            "threads": int(g("WRK_THREADS") or 2),
            "round": lp.parent.parent.name, "instance": inst, "run": lp.stem, "peak_rps": round(peak),
            "server_instance_id": s["meta"].get("instance_id"), "zone": s["meta"].get("zone"),
            "server_mhz": None if "-flex" in inst else med([v[0] for v in loaded if v[0]]),
            "server_util": med([v[1] for v in loaded]), "server_samples": len(win),
            "client_node": g("CLIENT_NODE"), "client_cpu_med": med(cli), "client_cpu_max": max(cli) if cli else None,
            "flex_static_mhz": "-flex" in inst,
        })
    return rows


if __name__ == "__main__":
    rows = analyze()
    print(f"{'thr':4}{'round':18}{'instance':17}{'run':6}{'peak rps':>10}{'MHz':>8}{'srvCPU%':>9}{'cliCPU med/max':>16}  host / client")
    for r in rows:
        print(f"{r['threads']:<4}{r['round']:18}{r['instance']:17}{r['run']:6}{r['peak_rps']:>10,}{(r['server_mhz'] or '-'):>8}{(r['server_util'] or '-'):>9}"
              f"{str(r['client_cpu_med']) + '/' + str(r['client_cpu_max']):>16}  {r['server_instance_id']} / {(r['client_node'] or '')[:16]}")
    if "--json" in sys.argv:
        (CLOCK_DIR / "clock.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
