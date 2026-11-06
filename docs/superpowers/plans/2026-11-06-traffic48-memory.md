# Traffic48 memory reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement the disjoint tasks below. Steps use checkbox syntax for tracking.

**Goal:** Reduce analyzer peak and idle memory while preserving existing results.

**Architecture:** Stream JSONL decoding, compact retained histograms, avoid
discarded GC correlation work, and execute each analysis in a child process.

**Tech Stack:** Python standard library, existing unittest suite, Linux RSS.

**Spec:** docs/superpowers/specs/2026-11-06-traffic48-memory-design.md

## Global Constraints

- No changes to EC2/EKS workloads, images, traffic schedules, JVMs or end time.
- No relaxed accounting/coverage/client quality checks; exact report parity.
- Current-data target peak <8 GiB, preferably4 GiB; verify rather than assume.
- One collector/foreground analyzer; atomic report preservation on failure.
- Independent exact-hash content/code/security PASS>=85 before watch replacement.
- Shared untracked experiment sources; disjoint ownership, no commits.

## Review Focus

- Torn final JSONL line versus malformed complete/interior lines.
- Invalid histograms, noncanonical keys, large integers and boolean counts.
- Equal-p99 ordering and exact inclusive GC time boundaries.
- Child failure/reaping and prior report preservation.
- Exact old/new report parity on immutable39-hour data and fixtures.

### Task 1: Analyzer memory and GC work (Maxwell)

Files: scripts/traffic48_analysis.py; tests/springboot-traffic48/test_memory_analysis.py.
Interfaces: existing read_jsonl(path), report(run_dir), and report JSON unchanged.

- [x] Write failing semantic/parity and bounded-storage tests.
- [x] Implement line decoding, compact storage and equivalent spike work.
- [x] Run all Python regressions and compare independent reference fixtures.

### Task 2: Return analyzer memory after every report (host)

Files: scripts/springboot_traffic48.py; tests/springboot-traffic48/test_memory_runner.py;
docs/springboot-traffic48.md.
Interface: analyze_isolated(output) executes the existing analyze CLI using the
current Python interpreter, explicit repository cwd, check=True and no shell.

- [x] Test child command, failure propagation, atomic prior-result preservation.
- [x] Use the child in collect/watch paths; direct analyze remains the child entry.
- [x] Run focused regressions and document memory behavior.

### Task 3: Full-data evidence and independent review (host + Laplace)

- [x] Freeze current inputs and already computed old report before edits/capture.
- [x] Run optimized full analysis once; measure peak RSS and wall time.
- [x] Compare reports recursively; resolve every semantic discrepancy.
- [x] Obtain independent PASS>=85 and exact artifact hash.

### Task 4: Watch-only deployment and verification (host)

- [x] Preserve review records and gate; replace identity-checked watcher only.
- [x] Verify single watcher, child memory return, fresh collection/report and workloads.
- [x] Record before/after memory/time, parity and process IDs; report to user.

## Completion evidence

2026-11-06: 86 tests passed; frozen full report byte-identical; peak RSS
6.834 GiB and analysis 841.570 s. Independent PASS 100 on artifact
`fc27327d32f583bcb171ce376dc29cae88271274adea5d89f3db2518b14bd76c`.
Old watcher 3426201 stopped; replacement 1431719 completed its first collection
and analysis. Live child 1445382 exited, parent RSS 20.25 MiB, observed child
peak 7.44 GiB on the larger 42.27-hour dataset. All 18 workload Jobs remain
active with unchanged UIDs/restarts and original end 2026-11-06T10:17:51Z.
Both task agents closed. Detailed evidence: results/springboot-traffic48-memory/20261106/README.md.
