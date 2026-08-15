from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from market_monitor.canonical_store import TableSpec, audit_table, diff_history


class CanonicalStoreTest(unittest.TestCase):
    def _write(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_audit_reports_duplicate_keys_and_latest_date(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "market.csv"
            self._write(path, [
                {"date": "2026-08-13", "advance": "1"},
                {"date": "2026-08-13", "advance": "2"},
                {"date": "2026-08-14", "advance": "3"},
            ])
            spec = TableSpec("market", "data/history/market_core.csv", ("date",), "date")
            audit = audit_table(path, spec)
            self.assertEqual(audit["row_count"], 3)
            self.assertEqual(audit["latest_date"], "2026-08-14")
            self.assertEqual(audit["duplicate_key_count"], 1)
            self.assertEqual(len(audit["sha256"]), 64)

    def test_diff_history_flags_only_pre_target_changes(self):
        spec = TableSpec("market", "x.csv", ("date",), "date")
        before = [
            {"date": "2026-08-13", "advance": "100"},
            {"date": "2026-08-14", "advance": "200"},
        ]
        after = [
            {"date": "2026-08-13", "advance": "101"},
            {"date": "2026-08-14", "advance": "201"},
        ]
        diff = diff_history(before, after, spec, "2026-08-14")
        self.assertEqual(diff["modified_historical_dates"], ["2026-08-13"])
        self.assertEqual(diff["target_date_changed_keys"], 1)
        self.assertEqual(diff["deleted_keys"], 0)
        self.assertEqual(diff["added_keys"], 0)


if __name__ == "__main__":
    unittest.main()
