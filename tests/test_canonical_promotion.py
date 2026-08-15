from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from market_monitor.canonical_promotion import prepare_stage, promote_candidate


class CanonicalPromotionTest(unittest.TestCase):
    def _write_market(self, root: Path, amount: int) -> Path:
        path = root / "data/history/market_core.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "total_amount_100m"])
            writer.writeheader()
            writer.writerow({"date": "2026-08-14", "total_amount_100m": amount})
        return path

    def test_fail_never_changes_canonical_file(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            canonical = self._write_market(root, 21415)
            before = canonical.read_bytes()
            stage = prepare_stage(root, "2026-08-14")
            self._write_market(stage, 1)

            with self.assertRaises(RuntimeError):
                promote_candidate(
                    stage,
                    root,
                    "2026-08-14",
                    {"status": "FAIL", "failures": ["bad"], "warnings": [], "tables": {}},
                )

            self.assertEqual(canonical.read_bytes(), before)

    def test_pass_promotes_candidate_and_writes_manifest(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._write_market(root, 21415)
            stage = prepare_stage(root, "2026-08-14")
            candidate = self._write_market(stage, 22000)
            candidate_bytes = candidate.read_bytes()

            manifest = promote_candidate(
                stage,
                root,
                "2026-08-14",
                {"status": "PASS", "failures": [], "warnings": [], "tables": {}},
            )

            self.assertEqual((root / "data/history/market_core.csv").read_bytes(), candidate_bytes)
            saved = json.loads(
                (root / "output/2026-08-14/canonical_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["target_date"], "2026-08-14")
            self.assertEqual(saved["validation_status"], "PASS")
            self.assertEqual(manifest["tables"]["market_core"]["before"]["row_count"], 1)
            self.assertEqual(manifest["tables"]["market_core"]["after"]["row_count"], 1)
            self.assertNotEqual(
                manifest["tables"]["market_core"]["before"]["sha256"],
                manifest["tables"]["market_core"]["after"]["sha256"],
            )

    def test_missing_candidate_file_does_not_delete_existing_canonical(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            canonical = self._write_market(root, 21415)
            before = canonical.read_bytes()
            stage = prepare_stage(root, "2026-08-14")
            (stage / "data/history/market_core.csv").unlink()

            promote_candidate(
                stage,
                root,
                "2026-08-14",
                {"status": "PASS", "failures": [], "warnings": [], "tables": {}},
            )

            self.assertEqual(canonical.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
