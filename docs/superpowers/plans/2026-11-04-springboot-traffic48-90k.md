# Ongoing benchmark 90,000 RPS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Raise future comparison peaks to 90,000 RPS without restarting servers or changing the original experiment end.

**Architecture:** Six additional independent generators provide the difference at peak phases and preserve the existing ramps. The observer validates each source and combines histograms/counts while retaining original server metrics/GC once.

**Tech Stack:** Go standard library, Python/PyYAML, EKS/Karpenter, ECR.

**Spec:** docs/superpowers/specs/2026-11-04-springboot-traffic48-90k-design.md

## Global Constraints

- User-selected steady peak exactly90000 RPS; original steady low/mid levels unchanged.
- Original 172800-second end and all running servers/original clients preserved.
- mall-apne2-mgmt / benchmark / ap-northeast-2c; six dedicated c6in.2xlarge nodes.
- No CPU limits, no extra cleanup privileges, digest-pinned images, finite deadlines.
- Validate each source; do not relax accounting, coverage, CPU or dispatch checks.
- Preserve unrelated workspace changes; no commits; scratch files only in /tmp.

## Review Focus

- Idle zero-rate phases and ramps must never divide by zero or create phantom arrivals.
- Additional source gaps or missing files must not be concealed by baseline coverage.
- Old peaks stay at their original target; revised targets apply only after activation.
- Original servers and clients must not be deleted/restarted by extra resource lifecycle.
- Combined counts are exact sums of separately planned integer counts; latency percentiles come from merged histograms, never averaged percentiles.

### Task 1: Go idle schedule support (Mill)

Files: docker/traffic-client/{main.go,main_test.go}.
Interface: optional Config.allow_idle=true; keep default validation unchanged.
- [x] Write/run failing real HTTP and count tests for idle/ramp/final drain behavior.
- [x] Implement minimal nonnegative phase validation and safe arrival boundaries.
- [x] Run focused tests, full race and vet; report evidence.

### Task 2: Combined-source analysis (Maxwell)

Files: scripts/traffic48_analysis.py, tests/springboot-traffic48/test_boost_analysis.py.
Consumes metadata boost schema and per-instance boost output from spec.
- [x] Write/run failing tests for combined counts/histograms, missing source, source gaps, final totals, partial ratios, and history/activation boundaries.
- [x] Implement independent source validation and combined summaries with per-source quality.
- [x] Preserve original-only behavior; run all Python regressions.

### Task 3: Additional resource runner and capture (host)

Files: scripts/springboot_traffic48_boost.py, scripts/springboot_traffic48.py,
tests/springboot-traffic48/test_boost_runner.py, docs/springboot-traffic48.md.
- [x] Write/run failing tests for exact90k future schedules, finite isolated unprivileged manifests and independent capture.
- [x] Implement prepare/launch plus additional-source observer capture/termination.
- [x] Verify assembled Go→Python contract, build/push/pin client image.

### Task 4: Review and deploy (host + independent Laplace)

- [x] Independent code/security/content gate PASS >=85 with exact artifact hash.
- [x] Prepare future activation, dry-run, launch six extra clients; replace watch only.
- [x] Verify extra readiness/idle accounting and unchanged original Pod UIDs/restarts/end.
- [x] Record before/after target, activation, next90k peak, and results paths.

## Execution ruling

Existing benchmark approval and the explicit new90k request authorize this
scoped change. Work in the shared checkout with disjoint ownership because all
existing experiment source/results are untracked; preserve them and do not
commit. Run deployments only after current independent quality gate.


## Verification record (2026-11-04 UTC)

- Independent Laplace re-review PASS, content100/100, zero open Critical/Important; canonical ramp defect independently closed.
- Artifact: cd59e954104820f83ee44257628eccd269d1fd5805b851badbd42c682755e995.
- Python65 tests PASS; Go focused/race/vet PASS; actual HTTP contract1200 completed requests and independently reconciled counts.
- Pushed/pinned client digest: sha256:d386c9089ef62639d91307b9537c3d2c0766626d63c61514a2524607b9d2b6b3.
- Six additional clients Ready on distinct c6in.2xlarge nodes in2c; original13 Pod identities/nodes/restarts and separate Flex experiment preserved.
- Watch-only replacement4034910→3426201; one observer process confirmed. First collection has zero errors and all six future-start configs/status captured.
- Activation2026-11-04T15:02:51Z; first revised peak2026-11-04T16:02:51Z (60-second entry ramp); original end2026-11-06T10:17:51Z.
- Live90k peak is still scheduled, not yet measured. Pre-start boost samples are intentionally empty; actual zero-idle/ramp accounting was separately verified by real HTTP contract.
- Evidence: results/springboot-traffic48/20261104t0900/{review-90k.md,boost-contract-verification.json,boost-image-verification.json,boost-launch-verification.json,observer-90k.json,boost-90k-status.md}.
