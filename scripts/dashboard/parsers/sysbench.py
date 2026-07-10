"""sysbench CPU/Memory 원시 로그 파서.

로그 파싱 로직은 scripts/generate-sysbench-report.py의 parse_cpu_log/parse_memory_log를
그대로 포팅(재작성 아님) — 54개 인스턴스로 커버리지만 확장.
"""
import re
from pathlib import Path

from common import RESULTS_DIR, canonical_instances, mean


def parse_cpu_log(path):
    content = path.read_text(errors="replace")
    mt_events = re.findall(r"events per second:\s+(\d+\.?\d*)", content)
    st_section = content.split("Single Thread Performance")
    single_thread = None
    if len(st_section) > 1:
        m = re.search(r"events per second:\s+(\d+\.?\d*)", st_section[1])
        if m:
            single_thread = float(m.group(1))
    multi_values = [float(x) for x in mt_events[:3]] if mt_events else []
    multi_thread = mean(multi_values)
    return multi_thread, single_thread


def parse_memory_log(path):
    content = path.read_text(errors="replace")
    patterns = {
        "mem_seq_write": r"Sequential Write \(1K block\).*?(\d+\.?\d*) MiB/sec",
        "mem_seq_read": r"Sequential Read \(1K block\).*?(\d+\.?\d*) MiB/sec",
        "mem_rnd_write": r"Random Write \(1K block\).*?(\d+\.?\d*) MiB/sec",
        "mem_rnd_read": r"Random Read \(1K block\).*?(\d+\.?\d*) MiB/sec",
        "mem_large_block": r"Large Block Sequential Write \(1M block\).*?(\d+\.?\d*) MiB/sec",
    }
    out = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, content, re.DOTALL)
        out[key] = float(m.group(1)) if m else None
    return out


def build():
    cpu_dir = RESULTS_DIR / "sysbench-cpu"
    mem_dir = RESULTS_DIR / "sysbench-memory"
    instances = {}
    for name in canonical_instances():
        cpu_logs = sorted((cpu_dir / name).glob("run*.log")) if (cpu_dir / name).is_dir() else []
        mem_logs = sorted((mem_dir / name).glob("run*.log")) if (mem_dir / name).is_dir() else []
        if not cpu_logs and not mem_logs:
            continue

        mt_runs, st_runs = [], []
        for lp in cpu_logs:
            mt, st = parse_cpu_log(lp)
            if mt is not None:
                mt_runs.append(mt)
            if st is not None:
                st_runs.append(st)

        mem_runs = {k: [] for k in ["mem_seq_write", "mem_seq_read", "mem_rnd_write", "mem_rnd_read", "mem_large_block"]}
        for lp in mem_logs:
            r = parse_memory_log(lp)
            for k, v in r.items():
                if v is not None:
                    mem_runs[k].append(v)

        entry = {
            "cpu_mt": mean(mt_runs),
            "cpu_st": mean(st_runs),
        }
        entry.update({k: mean(v) for k, v in mem_runs.items()})
        instances[name] = entry

    coverage = sum(1 for v in instances.values() if v["cpu_mt"] is not None)
    return {
        "benchmark": "sysbench",
        "coverage": coverage,
        "headline": {"field": "cpu_mt", "direction": "max", "label": "CPU Multi-thread", "unit": "events/s"},
        "notes": {
            "method": "sysbench CPU(4threads, 60s) 3회 평균 + Single Thread 1회, sysbench Memory 5종 블록 테스트 5회 평균",
        },
        "instances": instances,
    }
