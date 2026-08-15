from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from render_market_monitor_html import render_html
from tests.test_html_v11_interactions import HtmlV11InteractionsTest
from validate_market_monitor_html import validate_report


ROOT = Path(__file__).resolve().parents[1]


class HtmlV11ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.report = HtmlV11InteractionsTest()._report()
        self.html = render_html(self.report)

    def test_valid_v11_report_has_no_structural_failures(self):
        result = validate_report(self.report, self.html)
        self.assertEqual(result["failures"], [])

    def test_missing_time_slider_fails(self):
        broken = self.html.replace('class="time-range-start"', 'class="missing-range-start"', 1)
        result = validate_report(self.report, broken)
        self.assertIn("time_slider_contract_missing", result["failures"])

    def test_hot_matrix_must_be_newest_first_and_max_ten_dates(self):
        broken = copy.deepcopy(self.report)
        broken["hot_stock_matrix"]["dates"] = ["2026-08-13", "2026-08-14"]
        result = validate_report(broken, self.html)
        self.assertIn("hot_matrix_not_newest_first", result["failures"])

        broken = copy.deepcopy(self.report)
        broken["hot_stock_matrix"]["dates"] = [f"2026-07-{day:02d}" for day in range(1, 12)][::-1]
        result = validate_report(broken, self.html)
        self.assertIn("hot_matrix_more_than_ten_dates", result["failures"])

    def test_three_shenwan_sort_controls_are_required(self):
        broken = self.html.replace('data-sort-field="amount"', 'data-sort-field="missing"', 1)
        result = validate_report(self.report, broken)
        self.assertIn("sw_sort_control_missing:amount", result["failures"])

    def test_area_line_markers_and_combined_amount_ban_are_required(self):
        broken = self.html.replace('data-area-chart="crowding-share"', 'data-area-chart="missing"', 1)
        result = validate_report(self.report, broken)
        self.assertIn("crowding_share_area_chart_missing", result["failures"])

        broken = self.html.replace('data-area-chart="innovation-share"', 'data-area-chart="missing"', 1)
        result = validate_report(self.report, broken)
        self.assertIn("innovation_share_area_chart_missing", result["failures"])

        result = validate_report(self.report, self.html + "四行业成交额合计")
        self.assertIn("combined_amount_presentation_present", result["failures"])

    def test_runtime_declares_html_v11_interaction_contract(self):
        cfg = json.loads((ROOT / "config/html_production_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["html_version"], "1.1")
        self.assertEqual(cfg["time_slider_default"], "full_history")
        self.assertEqual(cfg["hot_matrix_default_dates"], 10)
        self.assertEqual(cfg["hot_matrix_order"], "newest_left")
        self.assertEqual(cfg["sw_sort_cycle"], ["original", "desc", "asc", "original"])
        self.assertEqual(cfg["share_chart_kind"], "area")
        self.assertEqual(cfg["turnover_chart_kind"], "line")


if __name__ == "__main__":
    unittest.main()
