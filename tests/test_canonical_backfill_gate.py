from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from run_history_preflight import execute_preflight_with_gate


class CanonicalBackfillGateTest(unittest.TestCase):
    def _write_market(self, root: Path, effective_stocks: int) -> Path:
        path = root / "data/history/market_core.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "date", "advance", "decline", "flat", "effective_stocks",
            "total_amount_100m", "hot_amount_100m", "market_breadth",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({
                "date": "2026-08-14", "advance": 2306, "decline": 2871, "flat": 154,
                "effective_stocks": effective_stocks, "total_amount_100m": 21415.4,
                "hot_amount_100m": 1796.1,
                "market_breadth": (2306 - 2871) / (2306 + 2871),
            })
        return path

    def test_invalid_staged_history_repair_cannot_modify_live_canonical(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            live = self._write_market(root, 5331)
            before = live.read_bytes()

            def corrupt_repair(stage_root, report_date, definitions, repair_indices=True):
                self._write_market(stage_root, 1)
                return {
                    "before": {"indices": [], "market_denominator_dates": []},
                    "after": {"indices": [], "market_denominator_dates": []},
                }

            with self.assertRaises(RuntimeError):
                execute_preflight_with_gate(
                    root=root,
                    target_date="2026-08-14",
                    definitions=[],
                    repair_indices=True,
                    repair_fn=corrupt_repair,
                )

            self.assertEqual(live.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
