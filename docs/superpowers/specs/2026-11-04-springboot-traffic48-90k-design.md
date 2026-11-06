# Ongoing 48-hour benchmark: 90,000 RPS peak

The user explicitly requests a 90,000 RPS peak. Preserve the original continuous
Flex experiment, all six running comparison servers/JVMs, existing load clients,
their history, and the original 172800-second measurement end.

Add six independent c6in.2xlarge generators, one per existing server, in
ap-northeast-2c on dedicated benchmark-client nodes. Keep required hostname
anti-affinity, CPU requests 6000m with no limits, memory request 4Gi, pinned
images, ClusterIP targets, no service-account token or cleanup permissions.

The original peak is 76,291.49022349785 RPS. Additional generators supply the
13,708.50977650215 RPS difference during future 100 phases. Other steady levels
remain unchanged. First-day transitions preserve 60-second ramps: extra traffic
ramps from zero at a peak's entrance and to zero in the following 80 phase.
Second-day peaks jump immediately. The combined target is exactly 90,000 RPS
at steady peaks; actual started/success/dropped remain separately measured.

Activation is a shared future existing phase boundary with at least 15 minutes
provisioning lead, selected in an idle added-traffic phase. Extra schedules cover
only the remaining original phases, with identical phase identifiers and the
original end. Keep earlier 76,291-RPS peaks explicitly identified in reports.

The Go client accepts zero-rate idle phases only with explicit allow_idle=true;
normal configuration validation stays strict. Idle phases offer zero requests,
zero-to-positive and positive-to-zero ramps conserve exact counts, and all
requests retain original phase attribution and existing lateness/drop rules.

Metadata boost schema: peak_rps, base_peak_rps, start_epoch,
measurement_offset_seconds, phases (remaining additional-rate phases),
client_digest, status, manifest_sha256. Additional output is
<instance>/boost/{config.json,status.json,samples.ndjson,metrics.ndjson}.

Validate each generator's raw accounting/final totals independently. Combine
counts and latency histograms over one wall-time interval, with per-source
coverage, CPU, dispatch and loss checks. Never use union coverage to hide a
missing additional source. Use original server metrics/GC once. A missing,
late, failed, invalid or incomplete source blocks authoritative comparisons for
affected future phases; it does not retroactively invalidate earlier phases.
Partial phase ratios stay null. Do not relax any existing quality thresholds.

Extra clients cannot delete servers; they finish at the original end with finite
Job deadlines and results PVC retention. The observer waits for both client sets
and independently captures every source. Existing original experiment remains
unchanged; only the comparison metadata, observer, and new resources change.

Before deployment: meaningful red/green Go/Python regressions, race/vet,
independent content/security review PASS >=85, image digest verification and
server-side dry-run. Authorization to add this load is explicit in the session;
no further routine approval question is needed.
