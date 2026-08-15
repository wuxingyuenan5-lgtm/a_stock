from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class IndexHistoryWindowTest(unittest.TestCase):
    def _csv(self, path: Path, fields: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_default_preflight_checks_latest_five_market_dates_only(self):
        from market_monitor.history_preflight import scan_history_gaps
        with TemporaryDirectory() as td:
            root = Path(td)
            dates = [f"2026-08-{day:02d}" for day in range(1, 11)]
            self._csv(root / "data/history/market_core.csv", ["date","total_amount_100m"], [
                {"date": d, "total_amount_100m": 1} for d in dates
            ])
            self._csv(root / "data/history/indices_history.csv", ["date","name","code","close","return","amount_100m","source","status"], [])
            gaps = scan_history_gaps(root, "2026-08-10")
            self.assertEqual(sorted({item["date"] for item in gaps["indices"]}), dates[-5:])

    def test_historical_close_is_optional_when_return_and_amount_are_verified(self):
        from market_monitor.history_preflight import scan_history_gaps
        with TemporaryDirectory() as td:
            root = Path(td)
            self._csv(root / "data/history/market_core.csv", ["date","total_amount_100m"], [{"date":"2026-08-14","total_amount_100m":1}])
            rows = []
            for name, code in (("上证50","1.000016"),("Choice微盘","47.800007"),("中证全指","1.000985")):
                rows.append({"date":"2026-08-14","name":name,"code":code,"close":"","return":0.01,"amount_100m":2,"source":"verified","status":"ok"})
            self._csv(root / "data/history/indices_history.csv", ["date","name","code","close","return","amount_100m","source","status"], rows)
            gaps = scan_history_gaps(root, "2026-08-14")
            self.assertEqual(gaps["indices"], [])


if __name__ == "__main__":
    unittest.main()
