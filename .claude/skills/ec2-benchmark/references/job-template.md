# Job Template Reference

The benchmark Job runs one instance, one repeat. It is a **multi-document YAML**: optional
PVC(s) first, then the Job. Below is the skeleton with the conventions that matter, followed
by the reasoning so you can adapt it rather than copy blindly.

## Placeholders

| Placeholder | Meaning | Example |
|---|---|---|
| `INSTANCE_SAFE` | instance type, dots→dashes | `c8g-xlarge` |
| `INSTANCE_TYPE` | instance type verbatim | `c8g.xlarge` |
| `ARCH` | `amd64` / `arm64` (nodeSelector only) | `arm64` |
| `RUN_NUMBER` | repeat/set index | `1`..`5` |
| `<TOOL>_VERSION` | pinned image tag | `24.8.14.39` |

Substitute with **chained pipes** (one `sed` per stage), never `sed -e ... -e ...` — variable
expansion behaves inconsistently across shells and the multi-`-e` form has bitten this repo.
Inside the in-pod script derive arch from `$(uname -m)` rather than substituting `ARCH` there,
so a global `s/ARCH/.../` can't corrupt unrelated text.

## Skeleton

```yaml
apiVersion: v1
kind: PersistentVolumeClaim          # only if you mount a dataset volume
metadata:
  name: <name>-data-INSTANCE_SAFE-runRUN_NUMBER
  namespace: benchmark
  labels: { benchmark: <name>, instance-type: "INSTANCE_TYPE" }
spec:
  storageClassName: gp3-clickhouse   # shared high-perf gp3 (16000 IOPS / 1000MB/s)
  accessModes: ["ReadWriteOnce"]
  resources: { requests: { storage: 100Gi } }
  dataSource:                        # restore from a VolumeSnapshot (see below)
    name: <snapshot-name>
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
---
apiVersion: batch/v1
kind: Job
metadata:
  name: <name>-INSTANCE_SAFE-runRUN_NUMBER
  namespace: benchmark
  labels: { benchmark: <name>, instance-type: "INSTANCE_TYPE" }
spec:
  ttlSecondsAfterFinished: 7200      # collect logs before this expires
  backoffLimit: 0                    # no infinite retry on OOM/failure
  template:
    metadata:
      labels: { benchmark: <name>, instance-type: "INSTANCE_TYPE" }
    spec:
      restartPolicy: Never
      nodeSelector:
        node.kubernetes.io/instance-type: INSTANCE_TYPE
        kubernetes.io/arch: ARCH
      tolerations:
        - { key: "benchmark", operator: "Equal", value: "true", effect: "NoSchedule" }
      affinity:
        podAntiAffinity:             # one benchmark pod per node — no noisy neighbors
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector: { matchExpressions: [{ key: benchmark, operator: Exists }] }
              topologyKey: "kubernetes.io/hostname"
      securityContext: { runAsUser: 101, runAsGroup: 101, fsGroup: 101 }  # match engine uid
      initContainers:               # only if mounting a restored volume
        - name: chown
          image: public.ecr.aws/docker/library/busybox:1.36
          securityContext: { runAsUser: 0 }
          command: ["sh","-c","chown -R 101:101 /var/lib/<engine> && echo chowned"]
          volumeMounts: [{ name: data, mountPath: /var/lib/<engine> }]
      containers:
        - name: <name>
          image: <image>:<TOOL>_VERSION
          command: ["/bin/bash","-c"]
          args:
            - |
              set -uo pipefail
              INSTANCE="INSTANCE_TYPE"; ARCH="$(uname -m)"; SET="RUN_NUMBER"
              echo "INSTANCE: ${INSTANCE}"; echo "ARCH: ${ARCH}"
              # --- RAM-relative limits (see "Memory & OOM") ---
              MEM_BYTES=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') * 1024 ))
              SPILL=$(( MEM_BYTES * 40 / 100 )); MAXMEM=$(( MEM_BYTES * 70 / 100 ))
              # --- start server in BACKGROUND, poll until ready (never foreground) ---
              <engine>-server ... > /var/lib/<engine>/server.log 2>&1 &
              for i in $(seq 1 120); do <client> "SELECT 1" >/dev/null 2>&1 && break; sleep 1; done
              # --- run measured work, print the log-format contract lines ---
              # --- stop server, exit 0 ---
              exit 0
          volumeMounts:
            - { name: data, mountPath: /var/lib/<engine> }   # if dataset volume
            - { name: cfg,  mountPath: /cfg }                 # if config/queries via ConfigMap
          resources:
            requests: { cpu: "2", memory: "2Gi" }
            # NO memory limit — engine must see full node RAM (C/M/R is the variable)
      volumes:
        - { name: data, persistentVolumeClaim: { claimName: <name>-data-INSTANCE_SAFE-runRUN_NUMBER } }
        - { name: cfg,  configMap: { name: <name>-cfg } }
```

## Memory & OOM (the cascade fix)

A single memory-heavy op (large hash aggregation, big sort) can blow past the node's RAM and
get the **server OOM-killed by the OS** — after which every later op fails with connection
errors (a cascade). Two defenses, both **RAM-relative** (computed from `/proc/meminfo` at
runtime so each instance scales by its own RAM):

- **Spill to disk** before memory fills: e.g. `max_bytes_before_external_group_by` /
  `_external_sort` ≈ 40% RAM. Heavy ops then complete (slower) instead of dying.
- **Per-op hard cap** ≈ 70% RAM: an op that still exceeds it fails *gracefully* (recorded as
  `FAILED`) without taking the server down, so the rest of the run survives.

Apply these to **every** op (pass them as client flags for all queries), not only the one you
think is heavy. Never hardcode absolute byte limits — they make 32GB instances spill early
(re-introducing the EBS confounder) and still OOM 8GB ones. Bigger RAM should win; relative
thresholds make that happen.

## EBS snapshot data supply

To avoid N× large downloads (one per instance), preload the dataset once, snapshot the volume, and restore a
per-pod PVC from it. Conventions:

- **Unique snapshot name.** Don't reuse a name already bound in-cluster — a second
  `VolumeSnapshotContent` pointing at the same handle with the same `volumeSnapshotRef` breaks
  the working binding. Use a fresh name (e.g. `<dataset>-<snapid-suffix>`) so it apply-s safely.
- **`deletionPolicy: Retain`** on the content, so deleting the k8s objects never deletes the
  underlying AWS snapshot. Before `kubectl delete`-ing a snapshot you created with `Delete`,
  patch it to `Retain` first.
- The run script should `kubectl apply` the snapshot manifest and wait for
  `.status.readyToUse == true` before deploying Jobs.
- **Phase-0 verification.** Restore one throwaway PVC + pod, start the engine, and confirm the
  engine **version**, the **table/DB names**, **row count**, and **actual column names** before
  trusting upstream query files. Pin the image to the verified version. Clean up the probe;
  confirm the source snapshot still exists afterward.

## Scheduling reality

- The `benchmark-server` NodePool CPU limit is large (480 = ~120 nodes), so the whole fleet
  can run concurrently — no need to batch.
- **Flex instances** (`c7i-flex`, etc.) are offered only in AZs 2b/2d, but the cluster subnets
  are 2a/2c → they never schedule. The run script must detect "Pending and not scheduling
  within ~5 min" and skip the whole instance, or it stalls. Expect a few less than the full count to actually run.
