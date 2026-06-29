# Report Reference

A benchmark produces two artifacts that together form a stable contract:
1. the **log-format** the in-pod script prints (what the parser reads), and
2. the **report** (`results/<name>/report-charts.html` + a parser that injects data + a
   published copy under `reports/`).

## Log-format contract

The in-pod script prints a header plus per-metric lines. Keep it line-oriented and
CSV-ish so a parser is trivial, and make failure explicit so a dead op is a comparable data
point, not a silent gap.

```
INSTANCE: c8g.xlarge
ARCH: aarch64
SERVER_VERSION: 24.8.14.39        # avoid a label that collides with a sed placeholder token
SET: 1
METRIC,run,v1,v2,v3               # per-op rows; FAILED:<code> in a cell on error
op00,1,1234,210,205
op01,1,FAILED:241,SKIPPED,SKIPPED
INSERT_ROWS_PER_SEC: 232379       # or INSERT_*: FAILED:<reason>
JOIN_MS: 1152
```

Gotcha: don't print a label whose text equals a sed placeholder (e.g. printing
`CLICKHOUSE_VERSION:` while the template substitutes `CLICKHOUSE_VERSION`). The global sed will
rewrite the label. Use a distinct label like `SERVER_VERSION:`.

## Parser (`scripts/generate-<name>-report.py`)

Pattern (see `scripts/generate-clickhouse-report.py` for a full example):

- `BASE_DIR` relative to the script (`Path(__file__).resolve().parent.parent`), never a
  hardcoded absolute path.
- Read `results/<name>/<instance>/run*.log` (skip empty files). Aggregate across repeats —
  e.g. median of best-hot per op; **only compute a total if all expected ops are present**, else
  null + count the missing as failures (a truncated log must not rank artificially well).
- Classify each instance: `arch` (Graviton/Intel/AMD), generation, family (C/M/R), `mem_mb`
  from `config/instances-4vcpu.txt`, `fits_in_ram` (mem ≥ dataset), and **price** from the
  On-Demand map (copy from an existing `generate-*-report.py`). Derive `value = speed/$`.
- Inject the payload (including the raw query/op text so the report can show it) into the HTML
  by **regex-replacing the contents of `<script id="ch-data" type="application/json">…</script>`**
  — re-runnable, unlike a one-shot placeholder. Also write `results/<name>/data.json`.
- After injecting, **publish a self-contained copy** to `reports/<name>-report.html` and ensure
  `reports/index.html` has a card linking it (copy an existing card block).

## Report HTML (`results/<name>/report-charts.html`)

Follow the standard look (CSS vars `--graviton:#10b981 --intel:#3b82f6 --amd:#ef4444`, cards,
chart-section, filterable table). Match the richness of `reports/nginx-report.html` /
`reports/clickhouse-report.html` (~14 charts):

- Top-N ranking (horizontal bar), the primary metric
- **gen × arch** grouped bar, **family × arch** grouped bar
- **RAM tier** (8/16/32GB) average + a same-CPU RAM-pair chart (shows memory advantage)
- generation improvement %, latest-gen detail
- price-performance **bubble** (x=price, y=metric), value Top-15, "avoid" Bottom-10
- secondary metrics (INSERT/JOIN/etc.)
- per-op explorer: a dropdown to pick an op → all instances compared (rankings differ per op)
- a "raw SQL/ops used" section, a filterable full-results table, and an insights/conclusion box

### Two non-negotiables learned the hard way

- **Inline Chart.js, do not use a CDN.** code-server's Live Preview blocks external scripts, so
  a `<script src="https://cdn…">` leaves every chart blank. Download `chart.umd.min.js` once and
  inline it into the HTML (`<script>…lib…</script>`), escaping any `</script>` as `<\/script>`.
  The parser only rewrites the `ch-data` script, so the inlined lib persists across re-runs.
- **Render data independently of charts.** Build the cards, table, query list, and per-op table
  first, then wrap the Chart.js calls in `try/catch` and show a small "charts unavailable"
  banner on failure. That way a charting error (or blocked lib) never blanks the whole report.

## Validation (`tests/<name>/validate.sh`)

The project's stand-in for unit tests — no live cluster needed:
- YAML parses (`python3 -c "import yaml; list(yaml.safe_load_all(open(f)))"`).
- Substitute a sample amd64 (c8i.xlarge) and arm64 (c8g.xlarge) instance and run
  `kubectl apply --dry-run=client`; assert **zero placeholder leaks**.
- Assert `podAntiAffinity`, `backoffLimit: 0`, no hardcoded memory limit, RAM-relative settings.
- `bash -n` the run script; assert the 51-instance list and chained-pipe sed.
- `python3 -m py_compile` the parser and run it on empty/partial input (graceful).
- Report HTML parses; Chart.js is inlined (no external `src=`).
