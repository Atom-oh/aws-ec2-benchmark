---
name: ec2-benchmark
description: >-
  Add, run, debug, or report on an EC2 instance-type benchmark in THIS
  aws-ec2-benchmark project — the suite comparing 51 xlarge instances (5~8세대
  Intel/AMD/Graviton) as K8s Jobs on EKS + Karpenter with a standard HTML report.
  Use whenever the user wants to add/build a new benchmark workload ("ClickHouse
  벤치마크 하자", "add a Kafka/Postgres/MySQL benchmark", "스냅샷 복구해서 mysql 벤치마크"),
  run an existing one across the instances ("nginx 벤치마크 51개 다 돌려줘"), or generate
  the report ("redis 로그로 리포트 만들어줘", "벤치마크 차트가 프리뷰에서 안 보여"). ALSO for
  diagnosing failing runs — cascading FAILED:210, OOM-killed servers, Jobs stuck
  Pending, flex instances not scheduling — which have known root causes here. Prefer
  this over ad-hoc kubectl even if the user doesn't say "benchmark". Do NOT use for
  keyword look-alikes that aren't this suite: tuning a production ClickHouse/DB query,
  adding instance types to the Karpenter NodePool, general EC2/EBS questions, or an
  unrelated Chart.js dashboard.
---

# EC2 Instance Benchmark Workflow

This repo benchmarks **51 xlarge (4 vCPU) EC2 instance types** — Intel/AMD/Graviton,
5~8세대 — on an EKS cluster (`mall-apne2-mgmt`) with Karpenter dynamic node provisioning.
Each benchmark runs as Kubernetes Jobs (one per instance, N repeats), collects logs to
`results/<name>/`, and renders a standard interactive HTML report.

Read `CLAUDE.md` first — it is the source of truth for cluster state, instance list, and
existing benchmarks. This skill captures the **end-to-end workflow + the hard-won gotchas**
so a new benchmark comes out consistent with the existing ones (sysbench, Redis, Nginx,
Elasticsearch, SpringBoot, ClickHouse) on the first try.

## The 8 stages

Work through these in order. Most live benchmarks are multi-hour cloud runs, so get the
template and report right *before* launching all 51.

1. **Design** — pick the workload, the metric and its direction (higher- or lower-is-better),
   the data source, and the repeat count. Write a short spec. See "Fairness" below — decide
   up front how you neutralize (or at least document) disk/network/memory confounders, because
   that decision shapes the template.

2. **Job template** → `benchmarks/<name>/<name>.yaml`. Single-container Job, one per instance.
   Follow the placeholder + scheduling + resource conventions in
   `references/job-template.md`. This is where most mistakes happen — read it.

3. **Data supply (optional)** — if the workload needs a large preloaded dataset, restore a
   per-pod volume from an EBS snapshot instead of downloading 51×. See the snapshot section in
   `references/job-template.md`, including how to avoid breaking existing snapshot bindings and
   how to verify the dataset (a "Phase 0" probe) before committing the template.

4. **Run script** → `scripts/generate-<name>-benchmark.sh`. Deploys per instance, collects
   logs, cleans up. Use `scripts/run-benchmark-skeleton.sh` (bundled with this skill) as the
   starting point — it already encodes full-parallel execution and the unschedulable-skip that
   you will otherwise rediscover painfully.

5. **Log format contract** — define the exact lines the in-pod script prints, so the parser is
   a stable contract. Include explicit `FAILED:<reason>` handling per metric. Example in
   `references/report.md`.

6. **Report** → `scripts/generate-<name>-report.py` + `results/<name>/report-charts.html`.
   Parser aggregates logs → injects JSON into the HTML → publishes a self-contained copy to
   `reports/<name>-report.html` and links it from `reports/index.html`. **Chart.js must be
   inlined, not loaded from a CDN.** Full conventions in `references/report.md`.

7. **Validation** → `tests/<name>/validate.sh`. YAML parse, `kubectl apply --dry-run=client`
   on a couple of substituted instances (amd64 + arm64), placeholder-leak check, `bash -n`,
   report HTML parse. This is the project's stand-in for unit tests — run it before every commit.

8. **Docs** — add a row to the 벤치마크 상태 table in `CLAUDE.md`, a detail section, and the
   placeholder table; note any instances that can't run (see "Known limits").

## Conventions that are easy to get wrong

These are short because the detail lives in the reference files — but they are the difference
between a run that finishes clean and one that wastes hours.

- **Placeholders & sed**: `INSTANCE_SAFE` (dots→dashes), `INSTANCE_TYPE`, `ARCH`, plus
  `RUN_NUMBER` and any `VERSION` token. Substitute with **chained pipes**, never multiple
  `-e` (bash variable-expansion differences bite). Verify zero leaks after substitution.
- **Arch**: read column 2 of `config/instances-4vcpu.txt` with `awk '$1==i{print $2}'`
  (x86_64→amd64). Avoid `grep -P` (not portable).
- **Node isolation**: every benchmark pod carries `podAntiAffinity` on `benchmark` (operator
  Exists) so two benchmarks never share a node, plus the `benchmark=true:NoSchedule` toleration.
- **`backoffLimit: 0`**: a failing/ OOM pod must not infinitely retry.
- **Never run the server in the foreground** in a Job — the Job never completes. Start it
  backgrounded, poll until ready, run the measured work, stop it, `exit 0`.

## Why benchmarks fail — known causes (check here first)

When the user reports a failure, match the symptom before debugging from scratch:

- **`FAILED:210` cascade** (one query/op fails, then everything after fails): the server was
  **OOM-killed by the OS**, so all later ops hit connection-refused. Caused by a memory-heavy
  op (e.g. a high-cardinality GROUP BY) with no bound. Fix: apply **RAM-relative** spill +
  per-op memory caps to *every* op, not just the obvious one — see `references/job-template.md`
  ("Memory & OOM"). Absolute byte limits are wrong: they penalize big-RAM instances and still
  OOM small-RAM ones.
- **Pods stuck `Pending`, run stalls**: the instance type can't be provisioned in the cluster's
  AZs (the flex types — e.g. `c7i-flex` — are only in 2b/2d, but subnets are 2a/2c). The run
  script must **fast-skip** such instances instead of waiting out the Job timeout. This is why
  the run is full-parallel with a `wait_schedulable` probe, not serial batches.
- **Charts blank in code-server preview**: the Live Preview blocks external CDNs. Chart.js
  must be **inlined into the HTML**. The data table/sections must also render independently of
  Chart.js (wrap chart code in try/catch) so a chart error never blanks the page.
- **A subset of queries/ops error with UNKNOWN_IDENTIFIER**: the dataset's schema differs from
  what the workload assumes (e.g. the ClickBench `hits` snapshot uses `TraficSourceID`, one
  'f'). Verify the real schema with a Phase-0 probe before trusting upstream query files.

## Fairness — the confounders to neutralize or document

A benchmark that silently lets disk/network/memory dominate is misleading. Decide and write
down how you handle these (they belong in the report's methodology section too):

- **Disk**: give every instance the same volume spec (e.g. the `gp3-clickhouse` StorageClass,
  16000 IOPS / 1000MB/s) so the *volume* isn't the variable. But know the limit: actual
  throughput is still capped by each instance's **per-instance EBS bandwidth**, and a dataset
  larger than RAM is re-read from EBS on every "hot" run. So "disk neutralized" only holds for
  instances where memory ≥ dataset — say so explicitly.
- **Memory (C 8GB / M 16GB / R 32GB)**: do **not** set a fixed pod memory limit — let the
  engine see the whole node, so the C/M/R difference is the intended variable. Make spill/cache
  thresholds **RAM-relative** so bigger RAM is genuinely advantaged (it should be).
- **Network/zone**: co-locate client and server in the same AZ when the workload is networked.

## Pointers

- `references/job-template.md` — Job YAML skeleton, placeholders, scheduling, memory/OOM,
  EBS snapshot supply + Phase-0 verification.
- `references/report.md` — parser pattern, log-format contract, the chart set, Chart.js
  inlining, publishing to `reports/` and `index.html`.
- `scripts/run-benchmark-skeleton.sh` — copy to `scripts/generate-<name>-benchmark.sh` and adapt.
- Existing examples to imitate: `benchmarks/clickhouse/`, `benchmarks/redis/`, `benchmarks/nginx/`
  and their `scripts/generate-*` + `results/*/report-charts.html`.
