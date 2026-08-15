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
        fields = list(rows[0])
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
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

    def test_diff_history_flags_only_pre_target_changes_as_history_mutations(self):
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

- [ ] **Step 3: Implement the minimal audit layer**

```python
# market_monitor/canonical_store.py
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

def _key(row, spec): return tuple(str(row.get(k) or "") for k in spec.key_fields)

def audit_table(path: Path, spec: TableSpec) -> dict[str, object]:
    rows = read_csv_rows(path)
    seen, duplicates = set(), 0
    for row in rows:
        key = _key(row, spec)
        duplicates += key in seen
        seen.add(key)
    dates = [str(r.get(spec.date_field) or "")[:10] for r in rows if r.get(spec.date_field)]
    return {"row_count":len(rows), "latest_date":max(dates, default=None),
            "duplicate_key_count":duplicates,
            "sha256":file_sha256(path) if path.exists() else None}

def diff_history(before, after, spec, target_date):
    b, a = {_key(r,spec):r for r in before}, {_key(r,spec):r for r in after}
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
- Result schema: `{"status":"PASS|WARN|FAIL","failures":list[str],"warnings":list[str],"tables":dict,"cross_checks":dict}`

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
            self.assertEqual(result["status"],"FAIL")
            self.assertIn("market_effective_stock_mismatch:2026-08-14",result["failures"])
            self.assertIn("market_breadth_mismatch:2026-08-14",result["failures"])

    def test_large_history_deletion_fails(self):
        with TemporaryDirectory() as old, TemporaryDirectory() as cand:
            fields=["date","advance"]
            old_rows=[{"date":f"2026-01-{d:02d}","advance":1} for d in range(1,11)]
            self._write(old,"data/history/market_core.csv",fields,old_rows)
            self._write(cand,"data/history/market_core.csv",fields,old_rows[-1:])
            result=validate_candidate(Path(cand),Path(old),"2026-08-14")
            self.assertEqual(result["status"],"FAIL")
            self.assertTrue(any(x.startswith("mass_history_deletion:market_core") for x in result["failures"]))
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_canonical_validation -v`

Expected: FAIL because validator is missing.

- [ ] **Step 3: Implement deterministic hard checks**

Implementation must validate at least:

```python
# pseudo-shape inside validate_candidate
if audit["duplicate_key_count"]:
    failures.append(f"duplicate_key:{name}")
if before_count and after_count < before_count * 0.90:
    failures.append(f"mass_history_deletion:{name}:{before_count}->{after_count}")

for row in market_rows:
    if all(_num(row.get(k)) is not None for k in ("advance","decline","flat","effective_stocks")):
        if int(_num(row["advance"]) + _num(row["decline"]) + _num(row["flat"])) != int(_num(row["effective_stocks"])):
            failures.append(f"market_effective_stock_mismatch:{row['date']}")
    if _num(row.get("advance")) is not None and _num(row.get("decline")) is not None:
        denom = _num(row["advance"]) + _num(row["decline"])
        expected = (_num(row["advance"])-_num(row["decline"]))/denom if denom else None
        if expected is not None and abs(expected-_num(row.get("market_breadth"))) > 1e-8:
            failures.append(f"market_breadth_mismatch:{row['date']}")
    if _num(row.get("hot_amount_100m")) is not None and _num(row.get("total_amount_100m")) is not None:
        if _num(row["hot_amount_100m"]) > _num(row["total_amount_100m"]):
            failures.append(f"hot_amount_gt_market:{row['date']}")
```

Also add warnings, not failures, for suspicious but plausible day-over-day jumps, e.g. all-A turnover ratio `<0.35` or `>2.8` versus the previous available trading day. Record historical changes from `diff_history()` in each table audit.

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
- Consumes: existing `market_monitor.production.run(...)`
- Produces: `prepare_stage(root: Path, target_date: str) -> Path`
- Produces: `promote_candidate(stage_root: Path, canonical_root: Path, target_date: str, validation: dict) -> dict[str, object]`
- Produces: `output/<date>/canonical_manifest.json`

- [ ] **Step 1: Write failing promotion tests**

```python
class CanonicalPromotionTest(unittest.TestCase):
    def test_fail_never_changes_canonical_file(self):
        # prepare canonical market_core.csv with known bytes, candidate with different bytes
        # call promote_candidate(..., {"status":"FAIL",...})
        # assert canonical bytes are unchanged and promotion raises RuntimeError
        ...

    def test_pass_promotes_candidate_and_writes_manifest(self):
        # candidate contains a target-date row, validation status PASS
        # assert canonical file now matches candidate and manifest contains before/after sha256
        ...
```

Use real temporary files; do not mock filesystem behavior.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_canonical_promotion -v`

Expected: FAIL because `canonical_promotion.py` does not exist.

- [ ] **Step 3: Implement staging and atomic promotion**

`prepare_stage()` must:

```python
stage = root / "output" / target_date / ".canonical_stage"
shutil.rmtree(stage, ignore_errors=True)
shutil.copytree(root / "data", stage / "data", dirs_exist_ok=True)
return stage
```

`promote_candidate()` must:

- refuse any validation with `status == "FAIL"`;
- copy only paths declared in `CANONICAL_TABLES` plus `data/sw_industry_latest.csv`;
- write through a temporary sibling file and `Path.replace()` to avoid partial writes;
- record before/after SHA256, row counts, latest dates and historical mutations in `canonical_manifest.json`;
- never silently delete a Canonical file because it is absent from staging.

- [ ] **Step 4: Refactor `run_daily.py` to execute collectors against the stage root**

The daily sequence becomes:

```python
stage_root = prepare_stage(Path("."), args.target_date)
result = run(
    target_date=args.target_date,
    config_path=Path(".").resolve() / args.config,
    root=stage_root,
    refresh_mapping=args.refresh_mapping,
)
append_index_history(stage_root / "data/history/indices_history.csv", ...)
append_hot_stock_history(stage_root / "data/history/hot_stocks.csv", ...)
validation = validate_candidate(stage_root, Path("."), args.target_date)
manifest = promote_candidate(stage_root, Path("."), args.target_date, validation)
```

Copy collector artifacts from `stage_root/output/<date>/` to `output/<date>/raw/` before promotion so Raw acquisition evidence remains auditable even when promotion fails.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_canonical_promotion tests.test_canonical_validation tests.test_canonical_store -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add run_daily.py market_monitor/canonical_promotion.py tests/test_canonical_promotion.py
git commit -m "feat: gate daily history writes through canonical staging"
```

---

### Task 4: Route historical repairs and derived innovation share through the same gate

**Files:**
- Modify: `run_history_preflight.py`
- Modify: `market_monitor/history_preflight.py`
- Modify: `build_report_data.py`
- Create: `tests/test_canonical_backfill_gate.py`

**Interfaces:**
- Consumes: `prepare_stage`, `validate_candidate`, `promote_candidate`
- Produces: no new public interface; historical repair commands must use the Canonical gate.

- [ ] **Step 1: Write failing tests proving preflight cannot directly mutate Canonical on invalid repair**

```python
class CanonicalBackfillGateTest(unittest.TestCase):
    def test_history_preflight_repairs_stage_not_live_history(self):
        # canonical indices_history has a verified 8/13 row
        # stage repair returns null/bad candidate
        # after command path, canonical verified row remains unchanged
        ...
```

Also add a `build_report_data` test asserting innovation share is recomputed from Canonical same-day amounts and never trusts a stale precomputed share when the denominator differs.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_canonical_backfill_gate tests.test_report_data -v`

Expected: at least the new gate test FAILS.

- [ ] **Step 3: Change preflight to stage → validate → promote**

`run_history_preflight.py` must prepare a staging root, run `preflight_history(stage_root, ...)`, validate the staged Canonical snapshot, and promote only PASS/WARN candidates with zero hard failures. If remote history is unavailable, retain the old Canonical history and emit WARN; do not rewrite with nulls.

- [ ] **Step 4: Make `build_report_data.py` Canonical-only and recompute deterministic derivatives**

For innovation rows:

```python
share = amount / denominator[d] if amount is not None and denominator.get(d) not in (None, 0) else None
```

Do not read Raw paths and do not accept `volume_activity_20d` anywhere in the output contract.

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
- Produces CLI: `python validate_canonical_data.py --target-date YYYY-MM-DD --output output/<date>/canonical_validation.json`
- Production artifact must include `canonical_manifest.json` and `canonical_validation.json`.

- [ ] **Step 1: Write failing workflow-contract and CLI tests**

Assert the formal order by workflow step names:

```text
History preflight and recoverable backfill
→ Produce normalized payload
→ Validate Canonical data
→ Build normalized report data
→ Render offline HTML
→ Validate HTML
```

Assert `config/html_production_runtime.json` declares `data_layer = "canonical_v2"` and `raw_direct_render_forbidden = true`.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_canonical_cli tests.test_production_v2_contract -v`

Expected: FAIL on missing CLI/runtime contract.

- [ ] **Step 3: Implement CLI and workflow hard stop**

`validate_canonical_data.py` loads the promoted Canonical root, runs the same invariants in audit-only mode, writes JSON, and exits `1` only on FAIL.

The workflow must upload:

```text
A股每日市场监控_YYYYMMDD.html
report_data.json
canonical_manifest.json
canonical_validation.json
html_validation.json
history_preflight.json
source_manifest.json
```

- [ ] **Step 4: Run full unit suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Run an 8/14 acceptance build**

Run locally/CI on the PR branch using the already validated 2026-08-14 data. Verify:

- Canonical validator has `failures=[]`;
- 8/13 three-index records remain populated;
- `hot_stocks.csv` row count does not shrink;
- historical mutations are listed rather than silent;
- `report_data.json` is built only after Canonical validation;
- HTML Validator remains PASS/WARN with zero failures.

- [ ] **Step 6: Commit**

```bash
git add validate_canonical_data.py .github/workflows/daily_market_monitor.yml config/html_production_runtime.json tests/test_canonical_cli.py tests/test_production_v2_contract.py docs/DAILY_PIPELINE.md
git commit -m "feat: make canonical validation a production gate"
```
