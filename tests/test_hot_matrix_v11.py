from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_report_data import build_hot_stock_matrix, build_report_data
from tests.test_report_data import ReportDataContractTest


class HotMatrixV11Test(unittest.TestCase):
    def test_hot_matrix_defaults_to_ten_dates_newest_first(self):
        rows = []
        for day in range(1, 13):
            rows.append({
                "date": f"2026-08-{day:02d}",
                "stock_code": f"{day:06d}",
                "sw_level2": "半导体",
            })
        matrix = build_hot_stock_matrix(rows)
        self.assertEqual(len(matrix["dates"]), 10)
        self.assertEqual(matrix["dates"][0], "2026-08-12")
        self.assertEqual(matrix["dates"][-1], "2026-08-03")
        self.assertEqual(matrix["rows"][0]["counts"], [1] * 10)

    def test_report_exposes_full_canonical_hot_history_separately_from_matrix(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            fixture = ReportDataContractTest(methodName="test_build_report_data_has_single_required_contract")
            fixture._fixture(root)
            report = build_report_data("2026-08-14", root)
            self.assertIn("hot_stocks_history", report)
            self.assertEqual(report["hot_stocks_history"], report["hot_stocks_latest"])
            self.assertIsNot(report["hot_stocks_history"], report["hot_stock_matrix"])


if __name__ == "__main__":
    unittest.main()
