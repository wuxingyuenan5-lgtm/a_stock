# Canonical Data v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a validated Canonical history layer between market-data collection and `report_data.json`, so raw collection results can never silently corrupt the long-lived CSV histories that drive the HTML report.

**Architecture:** Daily collection runs inside a staging root seeded from the currently validated Canonical histories. Candidate CSVs are validated as a coherent snapshot, compared with the previous Canonical snapshot, and promoted atomically only when hard checks pass. A deterministic manifest records hashes, row counts, latest dates, gaps, historical mutations, and warnings; `build_report_data.py` reads only promoted Canonical files.

**Tech Stack:** Python 3.11, stdlib `csv/json/hashlib/shutil/pathlib`, existing `unittest` suite, GitHub Actions, existing AKShare/requests collectors.

## Global Constraints

- Raw collection output must never directly drive HTML.
- Canonical CSV remains the GitHub-auditable long-term store; do not introduce SQLite.
- Canonical primary keys must be unique.
- Same-date reruns must never replace verified non-null history with null.
- Historical changes outside the target date must be explicitly recorded; mass deletions/date rollback are hard failures.
- `advance + decline + flat == effective_stocks` must hold when all fields are present.
- `market_breadth == (advance - decline) / (advance + decline)` within tolerance when the denominator is non-zero.
- `hot_amount_100m <= total_amount_100m`; hot-detail row count for a date must equal `hot_count` when that date has complete detail.
- Innovation share is recoverable only as same-day `innovation amount / all-A amount`; no proxy turnover is permitted.
- Every Canonical manifest must include SHA256, row count, latest date, duplicate-key count, unresolved gaps, warnings, and modified historical dates.
- Canonical validation FAIL must block promotion and HTML delivery.

---

### Task 1: Canonical table specs and deterministic audit primitives

**Files:**
- Create: `market_monitor/canonical_store.py`
- Create: `tests/test_canonical_store.py`

**Interfaces:**
- Produces: `TableSpec(name: str, path: str, key_fields: tuple[str, ...], date_field: str)`
- Produces: `CANONICAL_TABLES: dict[str, TableSpec]`
- Produces: `read_csv_rows(path: Path) -> list[dict[str, str]]`
- Produces: `file_sha256(path: Path) -> str`
- Produces: `audit_table(path: Path, spec: TableSpec) -> dict[str, object]`
- Produces: `diff_history(before: list[dict], after: list[dict], spec: TableSpec, target_date: str) -> dict[str, object]`

- [ ] **Step 1: Write failing tests for unique keys, hashes, latest date, and historical mutation detection**

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import unittest

from market_monitor.canonical_store import TableSpec, audit_table, diff_history

class CanonicalStoreTest(unittest.TestCase):
    def _write(self, path: Path, rows: list[dict]):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)

    def test_audit_reports_duplicate_keys_and_latest_date(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "market.csv"
            self._write(p, [
                {"date":"2026-08-13","advance":"1"},
                {"date":"2026-08-13","advance":"2"},
                {"date":"2026-08-14","advance":"3"},
            ])
            spec = TableSpec("market", "data/history/market_core.csv", ("date",), "date")
            audit = audit_table(p, spec)
            self.assertEqual(audit["row_count"], 3)
            self.assertEqual(audit["latest_date"], "2026-08-14")
            self.assertEqual(audit["duplicate_key_count"], 1)
            self.assertEqual(len(audit["sha256"]), 64)

    def test_diff_history_flags_only_pre_target_changes(self):
        spec = TableSpec("market", "x.csv", ("date",), "date")
        before = [{"date":"2026-08-13","advance":"100"},{"date":"2026-08-14","advance":"200"}]
        after = [{"date":"2026-08-13","advance":"101"},{"date":"2026-08-14","advance":"201"}]
        diff = diff_history(before, after, spec, "2026-08-14")
        self.assertEqual(diff["modified_historical_dates"], ["2026-08-13"])
        self.assertEqual(diff["target_date_changed_keys"], 1)
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `python -m unittest tests.test_canonical_store -v`

Expected: FAIL because `market_monitor.canonical_store` does not exist.

- [ ] **Step 3: Implement the audit layer**

```python
from dataclasses import dataclass
from pathlib import Path
import csv, hashlib

@dataclass(frozen=True)
class TableSpec:
    name: str
    path: str
    key_fields: tuple[str, ...]
    date_field: str

CANONICAL_TABLES = {
    "market_core": TableSpec("market_core", "data/history/market_core.csv", ("date",), "date"),
    "indices_history": TableSpec("indices_history", "data/history/indices_history.csv", ("date","name"), "date"),
    "hot_stocks": TableSpec("hot_stocks", "data/history/hot_stocks.csv", ("date","stock_code"), "date"),
    "innovation": TableSpec("innovation", "data/history/innovation_drug_eastmoney.csv", ("日期",), "日期"),
    "sw_crowding": TableSpec("sw_crowding", "data/history/sw_analysis_daily_second.csv", ("发布日期","指数代码"), "发布日期"),
    "sw_industry_history": TableSpec("sw_industry_history", "data/sw_industry_history.csv", ("日期","指数代码"), "日期"),
}

def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists(): return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def row_key(row: dict, spec: TableSpec):
    return tuple(str(row.get(k) or "") for k in spec.key_fields)

def audit_table(path: Path, spec: TableSpec) -> dict[str, object]:
    rows = read_csv_rows(path)
    seen, duplicates = set(), 0
    for row in rows:
        key = row_key(row, spec)
        if key in seen: duplicates += 1
        seen.add(key)
    dates = [str(r.get(spec.date_field) or "")[:10] for r in rows if r.get(spec.date_field)]
    return {"row_count":len(rows), "latest_date":max(dates, default=None),
            "duplicate_key_count":duplicates,
            "sha256":file_sha256(path) if path.exists() else None}

def diff_history(before, after, spec, target_date):
    b = {row_key(r,spec):r for r in before}; a = {row_key(r,spec):r for r in after}
    modified, target_changed = set(), 0
    for key in set(b) | set(a):
        if b.get(key) == a.get(key): continue
        row = a.get(key) or b.get(key) or {}
        d = str(row.get(spec.date_field) or "")[:10]
        if d and d < target_date: modified.add(d)
        if d == target_date: target_changed += 1
    return {"modified_historical_dates":sorted(modified), "target_date_changed_keys":target_changed,
            "deleted_keys":len(set(b)-set(a)), "added_keys":len(set(a)-set(b))}
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest tests.test_canonical_store -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add market_monitor/canonical_store.py tests/test_canonical_store.py
git commit -m "feat: add canonical history audit primitives"
```

---

### Task 2: Candidate-snapshot validator with cross-field invariants

**Files:**
- Create: `market_monitor/canonical_validation.py`
- Create: `tests/test_canonical_validation.py`

**Interfaces:**
- Consumes: `CANONICAL_TABLES`, `read_csv_rows`, `audit_table`, `diff_history`
- Produces: `validate_candidate(candidate_root: Path, canonical_root: Path, target_date: str) -> dict[str, object]`

- [ ] **Step 1: Write failing tests for mathematical inconsistencies and dangerous history loss**

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import csv, unittest
from market_monitor.canonical_validation import validate_candidate

class CanonicalValidationTest(unittest.TestCase):
    def _write(self, root, rel, fields, rows):
        p = Path(root) / rel; p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

    def test_bad_market_math_fails(self):
        with TemporaryDirectory() as old, TemporaryDirectory() as cand:
            fields=["date","advance","decline","flat","effective_stocks","total_amount_100m","hot_count","hot_amount_100m","market_breadth"]
            row={"date":"2026-08-14","advance":2306,"decline":2871,"flat":154,"effective_stocks":5330,"total_amount_100m":21415,"hot_count":12,"hot_amount_100m":1796,"market_breadth":0.9}
            self._write(old,"data/history/market_core.csv",fields,[row]); self._write(cand,"data/history/market_core.csv",fields,[row])
            result=validate_candidate(Path(cand),Path(old),"2026-08-14")
            self.assertIn("market_effective_stock_mismatch:2026-08-14",result["failures"])
            self.assertIn("market_breadth_mismatch:2026-08-14",result["failures"])

    def test_large_history_deletion_fails(self):
        with TemporaryDirectory() as old, TemporaryDirectory() as cand:
            fields=["date","advance"]
            old_rows=[{"date":f"2026-01-{d:02d}","advance":1} for d in range(1,11)]
            self._write(old,"data/history/market_core.csv",fields,old_rows)
            self._write(cand,"data/history/market_core.csv",fields,old_rows[-1:])
            result=validate_candidate(Path(cand),Path(old),"2026-08-14")
            self.assertTrue(any(x.startswith("mass_history_deletion:market_core") for x in result["failures"]))
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_canonical_validation -v`

Expected: FAIL because validator is missing.

- [ ] **Step 3: Implement hard checks and warning-only anomaly checks**

```python
def _num(value):
    try: return None if value in (None, "") else float(value)
    except (TypeError, ValueError): return None

for name, spec in CANONICAL_TABLES.items():
    candidate_path = candidate_root / spec.path
    canonical_path = canonical_root / spec.path
    audit = audit_table(candidate_path, spec)
    before = read_csv_rows(canonical_path); after = read_csv_rows(candidate_path)
    change = diff_history(before, after, spec, target_date)
    tables[name] = {**audit, **change}
    if audit["duplicate_key_count"]:
        failures.append(f"duplicate_key:{name}")
    if before and len(after) < len(before) * 0.90:
        failures.append(f"mass_history_deletion:{name}:{len(before)}->{len(after)}")

market_rows = read_csv_rows(candidate_root / CANONICAL_TABLES["market_core"].path)
for row in market_rows:
    a,d,f,e = (_num(row.get(k)) for k in ("advance","decline","flat","effective_stocks"))
    if None not in (a,d,f,e) and int(a+d+f) != int(e):
        failures.append(f"market_effective_stock_mismatch:{row['date']}")
    if a is not None and d is not None and a+d:
        expected=(a-d)/(a+d); actual=_num(row.get("market_breadth"))
        if actual is None or abs(expected-actual)>1e-8:
            failures.append(f"market_breadth_mismatch:{row['date']}")
    hot,total=_num(row.get("hot_amount_100m")),_num(row.get("total_amount_100m"))
    if hot is not None and total is not None and hot>total:
        failures.append(f"hot_amount_gt_market:{row['date']}")
```

Sort available market rows by date and add `WARN` when adjacent non-null `total_amount_100m` values have ratio `<0.35` or `>2.8`; do not FAIL solely on that jump.

- [ ] **Step 4: Run validator tests**

Run: `python -m unittest tests.test_canonical_validation -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add market_monitor/canonical_validation.py tests/test_canonical_validation.py
git commit -m "feat: validate canonical market history candidates"
```

---

### Task 3: Stage daily production before Canonical promotion

**Files:**
- Modify: `run_daily.py`
- Create: `market_monitor/canonical_promotion.py`
- Create: `tests/test_canonical_promotion.py`

**Interfaces:**
- Produces: `prepare_stage(root: Path, target_date: str) -> Path`
- Produces: `promote_candidate(stage_root: Path, canonical_root: Path, target_date: str, validation: dict) -> dict[str, object]`

- [ ] **Step 1: Write failing promotion tests with real files**

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import csv, json, unittest
from market_monitor.canonical_promotion import prepare_stage, promote_candidate

class CanonicalPromotionTest(unittest.TestCase):
    def _write_market(self, root: Path, amount: int):
        p=root/"data/history/market_core.csv"; p.parent.mkdir(parents=True,exist_ok=True)
        with p.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["date","total_amount_100m"]); w.writeheader(); w.writerow({"date":"2026-08-14","total_amount_100m":amount})
        return p

    def test_fail_never_changes_canonical_file(self):
        with TemporaryDirectory() as td:
            root=Path(td); canonical=self._write_market(root,21415); before=canonical.read_bytes()
            stage=prepare_stage(root,"2026-08-14"); self._write_market(stage,1)
            with self.assertRaises(RuntimeError):
                promote_candidate(stage,root,"2026-08-14",{"status":"FAIL","failures":["bad"]})
            self.assertEqual(canonical.read_bytes(),before)

    def test_pass_promotes_candidate_and_writes_manifest(self):
        with TemporaryDirectory() as td:
            root=Path(td); self._write_market(root,21415)
            stage=prepare_stage(root,"2026-08-14"); candidate=self._write_market(stage,22000)
            manifest=promote_candidate(stage,root,"2026-08-14",{"status":"PASS","failures":[],"warnings":[],"tables":{}})
            self.assertEqual((root/"data/history/market_core.csv").read_bytes(),candidate.read_bytes())
            saved=json.loads((root/"output/2026-08-14/canonical_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["target_date"],"2026-08-14")
            self.assertEqual(manifest["target_date"],"2026-08-14")
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_canonical_promotion -v`

Expected: FAIL because `canonical_promotion.py` does not exist.

- [ ] **Step 3: Implement staging and atomic promotion**

```python
def prepare_stage(root: Path, target_date: str) -> Path:
    stage=root/"output"/target_date/".canonical_stage"
    shutil.rmtree(stage,ignore_errors=True); stage.mkdir(parents=True,exist_ok=True)
    if (root/"data").exists(): shutil.copytree(root/"data",stage/"data",dirs_exist_ok=True)
    return stage

def _atomic_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True,exist_ok=True)
    tmp=dst.with_name(dst.name+".tmp")
    shutil.copy2(src,tmp); tmp.replace(dst)

def promote_candidate(stage_root, canonical_root, target_date, validation):
    if validation.get("status")=="FAIL": raise RuntimeError("canonical validation failed")
    table_manifest={}
    for name,spec in CANONICAL_TABLES.items():
        src=stage_root/spec.path; dst=canonical_root/spec.path
        if not src.exists(): continue
        before=audit_table(dst,spec) if dst.exists() else {"sha256":None,"row_count":0,"latest_date":None}
        _atomic_copy(src,dst); after=audit_table(dst,spec)
        table_manifest[name]={"before":before,"after":after}
    manifest={"target_date":target_date,"validation_status":validation.get("status"),"tables":table_manifest,
              "warnings":validation.get("warnings",[]),"failures":validation.get("failures",[])}
    out=canonical_root/"output"/target_date/"canonical_manifest.json"; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest
```

Also promote `data/sw_industry_latest.csv` atomically if it exists in staging, but never delete the live file when staging lacks it.

- [ ] **Step 4: Refactor `run_daily.py` to run collectors against staging**

```python
repo_root=Path(".").resolve()
stage_root=prepare_stage(repo_root,args.target_date)
result=run(target_date=args.target_date,config_path=repo_root/args.config,root=stage_root,refresh_mapping=args.refresh_mapping)
payload=result["payload"]
append_index_history(stage_root/"data/history/indices_history.csv",list((payload.get("indices") or {}).values()))
append_hot_stock_history(stage_root/"data/history/hot_stocks.csv",args.target_date,payload.get("hot_stocks") or [])
raw_source=stage_root/"output"/args.target_date
raw_dest=repo_root/"output"/args.target_date/"raw"
shutil.copytree(raw_source,raw_dest,dirs_exist_ok=True)
canonical_validation=validate_candidate(stage_root,repo_root,args.target_date)
promote_candidate(stage_root,repo_root,args.target_date,canonical_validation)
```

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_canonical_promotion tests.test_canonical_validation tests.test_canonical_store -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add run_daily.py market_monitor/canonical_promotion.py tests/test_canonical_promotion.py
git commit -m "feat: gate daily history writes through canonical staging"
```

---

### Task 4: Route historical repairs and innovation derivation through the same gate

**Files:**
- Modify: `run_history_preflight.py`
- Modify: `market_monitor/history_preflight.py`
- Modify: `build_report_data.py`
- Create: `tests/test_canonical_backfill_gate.py`

**Interfaces:**
- Consumes: `prepare_stage`, `validate_candidate`, `promote_candidate`

- [ ] **Step 1: Write failing preflight gate test**

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import csv, unittest
from market_monitor.canonical_promotion import prepare_stage
from market_monitor.history_preflight import append_index_history
from market_monitor.canonical_validation import validate_candidate

class CanonicalBackfillGateTest(unittest.TestCase):
    def test_bad_staged_repair_cannot_erase_verified_index(self):
        with TemporaryDirectory() as td:
            root=Path(td); p=root/"data/history/indices_history.csv"; p.parent.mkdir(parents=True,exist_ok=True)
            fields=["date","name","code","close","return","amount_100m","source","status"]
            with p.open("w",encoding="utf-8-sig",newline="") as f:
                w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerow({"date":"2026-08-13","name":"上证50","code":"1.000016","close":2928.12,"return":-0.0035,"amount_100m":1901.77,"source":"verified","status":"ok"})
            before=p.read_bytes(); stage=prepare_stage(root,"2026-08-14")
            append_index_history(stage/"data/history/indices_history.csv",[{"date":"2026-08-13","name":"上证50","code":"1.000016","close":None,"return":None,"amount_100m":None,"source":"failed","status":"error"}])
            validation=validate_candidate(stage,root,"2026-08-14")
            self.assertNotEqual(validation["status"],"FAIL")
            self.assertEqual(p.read_bytes(),before)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_canonical_backfill_gate tests.test_report_data -v`

Expected: new test fails until preflight uses the staging gate consistently.

- [ ] **Step 3: Change `run_history_preflight.py` to stage → repair → validate → promote**

```python
repo_root=Path(args.root).resolve(); stage=prepare_stage(repo_root,args.target_date)
result=preflight_history(stage,args.target_date,definitions,repair_indices=True)
validation=validate_candidate(stage,repo_root,args.target_date)
manifest=promote_candidate(stage,repo_root,args.target_date,validation)
out=repo_root/"output"/args.target_date/"history_preflight.json"
out.write_text(json.dumps({"preflight":result,"canonical":manifest},ensure_ascii=False,indent=2),encoding="utf-8")
```

Remote failure must leave verified values untouched; `append_index_history` already preserves non-null history on null reruns.

- [ ] **Step 4: Make innovation share deterministic in `build_report_data.py`**

```python
denominator={r["date"]:r.get("total_amount_100m") for r in market_history}
share=amount/denominator[d] if amount is not None and denominator.get(d) not in (None,0) else None
```

Do not read Raw paths, do not trust a stale precomputed share over this same-day calculation, and do not emit `volume_activity_20d`.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_canonical_backfill_gate tests.test_report_data tests.test_history_preflight -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add run_history_preflight.py market_monitor/history_preflight.py build_report_data.py tests/test_canonical_backfill_gate.py tests/test_report_data.py
git commit -m "feat: apply canonical gate to history repairs"
```

---

### Task 5: Workflow gate, manifest artifact, and full regression

**Files:**
- Create: `validate_canonical_data.py`
- Modify: `.github/workflows/daily_market_monitor.yml`
- Modify: `config/html_production_runtime.json`
- Modify: `tests/test_production_v2_contract.py`
- Create: `tests/test_canonical_cli.py`
- Modify: `docs/DAILY_PIPELINE.md`

**Interfaces:**
- CLI: `python validate_canonical_data.py --target-date YYYY-MM-DD --output output/<date>/canonical_validation.json`

- [ ] **Step 1: Write failing workflow and CLI tests**

```python
class CanonicalCliTest(unittest.TestCase):
    def test_runtime_declares_canonical_v2(self):
        cfg=json.loads((ROOT/"config/html_production_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["data_layer"],"canonical_v2")
        self.assertTrue(cfg["raw_direct_render_forbidden"])
```

In `tests/test_production_v2_contract.py`, compare workflow step-name positions and assert:

```python
names=["History preflight and recoverable backfill","Produce normalized payload","Validate Canonical data","Build normalized report data","Render offline HTML","Validate HTML"]
positions=[text.index(f"- name: {name}") for name in names]
self.assertEqual(positions,sorted(positions))
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_canonical_cli tests.test_production_v2_contract -v`

Expected: FAIL on missing CLI/runtime fields/workflow step.

- [ ] **Step 3: Implement CLI and workflow hard stop**

```python
# validate_canonical_data.py
result=validate_candidate(Path("."),Path("."),args.target_date)
Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
if result["status"]=="FAIL": raise SystemExit(1)
```

Add workflow step `Validate Canonical data` before `Build normalized report data`. Include these files in the production artifact: `A股每日市场监控_YYYYMMDD.html`, `report_data.json`, `canonical_manifest.json`, `canonical_validation.json`, `html_validation.json`, `history_preflight.json`, `source_manifest.json`.

- [ ] **Step 4: Run full unit suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Run 2026-08-14 acceptance build**

Verify from the generated JSON files that Canonical failures are empty, 8/13 three-index values remain populated, `hot_stocks.csv` does not shrink, historical mutations are listed, and `report_data.json` is produced only after Canonical validation.

- [ ] **Step 6: Commit**

```bash
git add validate_canonical_data.py .github/workflows/daily_market_monitor.yml config/html_production_runtime.json tests/test_canonical_cli.py tests/test_production_v2_contract.py docs/DAILY_PIPELINE.md
git commit -m "feat: make canonical validation a production gate"
```
