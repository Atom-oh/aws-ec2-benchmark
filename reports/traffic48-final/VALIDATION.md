# Verification evidence

All checks run against the isolated PR worktree on 2026-11-06. No AWS workload was started or changed.

- Existing dashboard data build and legacy comparison validation: passed before UI edits.
- Existing traffic48 analyzer/orchestration tests: 86 passed (`analyzer-tests.txt`).
- Go traffic client: `go test ./...` passed in `docker/traffic-client` (`client-tests.txt`).
- Report statistics and archive tests: 6 passed (`report-tests.txt`). Includes request-weighted pooled p99, matched intersections, rejecting nonzero exit ramps, retaining other validation flags, exact restored bytes, nonempty-destination rejection, and corrupt-part rejection.
- Historical flex48 load tests: 5 passed (`flex48-tests.txt`).
- Browser checks at 1440 and 390 pixels: passed, no page errors or document overflow. Selectors show expected values, strict empty cohorts render as unavailable, route switching destroys/recreates six charts (`browser-tests.txt`, `browser-1440.png`, `browser-390.png`). Screenshots show the idle-qualified day-two low cohort.
- Entire archive: 19 part checksums and all 189 decompressed file sizes/SHA-256 digests passed, 5,867,605,722 verified bytes (`raw-verification.json`). Streaming verification avoids a second uncompressed copy.
- Source raw credential-pattern scan: no findings across 189 files (`raw-secret-scan.json`). This is a scoped pattern check; IDs/internal addresses are retained provenance, not redacted source bytes.
- Standalone PNG/SVG exported with Python/Matplotlib 3.9.4; mobile screenshot and chart visually inspected.

Independent content/code review is recorded separately in `review.md`.
