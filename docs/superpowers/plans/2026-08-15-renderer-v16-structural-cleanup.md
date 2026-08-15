# A-share Monitor Renderer v1.6 Structural Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed-row/array-chart behavior with a stable rolling workbook contract, repair known historical gaps, and produce a clean 2026-08-14 mother workbook for future daily updates.

**Architecture:** Keep the validated rolling-workbook model, but move dynamic dashboard layout and chart data into explicit worksheet ranges. Renderer v1.6 will update existing chart objects through formula-backed series references, dynamically place dashboard sections, field-merge history without erasing verified cells, and run a preflight historical-gap scan before delivery. The obsolete auxiliary sheet is removed and the innovation sheet becomes `06_创新药交易拥挤度`.

**Tech Stack:** Python 3.11, artifact_tool workbook API, GitHub Actions, AKShare/Eastmoney/official exchange daily statistics.

## Global Constraints

- Never rebuild the workbook from scratch during daily production.
- Never delete/recreate existing charts solely to refresh data; existing chart objects must be preserved.
- Chart series must reference worksheet ranges rather than embedded Python arrays for the market-width dashboard.
- Missing values must never be replaced with zero or unrelated cross-source values.
- Existing verified historical non-null fields must never be overwritten by a null fallback value.
- `06_综合拥挤度_辅助` is removed; innovation becomes `06_创新药交易拥挤度`.
- Innovation uses only real supplier board turnover; the 20-day volume activity proxy is retired.
- Daily production runs historical-gap preflight before current-day rendering.

---

### Task 1: Lock v1.6 workbook contract with failing tests

**Files:**
- Modify: `tests/test_renderer_contract.py`
- Modify: `tests/test_production_v2_contract.py`
- Create: `tests/test_renderer_v16_structure.py`

**Interfaces:**
- Consumes: current v1.5 renderer entrypoint and config.
- Produces: assertions for v1.6 entrypoint, six-sheet contract, formula-backed chart series, dynamic dashboard, and preflight gap scan.

- [ ] Add tests that require `run_excel_renderer.py` to import v1.6 and config `renderer_version == "1.6"`.
- [ ] Add tests requiring sheet list to exclude `06_综合拥挤度_辅助` and include `06_创新药交易拥挤度`.
- [ ] Add source-contract tests forbidding `delete_all_drawings`, forbidding innovation activity proxy, and requiring chart `category_formula`/`formula` references for 00/03 market charts.
- [ ] Add tests requiring a `scan_history_gaps` preflight and historical-mode index fetch when target date is not current China date.
- [ ] Run targeted tests and confirm RED against v1.5.

### Task 2: Implement history-gap preflight and historical backfill primitives

**Files:**
- Create: `market_monitor/history_preflight.py`
- Modify: `market_monitor/production.py`
- Modify: `market_monitor/pipeline.py`

**Interfaces:**
- Produces: `scan_history_gaps(...) -> list[Gap]`, `fetch_index_date_historical(...)`, and recoverable innovation share fill from same-day all-A denominator.

- [ ] Test 8/13 missing index fields are detected as recoverable.
- [ ] Test historical target dates bypass current quote endpoint and use historical K-line fetch.
- [ ] Test innovation share is calculated only when same-day denominator exists.
- [ ] Test unresolved gaps are recorded explicitly rather than silently ignored.
- [ ] Implement minimal preflight/backfill logic and run tests GREEN.

### Task 3: Implement Renderer v1.6 structural cleanup

**Files:**
- Create: `run_excel_renderer_v16.py`
- Modify: `run_excel_renderer.py`
- Modify: `config/excel_renderer.json`
- Modify: `prepare_render_bundle.py`

**Interfaces:**
- Consumes: rolling validated workbook + render bundle.
- Produces: cleaned workbook with dynamic 00 layout, normalized 03/04/05/06 styles, renamed innovation sheet, formula-backed chart series, no obsolete auxiliary ranges.

- [ ] Add test fixture assertions for dynamic 04 full-detail section and 05 section starting after it.
- [ ] Add test that 03 market chart helper data is contiguous and style-copied through the latest row.
- [ ] Add test that 04/05/06 appended rows copy complete style from the prior valid body row.
- [ ] Add test that 05 and innovation duplicate row-4 headings are blank/removed.
- [ ] Implement v1.6 with existing chart objects preserved and market charts linked to helper ranges by formulas.
- [ ] Remove obsolete Q:Z helper traces where they are no longer part of the v1.6 contract.
- [ ] Rename innovation sheet and update all references/status text.
- [ ] Run renderer contract tests GREEN.

### Task 4: Repair the 2026-08-14 mother workbook and known data debt

**Files:**
- Input: `A股每日市场监控_20260814_最终修正版.xlsx`
- Output: `A股每日市场监控_20260814_v16正式母表.xlsx`

**Interfaces:**
- Uses: artifact_tool only.
- Produces: the new validated mother workbook.

- [ ] Backfill 2026-08-13 上证50 / Choice微盘 / 中证全指 from historical index data only.
- [ ] Backfill 2026-08-07 all-A denominator from a documented same-day market total source; recompute innovation share.
- [ ] Rebuild 03 helper ranges from 02 in ascending date order; ensure final rows are 8/12, 8/13, 8/14 with correct values.
- [ ] Convert 00/03 market chart series to worksheet references and set axis label interval/plot spacing so final dates do not overlap the right axis.
- [ ] Replace 00 fixed seven-row hot-stock block with recent-date matrix plus complete current-day hot-stock detail, then place 05/06 below dynamically.
- [ ] Normalize 01/03/04/05/06/99 body fonts, borders, row heights, date/percent/amount formats.
- [ ] Remove `06_综合拥挤度_辅助`, rename innovation to `06_创新药交易拥挤度`, and remove duplicate row-4 labels.
- [ ] Verify formula errors=0, required sheets, chart counts/anchors, market chart last categories=8/14, 04 full count=12, 05 latest official date, 01 latest date, innovation turnover no gaps, innovation share no recoverable gaps.
- [ ] Render 00/03/04/05/06/99 for visual review.

### Task 5: Add daily production validation and rolling-mother registration

**Files:**
- Modify: `.github/workflows/daily_market_monitor.yml`
- Modify: `config/web_production_runtime.json`
- Modify: `docs/DAILY_PIPELINE.md`

**Interfaces:**
- Produces: fail-fast production contract before artifact delivery.

- [ ] Run history preflight before current-day payload generation.
- [ ] Fail on chart formula range not ending at latest data row, dashboard overlap, obsolete sheet reappearance, or style-contract regression.
- [ ] Allow explicit unresolved-gap WARN only for non-recoverable data with source/status recorded.
- [ ] Register v1.6 validated workbook as next rolling mother.
- [ ] Run full repository tests and open PR for CI.

### Task 6: Final verification

- [ ] Run all tests.
- [ ] Inspect final workbook key ranges and chart formula references.
- [ ] Confirm no formula errors and no stale/zero/cross-source fills.
- [ ] Confirm all user-listed layout defects are resolved.
- [ ] Open PR, wait for CI, and merge only after success.
