# HTML v1.1 Interactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the A-share monitor HTML from static SVG output to a self-contained interactive report with full-history time sliders, tri-state Shenwan sorting, newest-first 10-day hot-stock matrix, and clearer 05/06 area/line charts.

**Architecture:** `report_data.json` remains the only renderer input and contains full Canonical history. The renderer emits semantic tables plus compact chart payloads and inlines one reusable JavaScript chart runtime; each chart owns a dual-handle date-window control initialized to the full available history. Table sorting is client-side and preserves an immutable original-order index.

**Tech Stack:** Python 3.11 renderer, plain embedded JavaScript/SVG (no CDN, no runtime network), HTML/CSS, stdlib `unittest`.

## Global Constraints

- Final HTML must remain one offline self-contained file with no external JS/CSS/CDN dependency.
- Every date-series chart defaults to full history.
- Every date-series chart must expose a dual-handle time slider; dragging either edge or the selected window updates axes and data.
- Tooltip must show date, metric name, value and unit.
- Legends and axis units must make each series unambiguous.
- Shenwan `成交额`, `日收益率`, `20日年化波动率` sort states cycle original → descending → ascending → original.
- Hot-stock matrix defaults to 10 recorded dates, latest date at the left; Canonical CSV retains all history.
- 05 amount-share is area, 05 turnover is line; no four-industry combined-amount table/chart.
- 06 innovation amount-share is area, turnover is line; activity proxy remains forbidden.

---

### Task 1: Make report-data display windows independent from Canonical retention

**Files:**
- Modify: `build_report_data.py`
- Modify: `tests/test_report_data.py`

**Interfaces:**
- `build_hot_stock_matrix(rows: list[dict], recent_dates: int = 10, named_max: int = 13, newest_first: bool = True) -> dict`
- `hot_stock_matrix.dates` contains only the display window.
- `hot_stocks_history` contains all Canonical hot-stock rows up to report date.

- [ ] **Step 1: Write failing tests for newest-first 10-date matrix and full retained history**

```python
def test_hot_matrix_defaults_to_ten_dates_newest_first(self):
    rows=[]
    for day in range(1, 13):
        rows.append({"date":f"2026-08-{day:02d}","stock_code":f"{day:06d}","sw_level2":"半导体"})
    matrix=build_hot_stock_matrix(rows)
    self.assertEqual(len(matrix["dates"]),10)
    self.assertEqual(matrix["dates"][0],"2026-08-12")
    self.assertEqual(matrix["dates"][-1],"2026-08-03")

def test_report_keeps_all_hot_stock_history_even_when_matrix_is_ten_days(self):
    report=build_report_data("2026-08-14", self.root)
    self.assertGreater(len({r["date"] for r in report["hot_stocks_history"]}), 10)
    self.assertEqual(len(report["hot_stock_matrix"]["dates"]), 10)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_report_data -v`

Expected: FAIL because matrix defaults to 6 ascending dates and `hot_stocks_history` is absent.

- [ ] **Step 3: Implement the display/retention split**

```python
def build_hot_stock_matrix(rows, recent_dates=10, named_max=13, newest_first=True):
    dates = sorted({str(r["date"]) for r in rows})[-recent_dates:]
    if newest_first:
        dates = list(reversed(dates))
    ...

# report contract
"hot_stock_matrix": matrix,
"hot_stocks_history": hot_all,
"hot_stocks_latest": latest_hot,
```

Counts must be computed using the date positions actually returned by `matrix["dates"]`; no later reversal in the HTML renderer.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_report_data -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add build_report_data.py tests/test_report_data.py
git commit -m "feat: separate hot-stock history from ten-day display matrix"
```

---

### Task 2: Reusable full-history time-window chart runtime

**Files:**
- Create: `assets/market_monitor_charts.js`
- Modify: `render_market_monitor_html.py`
- Create: `tests/test_html_time_controls.py`

**Interfaces:**
- Produces browser function: `mountTimeChart(element, config)`
- `config` shape:

```javascript
{
  dates: ["2026-01-05", ...],
  series: [{name:"市场宽度", values:[...], kind:"line|area|bar", axis:"left|right", unit:"%|家"}],
  leftAxis: {title:"上涨/下跌家数", unit:"家"},
  rightAxis: {title:"涨停/跌停家数", unit:"家"},
  zeroLine: true
}
```

- Each chart wrapper must include `.time-range-start`, `.time-range-end`, `.time-range-label`, and `.time-range-all`.

- [ ] **Step 1: Write failing HTML contract tests**

```python
class HtmlTimeControlsTest(unittest.TestCase):
    def test_every_time_chart_has_dual_range_and_defaults_full_history(self):
        html = render_html(self.report)
        self.assertGreaterEqual(html.count('data-time-chart="1"'), 4)
        self.assertEqual(html.count('class="time-range-start"'), html.count('data-time-chart="1"'))
        self.assertEqual(html.count('class="time-range-end"'), html.count('data-time-chart="1"'))
        self.assertIn('start.value="0"', html)
        self.assertIn('end.value=String(dates.length-1)', html)
        self.assertIn('class="time-range-all"', html)

    def test_final_html_inlines_runtime_without_network_dependency(self):
        html = render_html(self.report)
        self.assertIn("function mountTimeChart", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("https://", html.lower())
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_html_time_controls -v`

Expected: FAIL because current charts are static SVG.

- [ ] **Step 3: Implement generic JS chart runtime**

The runtime must:

```javascript
function mountTimeChart(el, config) {
  const dates = config.dates || [];
  const start = el.querySelector('.time-range-start');
  const end = el.querySelector('.time-range-end');
  start.min = end.min = "0";
  start.max = end.max = String(Math.max(0, dates.length - 1));
  start.value = "0";
  end.value = String(Math.max(0, dates.length - 1));

  function normalizedWindow() {
    let a = Number(start.value), b = Number(end.value);
    if (a > b) [a,b] = [b,a];
    return [a,b];
  }
  function redraw() {
    const [a,b] = normalizedWindow();
    drawSvg(el.querySelector('.time-chart-canvas'), config, a, b);
    el.querySelector('.time-range-label').textContent = dates.length ? `${dates[a]} — ${dates[b]}` : '暂无数据';
  }
  start.addEventListener('input', redraw);
  end.addEventListener('input', redraw);
  el.querySelector('.time-range-all').addEventListener('click', () => {
    start.value="0"; end.value=String(Math.max(0,dates.length-1)); redraw();
  });
  redraw();
}
```

`drawSvg()` must recalculate x/y domains from the selected `[a,b]` range, render line/area/bar kinds, legends, axis titles/units, and point/segment `<title>` tooltip text. For an `area` series, fill the polygon down to the chart baseline with translucent fill and draw a solid outline.

- [ ] **Step 4: Replace static time-SVG functions with semantic chart mounts**

`render_market_monitor_html.py` should read `assets/market_monitor_charts.js` and inline its content inside `<script>...</script>`. Add a helper:

```python
def _time_chart(chart_id: str, config: dict) -> str:
    payload = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
    return f'''<div class="time-chart" data-time-chart="1" id="{chart_id}">
      <div class="time-chart-canvas"></div>
      <div class="time-range"><input class="time-range-start" type="range"><input class="time-range-end" type="range">
      <span class="time-range-label"></span><button class="time-range-all" type="button">全部</button></div>
      <script type="application/json" class="time-chart-config">{payload}</script>
    </div>'''
```

At page initialization, call `mountTimeChart()` for every `[data-time-chart="1"]` element.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_html_time_controls tests.test_html_renderer tests.test_html_validator -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add assets/market_monitor_charts.js render_market_monitor_html.py tests/test_html_time_controls.py
git commit -m "feat: add full-history interactive time sliders"
```

---

### Task 3: Shenwan industry tri-state sorting

**Files:**
- Modify: `render_market_monitor_html.py`
- Create: `tests/test_sw_industry_sorting.py`

**Interfaces:**
- Sortable headers carry `data-sort-key="amount|return|volatility"` and `data-sort-state="original|desc|asc"`.
- Every industry row carries `data-original-index` plus numeric `data-amount`, `data-return`, `data-volatility` attributes.

- [ ] **Step 1: Write failing sorting-contract tests**

```python
class ShenwanSortingTest(unittest.TestCase):
    def test_three_columns_have_tri_state_sort_controls(self):
        html=render_html(self.report)
        for key in ("amount","return","volatility"):
            self.assertIn(f'data-sort-key="{key}"', html)
        self.assertIn("const cycle={original:'desc',desc:'asc',asc:'original'}", html.replace(" ",""))
        self.assertIn("data-original-index=", html)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_sw_industry_sorting -v`

Expected: FAIL because current table has filtering but no tri-state sort metadata/runtime.

- [ ] **Step 3: Add stable original-order metadata and clickable headers**

Rows must preserve input order exactly:

```python
for original_index, row in enumerate(sw_rows):
    attrs = (
        f'data-original-index="{original_index}" '
        f'data-amount="{row.get("成交额") if row.get("成交额") is not None else ""}" '
        f'data-return="{row.get("日收益率") if row.get("日收益率") is not None else ""}" '
        f'data-volatility="{row.get("20日年化波动率") if row.get("20日年化波动率") is not None else ""}"'
    )
```

- [ ] **Step 4: Add client-side state machine compatible with filters/search**

```javascript
const cycle={original:'desc',desc:'asc',asc:'original'};
function sortSwRows(key,state){
  const rows=[...tbody.querySelectorAll('tr[data-original-index]')];
  rows.sort((a,b)=>{
    if(state==='original') return Number(a.dataset.originalIndex)-Number(b.dataset.originalIndex);
    const av=Number(a.dataset[key]), bv=Number(b.dataset[key]);
    if(!Number.isFinite(av) && !Number.isFinite(bv)) return Number(a.dataset.originalIndex)-Number(b.dataset.originalIndex);
    if(!Number.isFinite(av)) return 1; if(!Number.isFinite(bv)) return -1;
    return state==='desc' ? bv-av : av-bv;
  });
  rows.forEach(r=>tbody.appendChild(r));
  applySwFilters();
}
```

Only one header is the active sort field; changing fields resets the previously active header to `original`.

- [ ] **Step 5: Run tests**

Run: `python -m unittest tests.test_sw_industry_sorting tests.test_html_renderer -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add render_market_monitor_html.py tests/test_sw_industry_sorting.py
git commit -m "feat: add tri-state Shenwan industry sorting"
```

---

### Task 4: Redesign 05/06 charts and remove combined-amount presentation

**Files:**
- Modify: `render_market_monitor_html.py`
- Modify: `tests/test_html_layout.py`
- Create: `tests/test_crowding_charts.py`

**Interfaces:**
- 05 chart IDs: `sw-share-chart`, `sw-turnover-chart`
- 06 chart IDs: `innovation-share-chart`, `innovation-turnover-chart`
- Amount-share series use `kind:"area"`; turnover series use `kind:"line"`.

- [ ] **Step 1: Write failing layout/chart tests**

```python
class CrowdingChartTest(unittest.TestCase):
    def test_sw_share_is_area_and_turnover_is_line(self):
        html=render_html(self.report)
        self.assertIn('id="sw-share-chart"',html)
        self.assertIn('"kind": "area"',html)
        self.assertIn('id="sw-turnover-chart"',html)
        self.assertIn('"name": "通信设备换手率"',html)
        self.assertNotIn("四行业成交额合计",html)

    def test_innovation_has_separate_share_area_and_turnover_line(self):
        html=render_html(self.report)
        self.assertIn('id="innovation-share-chart"',html)
        self.assertIn('id="innovation-turnover-chart"',html)
        self.assertIn('"name": "创新药成交额占全A"',html)
        self.assertIn('"name": "创新药换手率"',html)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_crowding_charts tests.test_html_layout -v`

Expected: FAIL on current dual-line charts/combined presentation.

- [ ] **Step 3: Build 05 configs with four explicitly named series**

Share chart:

```python
{
  "dates": dates,
  "leftAxis":{"title":"成交额占全A","unit":"%"},
  "series":[
    {"name":"通信设备成交额占全A","kind":"area","axis":"left","unit":"%","values":...},
    {"name":"计算机设备成交额占全A","kind":"area","axis":"left","unit":"%","values":...},
    {"name":"元件成交额占全A","kind":"area","axis":"left","unit":"%","values":...},
    {"name":"半导体成交额占全A","kind":"area","axis":"left","unit":"%","values":...},
  ]
}
```

Turnover chart mirrors the same four industries with `kind:"line"` and y-axis title `换手率`.

Remove the four-industry combined-amount table and combined-amount historical chart from HTML. Do not delete source fields from Canonical if they are useful for validation; this is a presentation removal.

- [ ] **Step 4: Build separate 06 area and line configs**

```python
share = {"series":[{"name":"创新药成交额占全A","kind":"area","axis":"left","unit":"%","values":shares}], ...}
turn = {"series":[{"name":"创新药换手率","kind":"line","axis":"left","unit":"%","values":turnovers}], ...}
```

Every tooltip is generated from the explicit `name` and `unit` fields; do not infer meaning from color.

- [ ] **Step 5: Run tests**

Run: `python -m unittest tests.test_crowding_charts tests.test_html_layout tests.test_html_time_controls -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add render_market_monitor_html.py tests/test_html_layout.py tests/test_crowding_charts.py
git commit -m "feat: clarify crowding charts with area and line views"
```

---

### Task 5: HTML validator v1.1 contracts and acceptance artifact

**Files:**
- Modify: `validate_market_monitor_html.py`
- Modify: `tests/test_html_validator.py`
- Modify: `config/html_production_runtime.json`
- Modify: `.github/workflows/daily_market_monitor.yml`
- Modify: `docs/DAILY_PIPELINE.md`

**Interfaces:**
- Validator checks time controls, matrix orientation/width, sort controls, area chart kinds, forbidden combined table and offline dependency rule.

- [ ] **Step 1: Add failing validator tests**

```python
def test_missing_time_slider_fails(self):
    result=validate_report(self.report, self.html.replace('class="time-range-start"','class="missing"',1))
    self.assertIn("time_slider_contract_missing",result["failures"])

def test_hot_matrix_must_be_newest_first_and_at_most_ten(self):
    broken=copy.deepcopy(self.report)
    broken["hot_stock_matrix"]["dates"]=["2026-08-01", "2026-08-14"]
    result=validate_report(broken,self.html)
    self.assertIn("hot_matrix_not_newest_first",result["failures"])

def test_combined_amount_presentation_is_forbidden(self):
    result=validate_report(self.report,self.html+"四行业成交额合计")
    self.assertIn("combined_amount_presentation_present",result["failures"])
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_html_validator -v`

Expected: new tests FAIL.

- [ ] **Step 3: Implement HTML v1.1 hard checks**

Add checks for:

- every `data-time-chart="1"` has start/end slider + `全部` reset;
- at least market structure, market breadth, 05 share, 05 turnover, 06 share, 06 turnover are time charts when data exists;
- hot matrix has `<=10` dates, sorted descending, first date is latest recorded hot-stock date;
- three Shenwan sortable keys exist;
- `20日成交量活跃度代理` remains absent;
- `四行业成交额合计` presentation text is absent;
- `kind:"area"` exists for 05/06 share charts;
- no external HTTP/script/link dependency.

- [ ] **Step 4: Update runtime contract**

`config/html_production_runtime.json` must declare:

```json
{
  "html_version": "1.1",
  "time_slider_default": "full_history",
  "hot_matrix_default_dates": 10,
  "hot_matrix_order": "newest_left",
  "sw_sort_cycle": ["original","desc","asc","original"],
  "share_chart_kind": "area",
  "turnover_chart_kind": "line"
}
```

Keep the Canonical v2 fields introduced by the data plan.

- [ ] **Step 5: Run full suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 6: Produce 2026-08-14 acceptance HTML**

Run the PR acceptance build and verify in the artifact:

- all time charts start at full history and sliders can narrow the range;
- 01 sorting cycles correctly after search/filter;
- 04 shows 10 dates newest-left while `hot_stocks.csv` remains full history;
- 05 has four-industry share area chart + turnover line chart and no combined-amount table;
- 06 has innovation share area chart + turnover line chart;
- HTML Validator reports zero failures.

- [ ] **Step 7: Commit**

```bash
git add validate_market_monitor_html.py tests/test_html_validator.py config/html_production_runtime.json .github/workflows/daily_market_monitor.yml docs/DAILY_PIPELINE.md
git commit -m "feat: enforce html v1.1 interaction contracts"
```
