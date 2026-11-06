# Spring Boot Traffic 48 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development / executing-plans. Preserve existing uncommitted work.

**Goal:** Six-instance 48-hour equal-traffic comparison relative to m7i.xlarge.

**Architecture:** A bounded Go arrival scheduler writes second-level aggregate histograms and Actuator metrics. A Python runner prepares isolated Jobs, calibrates the baseline, collects results and computes same-phase relative metrics.

**Tech Stack:** Go standard library, Python standard library + existing PyYAML, EKS/Karpenter.

**Spec:** docs/superpowers/specs/2026-11-04-springboot-traffic48-design.md

## Global Constraints

- Exactly 172800 seconds excluding calibration; six xlarge types in spec; m7i baseline.
- Equal absolute offered traffic; peak 110% measured successful capacity; low calibrated CPU 40%.
- Fixed context/namespace, same AZ, exclusive nodes, no CPU limits, digest-pinned images.
- No changes to the ongoing Flex experiment or existing user edits.
- Preserve offered/dropped/failed requests and mergeable latency histograms.

## Review Focus

- Overloaded or late clients must not silently lower offered traffic.
- Slow responses spanning phase boundaries retain their original phase.
- Missing calibration CPU, restart or invalid generator must block calibration.
- Unequal/partial collection must not be presented as a complete comparison.
- Cleanup permissions, deadlines and selectors cannot reach another experiment.

## Tasks

- [x] 1. Go generator: failing local HTTP tests for equal offered load, timeout/overload, ramp, histograms and phase boundaries; implement and race-test. Files docker/traffic-client/{main.go,main_test.go,go.mod,Dockerfile}.
- [x] 2. Python runner/analyzer: failing tests for schedule total, shared rates, calibration rejection, six isolated manifests, histogram ratios and missing baseline. Files scripts/springboot_traffic48.py, scripts/traffic48_analysis.py, tests/springboot-traffic48/test_traffic48.py.
- [x] 3. Local integration, build/pin client image, independent code/security/content review; fix findings and record evidence.
- [x] 4. Cluster dry-runs and calibration, then prepare reviewed manifests and launch 48-hour Jobs, collect first samples and verify observer. Record any access/approval blockers without claiming launch.

## Execution rulings

User explicitly supplied ongoing test scope and revisions; execute preparation without another design question. Work in the shared checkout using new, disjoint paths because ongoing runner and results are untracked here; do not commit or alter its files. Scratch/build cache stays in /tmp under sandbox permissions. Deploy only after the required quality gate and current checks.

## Execution status (2026-11-04 UTC)

Run `20261104t0900` has independent PASS 100/100, 35 Python regressions,
full Go race/vet and live six-server readiness/GC checks. All six server nodes
are distinct from the preserved Flex experiment. Calibration starts at 09:12:21
UTC and lasts 45 minutes; the detached finite orchestrator launches the 48-hour
measurement only after calibration validation. Task 4 is still in progress until
measurement Jobs actually launch. Review and launch evidence are in
`results/springboot-traffic48/20261104t0900/`.

### Measurement and observer verification (2026-11-04 10:45 UTC)

Calibration completed and all six measurement clients started at 10:17:51 UTC;
48-hour measurement ends 2026-11-06 10:17:51 UTC. All six servers and six
measurement clients remain Running with zero restarts. First samples and the
detached observer are verified; Task 4 is complete while measurement continues.

The running Java image lacks tar, so server GC capture now uses validated file
listing and binary cat reads. Live partial coverage now ends at the excluded
crossing frame's start; real gaps remain invalid and partial ratios remain null.
41 Python regressions and independent PASS 100/100 precede watch-only replacement.
All six GC snapshots recovered; collection errors are zero, raw log coverage
remains an estimate. m8g's first phase retains a genuine dispatch-lag invalid flag.
Current evidence: `intermediate-current.md`, `review-observer-hotfix.md`,
`observer-hotfix.json` under the run directory. Existing Flex benchmark preserved.
