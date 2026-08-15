from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from market_monitor.canonical_validation import validate_candidate


class CanonicalValidationTest(unittest.TestCase):
    def _write(self, root: Path, rel: str, fields: list[str], rows: list[dict]) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_bad_market_math_fails(self):
        with TemporaryDirectory() as old_td, TemporaryDirectory() as candidate_td:
            old_root, candidate_root = Path(old_td), Path(candidate_td)
            fields = [
                "date", "advance", "decline", "flat", "effective_stocks",
                "total_amount_100m", "hot_count", "hot_amount_100m", "market_breadth",
            ]
            bad = {
                "date": "2026-08-14",
                "advance": 2306,
                "decline": 2871,
                "flat": 154,
                "effective_stocks": 5330,
                "total_amount_100m": 21415,
                "hot_count": 12,
                "hot_amount_100m": 1796,
                "market_breadth": 0.9,
            }
            self._write(old_root, "data/history/market_core.csv", fields, [bad])
            self._write(candidate_root, "data/history/market_core.csv", fields, [bad])

            result = validate_candidate(candidate_root, old_root, "2026-08-14")

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("market_effective_stock_mismatch:2026-08-14", result["failures"])
            self.assertIn("market_breadth_mismatch:2026-08-14", result["failures"])

    def test_large_history_deletion_fails(self):
        with TemporaryDirectory() as old_td, TemporaryDirectory() as candidate_td:
            old_root, candidate_root = Path(old_td), Path(candidate_td)
            fields = ["date", "advance"]
            old_rows = [
                {"date": f"2026-01-{day:02d}", "advance": 1}
                for day in range(1, 11)
            ]
            self._write(old_root, "data/history/market_core.csv", fields, old_rows)
            self._write(candidate_root, "data/history/market_core.csv", fields, old_rows[-1:])

            result = validate_candidate(candidate_root, old_root, "2026-08-14")

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(item.startswith("mass_history_deletion:market_core") for item in result["failures"])
            )

    def test_suspicious_turnover_jump_is_warning_not_failure(self):
        with TemporaryDirectory() as old_td, TemporaryDirectory() as candidate_td:
            old_root, candidate_root = Path(old_td), Path(candidate_td)
            fields = [
                "date", "advance", "decline", "flat", "effective_stocks",
                "total_amount_100m", "hot_amount_100m", "market_breadth",
            ]
            rows = [
                {"date": "2026-08-13", "advance": 2500, "decline": 2500, "flat": 100, "effective_stocks": 5100,
                 "total_amount_100m": 20000, "hot_amount_100m": 1000, "market_breadth": 0},
                {"date": "2026-08-14", "advance": 2500, "decline": 2500, "flat": 100, "effective_stocks": 5100,
                 "total_amount_100m": 6000, "hot_amount_100m": 800, "market_breadth": 0},
            ]
            self._write(old_root, "data/history/market_core.csv", fields, rows)
            self._write(candidate_root, "data/history/market_core.csv", fields, rows)

            result = validate_candidate(candidate_root, old_root, "2026-08-14")

            self.assertEqual(result["status"], "WARN")
            self.assertEqual(result["failures"], [])
            self.assertIn("market_turnover_jump:2026-08-13->2026-08-14:0.3000", result["warnings"])


if __name__ == "__main__":
    unittest.main()
