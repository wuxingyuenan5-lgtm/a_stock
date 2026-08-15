from __future__ import annotations

import unittest

from render_market_monitor_html import render_html


class HtmlLayoutContractTest(unittest.TestCase):
    def _report(self):
        return {
            "meta":{"report_name":"A股每日市场监控","report_date":"2026-08-14","status":"WARN"},
            "market_history":[{"date":"2026-08-14","advance":2306,"decline":2871,"flat":154,"limit_up":62,"limit_down":13,"total_amount_100m":21415.4,"hot_count":0,"market_breadth":-0.1091}],
            "indices_history":[],"sw_industry_latest":[],
            "hot_stock_matrix":{"dates":["2026-08-14"],"rows":[]},"hot_stocks_latest":[],
            "sw_crowding_history":[],"innovation_history":[],
            "quality":{"status":"WARN","unresolved":[],"module_latest_dates":{"market":"2026-08-14","indices":"2026-08-14","sw_industry":"2026-08-14","sw_crowding":"2026-08-13","innovation":"2026-08-14"},"history_gaps":{"indices":[],"market_denominator_dates":[]},"payload_checks":[]},
        }

    def test_shenwan_table_is_scrollable_without_dropping_rows(self):
        html = render_html(self._report())
        self.assertIn('.sw-table{max-height:900px', html)

    def test_two_column_charts_do_not_force_720px_minimum_width(self):
        html = render_html(self._report())
        self.assertIn('.chart-grid-two .chart-svg{min-width:0', html)

    def test_quality_module_labels_are_chinese(self):
        html = render_html(self._report())
        for label in ("市场核心", "三项指数", "申万行业", "四行业拥挤度", "创新药"):
            self.assertIn(label, html)

    def test_business_module_numbering_matches_the_cleaned_monitor_contract(self):
        html = render_html(self._report())
        self.assertIn("00｜市场总览 · 市场涨跌结构", html)
        self.assertIn("00｜市场总览 · 市场宽度", html)
        self.assertIn("00｜市场总览 · 最近交易日指数与成交", html)
        self.assertIn("01｜申万行业", html)
        self.assertIn("04｜百亿成交", html)
        self.assertIn("05｜申万四行业资金拥挤度", html)
        self.assertIn("06｜创新药交易拥挤度", html)
        self.assertIn("99｜数据质量", html)
        self.assertNotIn("07｜创新药交易拥挤度", html)


if __name__ == "__main__":
    unittest.main()
