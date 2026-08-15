from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from validate_canonical_data import validate_current_canonical


ROOT = Path(__file__).resolve().parents[1]


class CanonicalCliTest(unittest.TestCase):
    def test_runtime_declares_canonical_v2(self):
        cfg = json.loads((ROOT / "config/html_production_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["data_layer"], "canonical_v2")
        self.assertTrue(cfg["raw_direct_render_forbidden"])
        self.assertEqual(cfg["canonical_validator"], "validate_canonical_data.py")
        self.assertIn("canonical_manifest.json", cfg["artifact"]["required_companions"])
        self.assertIn("canonical_validation.json", cfg["artifact"]["required_companions"])

    def test_audit_only_cli_uses_current_canonical_as_candidate(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            path = root / "data/history/market_core.csv"
            path.parent.mkdir(parents=True)
            fields = ["date","advance","decline","flat","effective_stocks","total_amount_100m","hot_amount_100m","market_breadth"]
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "date":"2026-08-14","advance":2306,"decline":2871,"flat":154,
                    "effective_stocks":5331,"total_amount_100m":21415.4,"hot_amount_100m":1796.1,
                    "market_breadth":(2306-2871)/(2306+2871),
                })
            result = validate_current_canonical(root, "2026-08-14")
            self.assertIn(result["status"], ("PASS", "WARN"))
            self.assertEqual(result["failures"], [])
            self.assertEqual(result["target_date"], "2026-08-14")


if __name__ == "__main__":
    unittest.main()
