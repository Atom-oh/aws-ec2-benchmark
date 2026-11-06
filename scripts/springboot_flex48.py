#!/usr/bin/env python3
"""Prepare, launch, inspect and recover the two-instance 48-hour experiment."""
import argparse
import copy
import csv
import datetime as dt
import json
import io
import re
from pathlib import Path
import subprocess
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = "mall-apne2-mgmt"
ZONE = "ap-northeast-2c"
TYPES = ("m7i-flex.xlarge", "m8i-flex.xlarge")
ECR = "180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/benchmark"


def kubectl(*args, **kwargs):
    return subprocess.run(["kubectl", "--context", CONTEXT, "-n", "benchmark", *args],
                          check=True, **kwargs)


def recover_latency(directory, fresh_snapshot=False):
    """Recover each average from its raw probe, keeping the original CSV intact.

    The initial deployed awk parser also matched 'Latency Distribution'. Correct
    collected samples without interrupting the already running 48-hour wrk.
    """
    path = directory / "samples.csv"
    probes = directory / "probes.log"
    if not path.exists() or not probes.exists():
        return
    averages = {}
    elapsed = None
    for line in probes.read_text().splitlines():
        marker = re.match(r"--- .* elapsed=(\d+) duration=\d+ ---", line)
        if marker:
            elapsed = marker.group(1)
        value = re.match(r"\s*Latency\s+([\d.]+)(us|ms|s)\s", line)
        if value and elapsed is not None:
            averages[elapsed] = float(value.group(1)) * {"us": .001, "ms": 1, "s": 1000}[value.group(2)]
    raw_path = directory / "samples-raw.csv"
    if fresh_snapshot or not raw_path.exists():
        raw_path.write_text(path.read_text())
    reader = csv.DictReader(io.StringIO(raw_path.read_text()))
    fields = reader.fieldnames
    rows = list(reader)
    for row in rows:
        if row["elapsed_sec"] not in averages:
            raise ValueError("Incomplete snapshot: average latency absent from raw probe")
        row["avg_latency_ms"] = f"{averages[row['elapsed_sec']]:.3f}"
    with path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def render(run_id, server_digest, client_digest):
    base = f"sb-flex48-{run_id}"
    common = {"benchmark-run": run_id, "experiment": "springboot-flex48"}
    server_template = list(yaml.safe_load_all((ROOT / "benchmarks/springboot/springboot-server.yaml").read_text()))[0]
    servers, clients = [], []
    server_names, service_names = [], []
    account = base + "-cleanup"
    clients.append({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": account, "labels": common}})
    clients.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": base, "labels": common},
                    "data": {"load.sh": (ROOT / "scripts/springboot-flex48-load.sh").read_text()}})
    for instance in TYPES:
        safe = instance.replace(".", "-")
        name = f"{base}-{safe}"
        server_name = name + "-server"
        labels = dict(common, **{"instance-type": instance})
        server_labels = dict(labels, benchmark="springboot-flex48-server", app=server_name)
        template = copy.deepcopy(server_template["spec"]["template"])
        template["metadata"] = {"labels": server_labels, "annotations": {"karpenter.sh/do-not-disrupt": "true"}}
        spec = template["spec"]
        spec.update(restartPolicy="Never", automountServiceAccountToken=False)
        spec["nodeSelector"] = {"node.kubernetes.io/instance-type": instance, "karpenter.sh/nodepool": "benchmark-server",
                                "topology.kubernetes.io/zone": ZONE, "karpenter.sh/capacity-type": "on-demand"}
        container = spec["containers"][0]
        container["image"] = f"{ECR}/springboot-simple@{server_digest}"
        container["resources"] = {"requests": {"cpu": "3000m", "memory": "12Gi"}}
        container["env"] = [e for e in container["env"] if e["name"] != "INSTANCE_TYPE"] + [
            {"name": "INSTANCE_TYPE", "value": instance},
            {"name": "MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE", "value": "health,metrics"}]
        servers.append({"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": server_name, "labels": labels},
                        "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 180000, "ttlSecondsAfterFinished": 604800, "template": template}})
        servers.append({"apiVersion": "v1", "kind": "Service", "metadata": {"name": server_name, "labels": labels},
                        "spec": {"selector": {"app": server_name}, "ports": [{"port": 8080, "targetPort": 8080}], "type": "ClusterIP"}})
        server_names.append(server_name)
        service_names.append(server_name)
        pvc = name + "-results"
        clients.append({"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": pvc, "labels": labels},
                        "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "gp3", "resources": {"requests": {"storage": "1Gi"}}}})
        client_spec = {
            "serviceAccountName": account, "restartPolicy": "Never",
            "nodeSelector": {"node-type": "benchmark-client", "topology.kubernetes.io/zone": ZONE},
            "tolerations": [{"key": "benchmark-client", "operator": "Equal", "value": "true", "effect": "NoSchedule"}],
            "affinity": copy.deepcopy(spec["affinity"]),
            "volumes": [{"name": "script", "configMap": {"name": base}}, {"name": "results", "persistentVolumeClaim": {"claimName": pvc}}],
            "containers": [{"name": "load", "image": f"{ECR}/wrk@{client_digest}",
                            "command": ["/bin/sh", "-ec", "apk add --no-cache curl > /results/packages.log 2>&1; exec sh /script/load.sh"],
                            "resources": {"requests": {"cpu": "6000m", "memory": "4Gi"}},
                            "volumeMounts": [{"name": "script", "mountPath": "/script", "readOnly": True}, {"name": "results", "mountPath": "/results"}],
                            "env": [{"name": key, "value": value} for key, value in {
                                "TARGET": f"http://{server_name}:8080", "INSTANCE_TYPE": instance,
                                "RUN_ID": run_id, "SERVER_JOB": server_name, "SERVER_SERVICE": server_name}.items()]}],
            "initContainers": [{"name": "ready", "image": f"{ECR}/wrk@{client_digest}",
                                "command": ["/bin/sh", "-ec", f"until wget -q -O - http://{server_name}:8080/actuator/health | grep -q UP; do sleep 5; done"],
                                "resources": {"requests": {"cpu": "100m", "memory": "32Mi"}}}]}
        clients.append({"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name + "-load", "labels": labels},
                        "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 178200, "ttlSecondsAfterFinished": 604800,
                                 "template": {"metadata": {"labels": dict(labels, benchmark="springboot-flex48-load"),
                                                           "annotations": {"karpenter.sh/do-not-disrupt": "true"}}, "spec": client_spec}}})
    clients.insert(1, {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": {"name": account, "labels": common},
                       "rules": [{"apiGroups": ["batch"], "resources": ["jobs"], "resourceNames": server_names, "verbs": ["delete"]},
                                 {"apiGroups": [""], "resources": ["services"], "resourceNames": service_names, "verbs": ["delete"]}]})
    clients.insert(2, {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": {"name": account, "labels": common},
                       "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": account},
                       "subjects": [{"kind": "ServiceAccount", "name": account, "namespace": "benchmark"}]})
    for obj in servers + clients:
        obj["metadata"]["namespace"] = "benchmark"
    return servers, clients


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "launch", "status", "collect", "watch"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--server-digest")
    parser.add_argument("--client-digest")
    args = parser.parse_args()
    if not args.run_id.isalnum() or len(args.run_id) > 20:
        parser.error("run-id must contain at most 20 letters/digits")
    output = ROOT / "results/springboot-flex48" / args.run_id
    output.mkdir(parents=True, exist_ok=True)
    if args.action == "prepare":
        if not all(d and d.startswith("sha256:") for d in (args.server_digest, args.client_digest)):
            parser.error("prepare requires both image digests")
        servers, clients = render(args.run_id, args.server_digest, args.client_digest)
        for filename, objects in (("servers.yaml", servers), ("clients.yaml", clients)):
            (output / filename).write_text(yaml.safe_dump_all(objects, sort_keys=False))
        (output / "metadata.json").write_text(json.dumps({"run_id": args.run_id, "context": CONTEXT,
            "prepared_at": dt.datetime.now(dt.timezone.utc).isoformat(), "types": TYPES,
            "duration_seconds": 172800, "warmup_seconds": 300, "zone": ZONE,
            "server_digest": args.server_digest, "client_digest": args.client_digest}, indent=2) + "\n")
        print(output)
    elif args.action == "launch":
        # Server readiness bounds startup; no local process is needed after launch.
        kubectl("apply", "-f", str(output / "servers.yaml"))
        try:
            kubectl("wait", "--for=condition=ready", "pod", "-l", f"benchmark-run={args.run_id}", "--timeout=900s")
            kubectl("apply", "-f", str(output / "clients.yaml"))
        except subprocess.CalledProcessError:
            kubectl("delete", "-f", str(output / "servers.yaml"), "--ignore-not-found")
            raise
    elif args.action == "status":
        kubectl("get", "jobs,pods,pvc", "-l", f"benchmark-run={args.run_id}", "-o", "wide")
    elif args.action == "watch":
        deadline = time.monotonic() + 50 * 3600
        next_copy = time.monotonic() + 600
        while time.monotonic() < deadline:
            try:
                jobs = json.loads(kubectl("get", "jobs", "-l", f"benchmark-run={args.run_id}", "-o", "json", capture_output=True, text=True).stdout)
                loads = [j for j in jobs["items"] if j["metadata"]["name"].endswith("-load")]
                (output / "jobs-status.json").write_text(json.dumps(jobs, indent=2) + "\n")
                terminal = len(loads) == 2 and all(any(c["type"] in ("Complete", "Failed") and c["status"] == "True"
                    for c in j.get("status", {}).get("conditions", [])) for j in loads)
                if terminal or time.monotonic() >= next_copy:
                    subprocess.run(["python3", str(Path(__file__).resolve()), "collect", "--run-id", args.run_id], check=True)
                    next_copy = time.monotonic() + 1800
                if terminal:
                    print("Both load Jobs ended; durable results recovered.", flush=True)
                    return
            except (subprocess.CalledProcessError, OSError, ValueError) as error:
                print(f"Observer will retry: {error}", flush=True)
            time.sleep(60)
        raise SystemExit("Observer reached its 50-hour limit; inspect PVCs and Job status")
    elif args.action == "collect":
        # EBS remains available after the load exits; a temporary pod can recover it.
        pods = json.loads(kubectl("get", "pods", "-l", f"benchmark-run={args.run_id},benchmark=springboot-flex48-load", "-o", "json", capture_output=True, text=True).stdout)
        for pod in pods["items"]:
            instance = pod["metadata"]["labels"]["instance-type"]
            target = output / instance
            target.mkdir(exist_ok=True)
            name = pod["metadata"]["name"]
            (target / "pod.json").write_text(json.dumps(pod, indent=2) + "\n")
            (target / "pod.log").write_text(kubectl("logs", name, "-c", "load", capture_output=True, text=True).stdout)
            if pod["status"]["phase"] == "Running":
                kubectl("cp", "-c", "load", f"{name}:/results/.", str(target))
            else:
                reader_name = f"sb-flex48-{args.run_id}-{instance.replace('.', '-')}-reader"
                load = pod["spec"]["containers"][0]
                reader = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": reader_name,
                    "namespace": "benchmark", "labels": {"benchmark-run": args.run_id}},
                    "spec": {"restartPolicy": "Never", "activeDeadlineSeconds": 600,
                        "automountServiceAccountToken": False,
                        "nodeSelector": {"node-type": "benchmark-client", "topology.kubernetes.io/zone": ZONE},
                        "tolerations": pod["spec"]["tolerations"],
                        "volumes": [v for v in pod["spec"]["volumes"] if v["name"] == "results"],
                        "containers": [{"name": "reader", "image": load["image"], "command": ["/bin/sh", "-c", "sleep 590"],
                            "resources": {"requests": {"cpu": "100m", "memory": "64Mi"}},
                            "volumeMounts": [{"name": "results", "mountPath": "/results", "readOnly": True}]}]}}
                kubectl("create", "-f", "-", input=yaml.safe_dump(reader), text=True)
                try:
                    kubectl("wait", "--for=condition=ready", f"pod/{reader_name}", "--timeout=300s")
                    kubectl("cp", "-c", "reader", f"{reader_name}:/results/.", str(target))
                finally:
                    kubectl("delete", "pod", reader_name, "--ignore-not-found", "--wait=false")
            recover_latency(target, fresh_snapshot=True)
            print(target)


if __name__ == "__main__":
    main()
