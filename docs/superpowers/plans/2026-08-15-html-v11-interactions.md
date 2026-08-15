# HTML v1.1 Interactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the A-share monitor HTML from static SVG output to a self-contained interactive report with full-history time sliders, tri-state Shenwan sorting, newest-first 10-day hot-stock matrix, and clearer 05/06 area/line charts.

**Architecture:** `report_data.json` remains the only renderer input and contains full Canonical history. The renderer emits semantic tables plus compact chart payloads and inlines one reusable JavaScript chart runtime; each chart owns a dual-handle date-window control initialized to the full available history. Table sorting is client-side and preserves an immutable original-order index.

**Tech Stack:** Python 3.11 renderer, plain embedded JavaScript/SVG (no CDN, no runtime network), HTML/CSS, stdlib `unittest`.

## Global Constraints

- Final HTML must remain one offline self-contained file with no external JS/CSS/CDN dependency.
- Every date-series chart defaults to full history.
- Every date-series chart must expose a dual-handle time slider; dragging either edge updates the selected range, and the selected range can be restored to full history with an explicit `全部` control.
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
    dates=sorted({str(r["date"]) for r in rows})[-recent_dates:]
    if newest_first: dates=list(reversed(dates))
    cumulative={}; counts={d:{} for d in dates}
    for row in rows:
        industry=str(row.get("sw_level2") or "待申万映射")
        if industry in ("","未匹配"): industry="待申万映射"
        cumulative[industry]=cumulative.get(industry,0)+1
        d=str(row.get("date") or "")
        if d in counts: counts[d][industry]=counts[d].get(industry,0)+1
    named=sorted(cumulative,key=lambda x:(-cumulative[x],x))[:named_max]
    overflow=set(cumulative)-set(named); matrix_rows=[]
    for industry in named:
        matrix_rows.append({"industry":industry,"counts":[counts[d].get(industry,0) for d in dates],"history_total":cumulative[industry]})
    if overflow:
        matrix_rows.append({"industry":"其他行业汇总","counts":[sum(counts[d].get(i,0) for i in overflow) for d in dates],"history_total":sum(cumulative[i] for i in overflow)})
    return {"dates":dates,"rows":matrix_rows}
```

Add these fields to the report object:

```python
"hot_stock_matrix": build_hot_stock_matrix(hot_all),
"hot_stocks_history": hot_all,
"hot_stocks_latest": latest_hot,
```

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
- Example config:

```javascript
{
  dates:["2026-08-13","2026-08-14"],
  series:[{name:"市场宽度",values:[-0.5861,-0.1091],kind:"line",axis:"left",unit:"%"}],
  leftAxis:{title:"市场宽度",unit:"%"},
  rightAxis:null,
  zeroLine:true
}
```

- Each chart wrapper includes `.time-range-start`, `.time-range-end`, `.time-range-label`, `.time-range-all`.

- [ ] **Step 1: Write failing HTML contract tests**

```python
class HtmlTimeControlsTest(unittest.TestCase):
    def test_every_time_chart_has_dual_range_and_defaults_full_history(self):
        html=render_html(self.report)
        charts=html.count('data-time-chart="1"')
        self.assertGreaterEqual(charts,6)
        self.assertEqual(html.count('class="time-range-start"'),charts)
        self.assertEqual(html.count('class="time-range-end"'),charts)
        self.assertIn('start.value="0"',html)
        self.assertIn('end.value=String(Math.max(0,dates.length-1))',html.replace(" ",""))
        self.assertEqual(html.count('class="time-range-all"'),charts)

    def test_final_html_inlines_runtime_without_network_dependency(self):
        html=render_html(self.report)
        self.assertIn("function mountTimeChart",html)
        self.assertNotIn("<script src=",html)
        self.assertNotIn("https://",html.lower())
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_html_time_controls -v`

Expected: FAIL because current charts are static SVG.

- [ ] **Step 3: Implement generic JavaScript time-window runtime**

```javascript
function mountTimeChart(el,config){
  const dates=config.dates||[];
  const start=el.querySelector('.time-range-start');
  const end=el.querySelector('.time-range-end');
  start.min=end.min="0";
  start.max=end.max=String(Math.max(0,dates.length-1));
  start.value="0";
  end.value=String(Math.max(0,dates.length-1));
  function windowRange(){
    let a=Number(start.value),b=Number(end.value);
    if(a>b){const t=a;a=b;b=t;} return [a,b];
  }
  function redraw(){
    const [a,b]=windowRange();
    drawSvg(el.querySelector('.time-chart-canvas'),config,a,b);
    el.querySelector('.time-range-label').textContent=dates.length?`${dates[a]} — ${dates[b]}`:'暂无数据';
  }
  start.addEventListener('input',redraw); end.addEventListener('input',redraw);
  el.querySelector('.time-range-all').addEventListener('click',()=>{start.value="0";end.value=String(Math.max(0,dates.length-1));redraw();});
  redraw();
}
```

Implement `drawSvg(container,config,a,b)` to slice every series to `[a,b]`, recalculate left/right numeric domains from visible values, render SVG line/area/bar shapes, render a visible legend and y-axis titles, and attach `<title>` to every visible point/bar with `date + series.name + formatted value + unit`. Area series close their polygon to the plot baseline and use translucent fill plus a solid outline.

- [ ] **Step 4: Replace static time-SVG calls with semantic chart mounts**

```python
def _time_chart(chart_id: str, config: dict) -> str:
    payload=json.dumps(config,ensure_ascii=False).replace("</","<\\/")
    return f'''<div class="time-chart" data-time-chart="1" id="{chart_id}">
      <div class="time-chart-canvas"></div>
      <div class="time-range"><input class="time-range-start" type="range"><input class="time-range-end" type="range">
      <span class="time-range-label"></span><button class="time-range-all" type="button">全部</button></div>
      <script type="application/json" class="time-chart-config">{payload}</script>
    </div>'''
```

Read `assets/market_monitor_charts.js` at render time and inline it. Initialization must parse each `.time-chart-config` and call `mountTimeChart()` for every `[data-time-chart="1"]`.

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
- Every industry row carries `data-original-index`, `data-amount`, `data-return`, `data-volatility`.

- [ ] **Step 1: Write failing sorting-contract tests**

```python
class ShenwanSortingTest(unittest.TestCase):
    def test_three_columns_have_tri_state_sort_controls(self):
        html=render_html(self.report)
        for key in ("amount","return","volatility"):
            self.assertIn(f'data-sort-key="{key}"',html)
        compact=html.replace(" ","")
        self.assertIn("constcycle={original:'desc',desc:'asc',asc:'original'}",compact)
        self.assertIn("data-original-index=",html)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_sw_industry_sorting -v`

Expected: FAIL because current table has filtering but no tri-state sorting.

- [ ] **Step 3: Add stable original-order row metadata**

```python
for original_index,row in enumerate(sw_rows):
    amount="" if row.get("成交额") is None else row["成交额"]
    ret="" if row.get("日收益率") is None else row["日收益率"]
    vol="" if row.get("20日年化波动率") is None else row["20日年化波动率"]
    attrs=(f'data-original-index="{original_index}" data-amount="{amount}" '
           f'data-return="{ret}" data-volatility="{vol}"')
```

Render sortable `<button>` elements in the three relevant `<th>` cells with `data-sort-state="original"`.

- [ ] **Step 4: Add tri-state client sorting compatible with search/filter**

```javascript
const cycle={original:'desc',desc:'asc',asc:'original'};
function sortSwRows(key,state){
  const tbody=document.querySelector('#sw-industry-table tbody');
  const rows=[...tbody.querySelectorAll('tr[data-original-index]')];
  rows.sort((a,b)=>{
    if(state==='original') return Number(a.dataset.originalIndex)-Number(b.dataset.originalIndex);
    const av=Number(a.dataset[key]),bv=Number(b.dataset[key]);
    const aok=a.dataset[key]!==''&&Number.isFinite(av),bok=b.dataset[key]!==''&&Number.isFinite(bv);
    if(!aok&&!bok) return Number(a.dataset.originalIndex)-Number(b.dataset.originalIndex);
    if(!aok) return 1; if(!bok) return -1;
    return state==='desc'?bv-av:av-bv;
  });
  rows.forEach(r=>tbody.appendChild(r)); applySwFilters();
}
document.querySelectorAll('[data-sort-key]').forEach(btn=>btn.addEventListener('click',()=>{
  document.querySelectorAll('[data-sort-key]').forEach(other=>{if(other!==btn) other.dataset.sortState='original';});
  btn.dataset.sortState=cycle[btn.dataset.sortState||'original'];
  sortSwRows(btn.dataset.sortKey,btn.dataset.sortState);
}));
```

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

- [ ] **Step 1: Write failing chart/layout tests**

```python
class CrowdingChartTest(unittest.TestCase):
    def test_sw_share_is_area_and_turnover_is_line(self):
        html=render_html(self.report)
        self.assertIn('id="sw-share-chart"',html)
        self.assertIn('id="sw-turnover-chart"',html)
        self.assertIn('"name": "通信设备成交额占全A"',html)
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

Expected: FAIL on current dual-line/combined presentation.

- [ ] **Step 3: Build explicit 05 area and line configs**

```python
industries=["通信设备","计算机设备","元件","半导体"]
dates=[row["date"] for row in sw_history]
share_series=[]; turnover_series=[]
for industry in industries:
    share_values=[(row.get("targets") or {}).get(industry,{}).get("amount_share_of_a") for row in sw_history]
    turnover_values=[(row.get("targets") or {}).get(industry,{}).get("turnover") for row in sw_history]
    share_series.append({"name":f"{industry}成交额占全A","kind":"area","axis":"left","unit":"%","values":share_values})
    turnover_series.append({"name":f"{industry}换手率","kind":"line","axis":"left","unit":"%","values":turnover_values})
sw_share={"dates":dates,"leftAxis":{"title":"成交额占全A","unit":"%"},"rightAxis":None,"zeroLine":False,"series":share_series}
sw_turnover={"dates":dates,"leftAxis":{"title":"换手率","unit":"%"},"rightAxis":None,"zeroLine":False,"series":turnover_series}
```

Remove the HTML table/chart labeled `四行业成交额合计`; keep Canonical combined fields only for validation if already present.

- [ ] **Step 4: Build explicit 06 area and line configs**

```python
innovation_dates=[row["date"] for row in innovation]
innovation_share={"dates":innovation_dates,"leftAxis":{"title":"成交额占全A","unit":"%"},"rightAxis":None,"zeroLine":False,
                  "series":[{"name":"创新药成交额占全A","kind":"area","axis":"left","unit":"%","values":[row.get("amount_share_of_a") for row in innovation]}]}
innovation_turnover={"dates":innovation_dates,"leftAxis":{"title":"换手率","unit":"%"},"rightAxis":None,"zeroLine":False,
                     "series":[{"name":"创新药换手率","kind":"line","axis":"left","unit":"%","values":[row.get("turnover") for row in innovation]}]}
```

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
    broken=self.html.replace('class="time-range-start"','class="missing-range-start"',1)
    result=validate_report(self.report,broken)
    self.assertIn("time_slider_contract_missing",result["failures"])

def test_hot_matrix_must_be_newest_first(self):
    broken=copy.deepcopy(self.report)
    broken["hot_stock_matrix"]["dates"]=["2026-08-13","2026-08-14"]
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

```python
chart_count=html.count('data-time-chart="1"')
if chart_count and (html.count('class="time-range-start"')!=chart_count or html.count('class="time-range-end"')!=chart_count):
    failures.append("time_slider_contract_missing")
dates=(report.get("hot_stock_matrix") or {}).get("dates") or []
if len(dates)>10: failures.append("hot_matrix_more_than_ten_dates")
if dates!=sorted(dates,reverse=True): failures.append("hot_matrix_not_newest_first")
for key in ("amount","return","volatility"):
    if f'data-sort-key="{key}"' not in html: failures.append(f"sw_sort_control_missing:{key}")
if "四行业成交额合计" in html: failures.append("combined_amount_presentation_present")
if '"kind": "area"' not in html: failures.append("share_area_chart_missing")
```

Keep existing checks for external dependencies, activity proxy, latest market date and hot-stock counts.

- [ ] **Step 4: Update runtime contract**

Merge these fields into `config/html_production_runtime.json` without deleting Canonical-v2 fields:

```json
{
  "html_version": "1.1",
  "time_slider_default": "full_history",
  "hot_matrix_default_dates": 10,
  "hot_matrix_order": "newest_left",
  "sw_sort_cycle": ["original", "desc", "asc", "original"],
  "share_chart_kind": "area",
  "turnover_chart_kind": "line"
}
```

- [ ] **Step 5: Run full suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 6: Produce 2026-08-14 acceptance HTML**

Run the PR acceptance workflow. Inspect `report_data.json`, HTML and validator JSON to verify: sliders cover all history on initial render; 01 controls expose all three sort fields; 04 has 10 descending dates while `hot_stocks_history` remains complete; 05 has four-industry share area + turnover line and no combined-amount presentation; 06 has share area + turnover line; HTML validator failures are empty.

- [ ] **Step 7: Commit**

```bash
git add validate_market_monitor_html.py tests/test_html_validator.py config/html_production_runtime.json .github/workflows/daily_market_monitor.yml docs/DAILY_PIPELINE.md
git commit -m "feat: enforce html v1.1 interaction contracts"
```
