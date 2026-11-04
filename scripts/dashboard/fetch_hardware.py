#!/usr/bin/env python3
"""인스턴스 하드웨어 사양 조회 -> config/hardware-4vcpu.json (커밋되는 캐시 파일).

리포트의 "측정 대상 인스턴스" 표와 원인 분석(물리 코어 vs 하이퍼스레딩, 지속 클럭)에 쓰인다.
출처는 전부 AWS API이며 조회일을 파일에 남긴다 — 수치를 손으로 적지 않기 위함.
  - EC2 DescribeInstanceTypes: 물리 코어 수, 코어당 스레드, 지속 클럭, 메모리, 네트워크/EBS 대역폭
  - Pricing GetProducts: 프로세서명(physicalProcessor) — DescribeInstanceTypes에는 모델명이 없음

사용: python3 scripts/dashboard/fetch_hardware.py   (AWS CLI 기본 프로필, 계정 180294183052)
인스턴스를 추가하면 다시 실행해 갱신할 것. build_data.py는 이 파일을 읽기만 한다(API 호출 안 함).
"""
import datetime as dt
import json
import subprocess

from common import BASE_DIR, canonical_instances

REGION = "ap-northeast-2"
OUT = BASE_DIR / "config" / "hardware-4vcpu.json"


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--output", "json"], text=True))


def describe(instances):
    out = {}
    for i in range(0, len(instances), 50):  # API 상한 100, 여유 있게 50개씩
        resp = aws("ec2", "describe-instance-types", "--region", REGION, "--instance-types", *instances[i:i + 50])
        for it in resp["InstanceTypes"]:
            out[it["InstanceType"]] = {
                "vcpus": it["VCpuInfo"]["DefaultVCpus"],
                "cores": it["VCpuInfo"]["DefaultCores"],
                "threads_per_core": it["VCpuInfo"]["DefaultThreadsPerCore"],
                "clock_ghz": it["ProcessorInfo"].get("SustainedClockSpeedInGhz"),
                "mem_gib": it["MemoryInfo"]["SizeInMiB"] / 1024,
                "network": it["NetworkInfo"]["NetworkPerformance"],
                "ebs_max_mbps": it["EbsInfo"].get("EbsOptimizedInfo", {}).get("MaximumThroughputInMBps"),
                "local_nvme": it.get("InstanceStorageSupported", False),
            }
    return out


def processor(instance):
    resp = aws(
        "pricing", "get-products", "--region", "us-east-1", "--service-code", "AmazonEC2",
        "--filters",
        f"Type=TERM_MATCH,Field=instanceType,Value={instance}",
        f"Type=TERM_MATCH,Field=regionCode,Value={REGION}",
        "Type=TERM_MATCH,Field=operatingSystem,Value=Linux",
        "Type=TERM_MATCH,Field=tenancy,Value=Shared",
        "Type=TERM_MATCH,Field=preInstalledSw,Value=NA",
        "Type=TERM_MATCH,Field=capacitystatus,Value=Used",
        "--max-items", "1",
    )
    if not resp.get("PriceList"):
        return None
    return json.loads(resp["PriceList"][0])["product"]["attributes"].get("physicalProcessor")


def main():
    names = canonical_instances()
    specs = describe(names)
    missing = sorted(set(names) - set(specs))
    if missing:
        raise SystemExit(f"DescribeInstanceTypes 누락: {missing}")
    for name in names:
        specs[name]["processor"] = processor(name)
    payload = {
        "source": "aws ec2 describe-instance-types + aws pricing get-products (physicalProcessor)",
        "region": REGION,
        "fetched": dt.date.today().isoformat(),
        "instances": dict(sorted(specs.items())),
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(specs)}개 -> {OUT.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
