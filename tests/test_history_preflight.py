from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class HistoryPreflightContractTest(unittest.TestCase):
    def _write_csv(self, path: Path, fieldnames: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_append_index_history_preserves_verified_non_null_on_null_rerun(self):
        from market_monitor.history_preflight import append_index_history, read_index_history
        with TemporaryDirectory() as td:
            path = Path(td) / "indices_history.csv"
            append_index_history(path, [{"date":"2026-08-13","name":"上证50","code":"1.000016","close":2928.0,"return":0.001,"amount_100m":1500.0,"source":"historical","status":"ok"}])
            append_index_history(path, [{"date":"2026-08-13","name":"上证50","code":"1.000016","close":None,"return":None,"amount_100m":None,"source":"failed rerun","status":"error"}])
            rows = read_index_history(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["close"], 2928.0)
            self.assertEqual(rows[0]["amount_100m"], 1500.0)
            self.assertEqual(rows[0]["status"], "ok")

    def test_scan_history_gaps_detects_missing_three_indices_and_market_denominator(self):
        from market_monitor.history_preflight import scan_history_gaps
        with TemporaryDirectory() as td:
            root = Path(td)
            self._write_csv(root / "data/history/market_core.csv", ["date","total_amount_100m"], [
                {"date":"2026-08-06","total_amount_100m":"25291.46"},
                {"date":"2026-08-10","total_amount_100m":"25207.93"},
                {"date":"2026-08-14","total_amount_100m":"21415.41"},
            ])
            self._write_csv(root / "data/history/indices_history.csv", ["date","name","code","close","return","amount_100m","source","status"], [
                {"date":"2026-08-12","name":"上证50","code":"1.000016","close":"1","return":"0.1","amount_100m":"1","source":"x","status":"ok"},
                {"date":"2026-08-14","name":"上证50","code":"1.000016","close":"1","return":"0.1","amount_100m":"1","source":"x","status":"ok"},
            ])
            self._write_csv(root / "data/history/innovation_drug_eastmoney.csv", ["日期","成交额","换手率"], [
                {"日期":"2026-08-07","成交额":"112898401493","换手率":"0.0366"},
                {"日期":"2026-08-14","成交额":"103727030799","换手率":"0.0438"},
            ])
            gaps = scan_history_gaps(root, "2026-08-14", required_index_dates=["2026-08-13"])
            self.assertEqual(sorted(item["name"] for item in gaps["indices"] if item["date"] == "2026-08-13"), ["Choice微盘","上证50","中证全指"])
            self.assertIn("2026-08-07", gaps["market_denominator_dates"])

    def test_backfill_index_date_uses_historical_fetcher_only(self):
        import market_monitor.history_preflight as hp
        calls = []
        original = hp.fetch_eastmoney_index
        try:
            def fake_fetch(target_date: str, secid: str, name: str):
                calls.append((target_date, secid, name))
                return {"date":target_date,"name":name,"code":secid,"close":1.0,"return":0.01,"amount_100m":2.0,"source":"historical","status":"ok"}
            hp.fetch_eastmoney_index = fake_fetch
            rows = hp.backfill_index_date("2026-08-13", [
                {"name":"上证50","secid":"1.000016"},
                {"name":"Choice微盘","secid":"47.800007"},
                {"name":"中证全指","secid":"1.000985"},
            ])
        finally:
            hp.fetch_eastmoney_index = original
        self.assertEqual(len(rows), 3)
        self.assertEqual({c[0] for c in calls}, {"2026-08-13"})
        self.assertTrue(all(r["status"] == "ok" for r in rows))

    def test_preflight_bootstraps_many_index_gaps_with_one_range_call_per_index(self):
        import market_monitor.history_preflight as hp
        with TemporaryDirectory() as td:
            root = Path(td)
            self._write_csv(root / "data/history/market_core.csv", ["date","total_amount_100m"], [
                {"date":"2026-08-10","total_amount_100m":1}, {"date":"2026-08-11","total_amount_100m":1},
                {"date":"2026-08-12","total_amount_100m":1}, {"date":"2026-08-13","total_amount_100m":1}, {"date":"2026-08-14","total_amount_100m":1},
            ])
            definitions=[{"name":"上证50","secid":"1.000016"},{"name":"Choice微盘","secid":"47.800007"},{"name":"中证全指","secid":"1.000985"}]
            calls=[]
            original = hp.backfill_index_range
            try:
                def fake_range(start_date, end_date, defs):
                    calls.append((start_date,end_date,tuple(d["name"] for d in defs)))
                    rows=[]
                    for d in ["2026-08-10","2026-08-11","2026-08-12","2026-08-13","2026-08-14"]:
                        for item in defs:
                            rows.append({"date":d,"name":item["name"],"code":item["secid"],"close":1,"return":0.01,"amount_100m":2,"source":"range","status":"ok"})
                    return rows
                hp.backfill_index_range = fake_range
                result = hp.preflight_history(root, "2026-08-14", definitions, repair_indices=True)
            finally:
                hp.backfill_index_range = original
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0:2], ("2026-08-10","2026-08-14"))
            self.assertEqual(result["after"]["indices"], [])

    def test_bulk_failure_caps_sparse_fallback_to_five_latest_dates(self):
        import market_monitor.history_preflight as hp
        with TemporaryDirectory() as td:
            root = Path(td)
            dates = [f"2026-07-{day:02d}" for day in range(20, 32)] + [f"2026-08-{day:02d}" for day in range(1, 15)]
            self._write_csv(root / "data/history/market_core.csv", ["date","total_amount_100m"], [{"date":d,"total_amount_100m":1} for d in dates])
            definitions=[{"name":"上证50","secid":"1.000016"},{"name":"Choice微盘","secid":"47.800007"},{"name":"中证全指","secid":"1.000985"}]
            sparse_dates=[]
            old_range, old_date = hp.backfill_index_range, hp.backfill_index_date
            try:
                hp.backfill_index_range = lambda *args, **kwargs: []
                def fake_date(d, defs):
                    sparse_dates.append(d)
                    return []
                hp.backfill_index_date = fake_date
                hp.preflight_history(root, "2026-08-14", definitions, repair_indices=True)
            finally:
                hp.backfill_index_range, hp.backfill_index_date = old_range, old_date
            self.assertLessEqual(len(set(sparse_dates)), 5)
            self.assertIn("2026-08-14", sparse_dates)
            self.assertIn("2026-08-13", sparse_dates)


if __name__ == "__main__":
    unittest.main()
