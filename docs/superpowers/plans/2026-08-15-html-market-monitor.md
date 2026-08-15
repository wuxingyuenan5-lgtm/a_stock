# A股每日市场监控 HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained daily HTML market monitor driven by one normalized `report_data.json`, with history preflight/backfill before rendering and no Excel dashboard dependency.

**Architecture:** Existing collectors remain the source of current-day production data. A new history layer persists index history and scans recoverable gaps; a report-data builder joins market history, index history, Shenwan snapshots/crowding, hot-stock history, and innovation history into one JSON contract. A standard-library HTML renderer consumes only that contract and emits a single offline HTML file with inline CSS/SVG/JavaScript; a validator checks data freshness, row counts, gaps, and external-dependency bans.

**Tech Stack:** Python 3.11 standard library, existing pandas/requests/AKShare collectors, inline HTML/CSS/SVG/vanilla JavaScript, GitHub Actions.

## Global Constraints

- HTML is the primary presentation artifact; Excel is not an intermediate dependency.
- HTML must be one offline file with no CDN, server, external JS, external CSS, or remote image dependency.
- Missing values may not be replaced with zero, proxy metrics, or cross-definition values.
- Historical index gaps must use historical K-line data, never current quotes.
- Innovation turnover accepts supplier-direct board turnover only; the 20-day volume-activity proxy is retired.
- Existing verified non-null history must never be erased by a later null.
- Daily production runs history preflight before rendering and reports unresolved gaps explicitly.
- Hot-stock detail is dynamically sized and must show all rows for the report date.
- The HTML report date must equal the newest market-history date.

---

### Task 1: History persistence and preflight/backfill

**Files:**
- Create: `market_monitor/history_preflight.py`
- Modify: `market_monitor/pipeline.py`
- Create: `tests/test_history_preflight.py`
- Create: `data/history/indices_history.csv` during migration/production

**Interfaces:**
- Consumes: daily `indices` payload, `data/history/market_core.csv`, innovation Eastmoney history.
- Produces: `append_index_history(path, records)`, `scan_history_gaps(root, report_date)`, `backfill_index_date(date, definitions)`, and `preflight_history(root, report_date)`.

- [ ] Write failing tests proving that index history appends by `(date,name)`, preserves verified non-null values on null reruns, detects 2026-08-13 index gaps, and never uses current quotes for historical repair.
- [ ] Run `python -m unittest tests.test_history_preflight -v` and verify failures are caused by missing implementation.
- [ ] Implement the minimal history module and persist current-day index records from `pipeline.run`.
- [ ] Add historical Eastmoney K-line backfill for missing index dates with bounded retries/timeouts.
- [ ] Add market-denominator gap reporting; only mark a denominator repaired when an explicit same-definition historical value is available.
- [ ] Run the focused tests, then the full suite.
- [ ] Commit the history layer.

### Task 2: Standardized report-data contract

**Files:**
- Create: `build_report_data.py`
- Create: `tests/test_report_data.py`
- Modify: `prepare_render_bundle.py`

**Interfaces:**
- Consumes: `daily_payload.json`, `market_core.csv`, `indices_history.csv`, `sw_industry_latest.csv`, `sw_analysis_daily_second.csv`, innovation history, hot-stock archive/current payload.
- Produces: `output/YYYY-MM-DD/report_data.json` with keys `meta`, `market_history`, `indices_history`, `sw_industry_latest`, `hot_stock_matrix`, `hot_stocks_latest`, `sw_crowding_history`, `innovation_history`, `quality`.

- [ ] Write failing contract tests for all required top-level keys and report-date consistency.
- [ ] Add tests that `hot_stocks_latest` count equals payload `hot_count`, and innovation turnover contains no proxy field.
- [ ] Implement the builder using existing persisted histories and current output files only; no network access inside this stage.
- [ ] Compute recoverable innovation amount-share only from same-day innovation amount and same-day all-A amount.
- [ ] Emit explicit quality items for unresolved gaps rather than silently dropping dates.
- [ ] Run focused and full tests.
- [ ] Commit the report-data contract.

### Task 3: Self-contained HTML renderer

**Files:**
- Create: `render_market_monitor_html.py`
- Create: `tests/test_html_renderer.py`

**Interfaces:**
- Consumes: one `report_data.json`.
- Produces: `A股每日市场监控_YYYYMMDD.html`.

- [ ] Write failing tests asserting there is no `http://`, `https://`, `<script src=`, or `<link href=` in the rendered file.
- [ ] Add tests proving 12/23/30 hot-stock rows render without a seven-row cap.
- [ ] Add tests proving the market structure chart contains latest report-date values for advance, decline, limit-up, and limit-down.
- [ ] Implement semantic page sections and shared CSS using the approved deep-blue visual system.
- [ ] Implement market-structure and market-breadth charts as inline SVG generated from full historical arrays, with right/left plot padding and native `<title>` tooltips.
- [ ] Implement dynamic tables for recent indices, Shenwan industry, hot-stock matrix/full detail, four-industry crowding, innovation, and quality.
- [ ] Add lightweight local sorting/filtering for the Shenwan table using embedded vanilla JavaScript only.
- [ ] Run focused and full tests.
- [ ] Commit the renderer.

### Task 4: HTML validator

**Files:**
- Create: `validate_market_monitor_html.py`
- Create: `tests/test_html_validator.py`

**Interfaces:**
- Consumes: `report_data.json` and rendered HTML.
- Produces: `html_validation.json` and process exit code 0 only on PASS/WARN according to contract; structural failures exit non-zero.

- [ ] Write failing tests for stale report date, mismatched hot-count/detail rows, unresolved recoverable innovation-share gaps, external dependencies, and missing latest chart date.
- [ ] Implement validator checks from the approved design spec.
- [ ] Classify source-unavailable but non-recoverable data as WARN; structural inconsistencies as FAIL.
- [ ] Run focused and full tests.
- [ ] Commit the validator.

### Task 5: Workflow and web production integration

**Files:**
- Modify: `.github/workflows/daily_market_monitor.yml`
- Create: `config/html_production_runtime.json`
- Modify: `docs/DAILY_PIPELINE.md`
- Modify: `tests/test_production_v2_contract.py`

**Interfaces:**
- Consumes: existing daily data production plus Tasks 1-4.
- Produces: workflow artifact containing `report_data.json`, HTML, validation JSON, and source manifest.

- [ ] Write failing production-contract tests requiring preflight before report-data build, then render, then validate.
- [ ] Add `config/html_production_runtime.json` as the single web entrypoint for HTML production.
- [ ] Update workflow order to `collect -> history preflight -> report_data -> HTML render -> HTML validate -> upload/archive`.
- [ ] Keep Excel tooling available but remove it from the required HTML path.
- [ ] Update daily-pipeline documentation and run full tests.
- [ ] Commit workflow integration.

### Task 6: 2026-08-14 migration prototype and acceptance

**Files:**
- Create/update: migration/backfill data under `data/history/` only when verified.
- Produce: `output/2026-08-14/report_data.json`
- Produce: `output/2026-08-14/A股每日市场监控_20260814.html`
- Produce: `output/2026-08-14/html_validation.json`

**Interfaces:**
- Consumes: current validated 8/14 data and verified historical backfills.
- Produces: first accepted HTML prototype and a repeatable production baseline.

- [ ] Run history preflight for 2026-08-14 and repair 2026-08-13 three-index history using historical K-line calls.
- [ ] Repair 2026-08-07 all-A denominator only from a same-definition verified historical source; if unavailable, keep the gap explicit and mark WARN rather than fabricate a value.
- [ ] Build `report_data.json`, render HTML, and run validator.
- [ ] Verify market structure and limit-up/down latest point is 2026-08-14.
- [ ] Verify all 12 report-date >100亿元 stocks render, and historical matrices are not row-capped.
- [ ] Verify Shenwan and crowding effective dates match underlying source data.
- [ ] Verify innovation has supplier-direct turnover only and no activity proxy.
- [ ] Open/render the final HTML for visual inspection and correct axis-edge/table-overflow issues.
- [ ] Commit only verified migration data and production code; do not invent unresolved historical values.
