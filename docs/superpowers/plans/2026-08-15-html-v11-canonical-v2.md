# HTML v1.1 + Canonical 数据母表 v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 A股每日市场监控升级为全历史可拖拽交互图表、申万行业三态排序、百亿成交近10日反向矩阵，并建立 Raw → Canonical → manifest → report_data → HTML 的正式数据质量闸门。

**Architecture:** 继续使用 GitHub CSV 作为长期可审计历史，但把“采集结果”和“正式历史”分离。`canonical_store.py` 负责字段级无损 upsert、主键唯一、数学复核和历史修改审计；`build_report_data.py` 只读 Canonical。HTML Renderer 继续生成单文件离线 HTML，但图表升级为内嵌交互脚本，所有时间图共享同一套 range slider / tooltip / legend 组件。

**Tech Stack:** Python 3.11、标准库 csv/json/hashlib、现有 AKShare/requests 数据采集、原生 HTML/CSS/JavaScript + SVG（代码内嵌，无 CDN）。

## Global Constraints

- 最终 HTML 必须单文件、自包含、离线可打开；禁止 CDN、外部 JS/CSS 和运行时网络请求。
- 所有时间序列图默认展示全历史，并具备双端拖拽时间滚轴、整体拖动选区和“全部”恢复。
- 01 申万行业的成交额、日收益率、20日年化波动率必须支持 原始顺序 → 降序 → 升序 → 原始顺序。
- 04 百亿成交矩阵默认最近 10 个有记录交易日，最新日期最左；Canonical `hot_stocks.csv` 保存全部已验证历史。
- 05/06 的“成交额占全A”使用面积图；换手率使用折线图；标题、图例、单位、tooltip 必须明确。
- HTML 不展示“四行业成交额合计”表或历史图。
- 创新药只接受供应商直接板块换手率；20日成交量活跃度代理永久禁止。
- Canonical 写入必须主键唯一、空值不覆盖已验证非空、历史非当天改写可审计、大规模删除/日期回退 FAIL。
- Canonical Validator FAIL 时禁止生成正式 `report_data.json` 和正式 HTML。

---

### Task 1: Canonical store 与 manifest 基础合同

**Files:**
- Create: `market_monitor/canonical_store.py`
- Create: `tests/test_canonical_store.py`
- Create: `config/canonical_contract.json`

**Interfaces:**
- Produces: `upsert_canonical_csv(path: Path, key_fields: tuple[str,...], incoming_rows: list[dict], numeric_fields: set[str], report_date: str) -> dict`
- Produces: `validate_canonical_dataset(root: Path, report_date: str) -> dict`
- Produces: `write_canonical_manifest(root: Path, report_date: str, validation: dict) -> Path`

- [ ] **Step 1: Write failing tests for null-preserving upsert, duplicate keys, and historical modification audit**

```python
def test_null_rerun_never_erases_verified_value(tmp_path):
    from market_monitor.canonical_store import upsert_canonical_csv
    path = tmp_path / "market_core.csv"
    upsert_canonical_csv(path, ("date",), [{"date":"2026-08-14","total_amount_100m":21415.4}], {"total_amount_100m"}, "2026-08-14")
    result = upsert_canonical_csv(path, ("date",), [{"date":"2026-08-14","total_amount_100m":None}], {"total_amount_100m"}, "2026-08-14")
    assert result["rows"][0]["total_amount_100m"] == 21415.4


def test_historical_non_today_change_is_recorded(tmp_path):
    from market_monitor.canonical_store import upsert_canonical_csv
    path = tmp_path / "market_core.csv"
    upsert_canonical_csv(path, ("date",), [{"date":"2026-08-13","advance":1000}], {"advance"}, "2026-08-14")
    result = upsert_canonical_csv(path, ("date",), [{"date":"2026-08-13","advance":1001}], {"advance"}, "2026-08-14")
    assert result["historical_changes"] == [{"key":{"date":"2026-08-13"},"fields":["advance"]}]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_canonical_store -v`
Expected: import/function failures because `canonical_store.py` does not exist.

- [ ] **Step 3: Implement field-level canonical upsert and SHA manifest helpers**

Implementation rules:
- serialize CSV as UTF-8 BOM;
- preserve original row order except new keys append chronologically;
- numeric empty input never erases non-empty existing value;
- duplicate primary keys after merge raise `CanonicalValidationError`;
- return `rows`, `inserted_keys`, `historical_changes`, `sha256_before`, `sha256_after`.

- [ ] **Step 4: Add dataset validation tests**

```python
def test_market_math_contract_fails_on_bad_breadth(tmp_path):
    from market_monitor.canonical_store import validate_market_rows
    rows=[{"date":"2026-08-14","advance":2306,"decline":2871,"flat":154,"effective_stocks":5331,"market_breadth":0.5}]
    result=validate_market_rows(rows)
    assert "market_breadth_mismatch:2026-08-14" in result["failures"]
```

Validation must cover:
- `advance + decline + flat == effective_stocks`;
- breadth formula within `1e-9`;
- `hot_amount_100m <= total_amount_100m`;
- percentage/share ranges `[0,1]` where applicable;
- dates strictly nondecreasing after canonical sort;
- no duplicate primary keys.

- [ ] **Step 5: Run Task 1 tests GREEN and commit**

Run: `python -m unittest tests.test_canonical_store -v`
Expected: PASS.

Commit: `feat: add canonical data store and manifest validation`

---

### Task 2: Raw → Canonical production write path

**Files:**
- Modify: `run_daily.py`
- Modify: `market_monitor/history_preflight.py`
- Modify: `build_report_data.py`
- Create: `tests/test_canonical_pipeline.py`

**Interfaces:**
- Consumes: Task 1 `upsert_canonical_csv`, `validate_canonical_dataset`.
- Produces: `data/raw/YYYY-MM-DD/*.json|csv` and canonical history under existing `data/history/*.csv` paths.

- [ ] **Step 1: Write failing pipeline tests**

Tests must prove:
1. raw files are written before canonical mutation;
2. `build_report_data()` reads canonical files only;
3. canonical FAIL prevents report build;
4. same-date null rerun cannot erase verified values.

- [ ] **Step 2: Run targeted tests RED**

Run: `python -m unittest tests.test_canonical_pipeline -v`

- [ ] **Step 3: Implement raw snapshot persistence**

For each production run persist at least:
- `data/raw/<date>/daily_payload.json`
- `data/raw/<date>/hot_stocks.csv`
- `data/raw/<date>/source_manifest.json`
- `data/raw/<date>/validation.json`

Raw files are append/archive artifacts and never read by HTML Renderer.

- [ ] **Step 4: Route formal history updates through canonical store**

Replace direct overwrite paths for:
- `market_core.csv`
- `indices_history.csv`
- `hot_stocks.csv`
with canonical field-level upserts.

- [ ] **Step 5: Gate `build_report_data()` on canonical validation**

Before building report:
```python
validation = validate_canonical_dataset(root, target_date)
if validation["status"] == "FAIL":
    raise RuntimeError("canonical_validation_failed")
```
Write `output/<date>/canonical_validation.json` and `canonical_manifest.json`.

- [ ] **Step 6: Run Task 2 tests GREEN and commit**

Commit: `feat: gate report generation on canonical history validation`

---

### Task 3: 百亿成交历史与近10日矩阵合同

**Files:**
- Modify: `build_report_data.py`
- Modify: `tests/test_report_data.py`
- Create/Modify: `tests/test_hot_stock_history.py`

**Interfaces:**
- Produces: `build_hot_stock_matrix(rows, recent_dates=10, named_max=13)` where output `dates` is descending.

- [ ] **Step 1: Write RED tests**

```python
def test_hot_matrix_is_latest_left_and_defaults_to_ten_dates():
    matrix = build_hot_stock_matrix(rows_for_12_dates())
    assert len(matrix["dates"]) == 10
    assert matrix["dates"] == sorted(matrix["dates"], reverse=True)


def test_hot_history_keeps_records_outside_display_window():
    report = build_report_data("2026-08-14", root)
    assert len(report["hot_stock_history"]) > len(report["hot_stocks_latest"])
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Split storage history from display matrix**

`report_data.json` adds:
- `hot_stock_history`: all canonical rows through report date;
- `hot_stock_matrix`: only latest 10 recorded trading dates, newest first;
- `hot_stocks_latest`: report-date detail.

- [ ] **Step 4: Run GREEN and commit**

Commit: `feat: keep full hot-stock history with ten-day display matrix`

---

### Task 4: Shared interactive time-range chart engine

**Files:**
- Create: `market_monitor/html_chart_runtime.py`
- Modify: `render_market_monitor_html.py`
- Create: `tests/test_html_time_range.py`

**Interfaces:**
- Produces: `embedded_chart_runtime() -> str`
- HTML data contract: each time chart container has `data-time-chart="1"`, JSON series payload, and two range inputs initialized to full range.

- [ ] **Step 1: Write RED tests**

Verify generated HTML contains for every time chart:
- two draggable range controls;
- `data-range-start="0"` and `data-range-end="last"` semantics;
- “全部” reset button;
- tooltip layer;
- legend buttons;
- no external scripts/links.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement reusable inline JS/SVG runtime**

Runtime behavior:
- initial selection `[0, n-1]`;
- left/right handles cannot cross;
- dragging selected track shifts whole window preserving width;
- redraw recalculates y-domain from selected observations;
- reset restores full history;
- legend click toggles series and recomputes y-domain;
- tooltip uses actual date/value/unit;
- `resize` redraws safely.

- [ ] **Step 4: Convert market structure and market breadth to shared runtime**

Market structure retains:
- advance positive bars;
- decline negative bars;
- limit-up positive line on right scale;
- limit-down negative line on right scale.

- [ ] **Step 5: Run GREEN and commit**

Commit: `feat: add full-history draggable time ranges to HTML charts`

---

### Task 5: 01 申万行业三态排序

**Files:**
- Modify: `render_market_monitor_html.py`
- Create: `tests/test_sw_industry_sorting.py`

**Interfaces:**
- HTML rows include immutable `data-original-index`.
- Sortable headers include `data-sort-field` for `成交额`, `日收益率`, `20日年化波动率`.

- [ ] **Step 1: Write RED DOM-contract tests**

Verify header controls and embedded script contain state sequence `original -> desc -> asc -> original` and restore by original index.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement sorting JS**

Rules:
- only one active primary sort;
- filtering/search executes first, sorting second;
- clearing filters does not reset sort;
- third click restores canonical original order;
- missing numeric values always sort last for asc/desc.

- [ ] **Step 4: Run GREEN and commit**

Commit: `feat: add three-state Shenwan industry sorting`

---

### Task 6: 05 四行业拥挤度图表重构

**Files:**
- Modify: `render_market_monitor_html.py`
- Modify: `tests/test_html_layout.py`
- Create: `tests/test_crowding_charts.py`

**Interfaces:**
- Produces two charts only for historical visualization:
  1. `四行业成交额占全A` area chart;
  2. `四行业换手率` line chart.

- [ ] **Step 1: Write RED tests**

Assert:
- four-industry combined amount table absent;
- combined amount history chart absent;
- area chart includes 4 named series and `%` unit;
- turnover line chart includes 4 named series and `%` unit;
- both have time slider markers.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement stacked-or-overlaid transparent area rendering**

Use overlaid semi-transparent areas, not stacked sums, because each industry share is an independent percentage of all-A turnover. Legend explicitly names 通信设备/计算机设备/元件/半导体.

- [ ] **Step 4: Run GREEN and commit**

Commit: `feat: clarify four-industry crowding charts`

---

### Task 7: 06 创新药面积图 + 换手率折线

**Files:**
- Modify: `render_market_monitor_html.py`
- Modify: `validate_market_monitor_html.py`
- Create: `tests/test_innovation_charts.py`

**Interfaces:**
- Chart 1: area series `创新药成交额占全A`, unit `%`.
- Chart 2: line series `创新药换手率`, unit `%`.

- [ ] **Step 1: Write RED tests**

Assert both charts have explicit titles, legends, tooltip labels, full-history sliders, and no activity-proxy text/field.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement charts and validator checks**

Validator additionally fails if:
- `20日成交量活跃度代理` appears in HTML or report JSON;
- innovation share chart is missing area-series marker;
- turnover chart lacks direct-turnover series marker.

- [ ] **Step 4: Run GREEN and commit**

Commit: `feat: use area and direct-turnover charts for innovation drug`

---

### Task 8: Canonical anomaly checks and production workflow gate

**Files:**
- Modify: `market_monitor/canonical_store.py`
- Modify: `.github/workflows/daily_market_monitor.yml`
- Modify: `validate_market_monitor_html.py`
- Create: `tests/test_canonical_anomalies.py`
- Modify: `tests/test_production_v2_contract.py`

**Interfaces:**
- Workflow order becomes:
  `collect raw -> canonical upsert -> canonical validate -> build report -> render HTML -> HTML validate -> artifact/persist`.

- [ ] **Step 1: Write RED tests for workflow order and anomalies**

Anomaly tests:
- market total amount <= 0 FAIL;
- hot amount > total amount FAIL;
- share outside `[0,1]` FAIL;
- >10% canonical row-count shrink without explicit migration flag FAIL;
- unexpected latest-date regression FAIL;
- historical changes appear in manifest.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Add canonical validation step to workflow before report build**

Workflow persists:
- `canonical_validation.json`;
- `canonical_manifest.json`;
- raw archive;
- canonical CSV;
- report/HTML only after canonical validation is not FAIL.

- [ ] **Step 4: Run GREEN and commit**

Commit: `feat: enforce canonical quality gate before HTML production`

---

### Task 9: 8/14 acceptance artifact and regression verification

**Files:**
- Modify: `.github/workflows/daily_market_monitor.yml` acceptance step if necessary
- Modify: `docs/DAILY_PIPELINE.md`

**Interfaces:**
- Produces artifact containing HTML, `report_data.json`, `canonical_validation.json`, `canonical_manifest.json`, `html_validation.json`.

- [ ] **Step 1: Run full unit suite**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 2: Build 2026-08-14 acceptance report**

Run in CI using canonical 8/14 data.

- [ ] **Step 3: Verify acceptance invariants**

Must confirm:
- all time charts default full history and include draggable range controls;
- 01 three-state sort controls present;
- 04 exactly latest 10 dates with 8/14 at left;
- all historical hot-stock CSV rows remain stored;
- 05 has no combined-amount table and has area + turnover charts;
- 06 has area + direct turnover charts only;
- no external dependency;
- Canonical validator has zero FAIL;
- HTML validator has zero FAIL.

- [ ] **Step 4: Update pipeline documentation**

Document Raw/Canonical separation, manifest, production gate, and HTML v1.1 behavior.

- [ ] **Step 5: Commit and final review**

Commit: `docs: finalize HTML v1.1 canonical v2 production pipeline`

Then review PR diff, CI status, and artifact before merge; do not merge automatically unless explicitly approved.
