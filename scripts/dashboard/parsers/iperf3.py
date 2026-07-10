"""iperf3 원시 로그 파서.

로그는 4개 섹션(TCP Single/Parallel/Reverse, UDP)으로 구성. 각 섹션의 sender 요약 줄에서
Bitrate를 읽는다(TCP는 sender 기준 유지 — nginx/redis 등 다른 벤치마크와 달리 iperf3
레거시 리포트도 sender 값을 썼음, reports/iperf3-report.html의 rawData와 스케일 일치로 확인).
UDP는 크레딧 소진/타이밍 문제로 일부 run에서 완전히 실패(에러만 찍힘)할 수 있어 nullable 처리.
"""
import re

from common import RESULTS_DIR, canonical_instances, mean

# results/iperf3/ 디렉터리명이 이 벤치마크에서만 'c7i-flex.xlarge' 대신 'c7i.flex.xlarge'로
# 되어 있음(다른 8개 벤치마크 디렉터리는 정상 하이픈 표기) — 원본 데이터는 보존하고 파서에서만 매핑.
DIR_ALIASES = {"c7i-flex.xlarge": "c7i.flex.xlarge"}

SECTION_PATTERN = re.compile(
    r"--- (TCP Bandwidth \([^)]+\)|UDP Bandwidth Test \([^)]+\)) ---\n(.*?)(?=\n---|\Z)",
    re.S,
)
SINGLE_LINE = re.compile(
    r"\[\s*\d+\]\s+[\d.]+-([\d.]+)\s+sec\s+[\d.]+\s+\wBytes\s+([\d.]+)\s+(\wbits)/sec"
    r"(?:\s+\d+)?\s+sender"
)
SUM_LINE = re.compile(
    r"\[SUM\]\s+[\d.]+-([\d.]+)\s+sec\s+[\d.]+\s+\wBytes\s+([\d.]+)\s+(\wbits)/sec"
    r"(?:\s+\d+)?\s+sender"
)
UDP_LINE = re.compile(
    r"\[\s*\d+\]\s+[\d.]+-[\d.]+\s+sec\s+[\d.]+\s+\wBytes\s+([\d.]+)\s+(\wbits)/sec\s+"
    r"([\d.]+)\s+ms\s+(\d+)/(\d+)\s+\(([\d.]+)%\)\s+receiver"
)


def _to_gbps(value, unit):
    return value / 1000 if unit == "Mbits" else value


def parse_log(path):
    content = path.read_text(errors="replace")
    out = {"single_gbps": None, "parallel_gbps": None, "reverse_gbps": None,
           "udp_mbps": None, "jitter_ms": None, "loss_pct": None}
    for name, body in SECTION_PATTERN.findall(content):
        if name.startswith("TCP Bandwidth (Single"):
            m = SINGLE_LINE.search(body)
            if m:
                out["single_gbps"] = _to_gbps(float(m.group(2)), m.group(3))
        elif name.startswith("TCP Bandwidth (8 Parallel"):
            m = SUM_LINE.search(body)  # 8-way는 [SUM] 라인이 총 대역폭
            if m:
                out["parallel_gbps"] = _to_gbps(float(m.group(2)), m.group(3))
        elif name.startswith("TCP Bandwidth (Reverse"):
            m = SINGLE_LINE.search(body)
            if m:
                out["reverse_gbps"] = _to_gbps(float(m.group(2)), m.group(3))
        elif name.startswith("UDP Bandwidth"):
            m = UDP_LINE.search(body)
            if m:
                bitrate, unit, jitter, lost, total, loss_pct = m.groups()
                mbps = float(bitrate) * 1000 if unit == "Gbits" else float(bitrate)
                out["udp_mbps"] = mbps
                out["jitter_ms"] = float(jitter)
                out["loss_pct"] = float(loss_pct)
    return out


def build():
    base = RESULTS_DIR / "iperf3"
    instances = {}
    for name in canonical_instances():
        inst_dir = base / DIR_ALIASES.get(name, name)
        if not inst_dir.is_dir():
            continue
        logs = sorted(inst_dir.glob("run*.log"))
        runs = {k: [] for k in ["single_gbps", "parallel_gbps", "reverse_gbps", "udp_mbps", "jitter_ms", "loss_pct"]}
        for lp in logs:
            r = parse_log(lp)
            for k, v in r.items():
                if v is not None:
                    runs[k].append(v)
        if not any(runs.values()):
            continue
        instances[name] = {k: mean(v) for k, v in runs.items()}

    coverage = sum(1 for v in instances.values() if v["parallel_gbps"] is not None)
    return {
        "benchmark": "iperf3",
        "coverage": coverage,
        "headline": {"field": "parallel_gbps", "direction": "max", "label": "TCP Parallel Bandwidth", "unit": "Gbps"},
        "notes": {
            "method": "iperf3 TCP Single/8-Parallel/Reverse(30s) + UDP(1Gbps target, 30s), 5회 평균. sender 측 Bitrate 기준(UDP는 receiver 측 Jitter/Loss).",
            "udp_caveat": "UDP는 일부 run에서 소켓 오류로 완전 실패할 수 있어 평균 표본 수가 TCP보다 적을 수 있음",
            "single_stream_caveat": "c7g/c7i/m8i.xlarge는 5회 중 1회가 'Broken pipe' 오류로 완전 실패해 TCP Single Stream이 4회 평균(다른 필드는 5회)",
        },
        "instances": instances,
    }
