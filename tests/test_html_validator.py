from __future__ import annotations

import unittest

from render_market_monitor_html import render_html


class HtmlValidatorContractTest(unittest.TestCase):
    def _report(self):
        return {
            "meta":{"report_name":"A股每日市场监控","report_date":"2026-08-14","latest_market_date":"2026-08-14","status":"WARN"},
            "market_history":[
                {"date":"2026-08-13","advance":1087,"decline":4166,"flat":77,"limit_up":59,"limit_down":4,"total_amount_100m":25484.5,"hot_count":23,"market_breadth":-0.5861},
                {"date":"2026-08-14","advance":2306,"decline":2871,"flat":154,"limit_up":62,"limit_down":13,"total_amount_100m":21415.4,"hot_count":2,"market_breadth":-0.1091},
            ],
            "indices_history":[],
            "sw_industry_latest":[],
            "hot_stock_matrix":{"dates":["2026-08-14","2026-08-13"],"rows":[{"industry":"半导体","counts":[2,23],"history_total":25}]},
            "hot_stocks_latest":[
                {"date":"2026-08-14","rank":1,"stock_code":"000001","stock_name":"A","close":10,"return":0.01,"amount_100m":130,"sw_level1":"电子","sw_level2":"半导体"},
                {"date":"2026-08-14","rank":2,"stock_code":"000002","stock_name":"B","close":20,"return":-0.01,"amount_100m":120,"sw_level1":"电子","sw_level2":"半导体"},
            ],
            "sw_crowding_history":[],
            "innovation_history":[
                {"date":"2026-08-13","amount_100m":1293.17,"amount_share_of_a":1293.17/25484.5,"turnover":0.047,"return":0.0187,"volume":70817912},
                {"date":"2026-08-14","amount_100m":1037.27,"amount_share_of_a":1037.27/21415.4,"turnover":0.0438,"return":-0.0054,"volume":65909757},
            ],
            "quality":{"status":"WARN","unresolved":[],"module_latest_dates":{},"history_gaps":{"indices":[],"market_denominator_dates":[]},"payload_checks":[]},
        }

    def test_valid_report_passes_structural_validation(self):
        from validate_market_monitor_html import validate_report
        report=self._report(); result=validate_report(report, render_html(report))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failures"], [])

    def test_stale_report_date_fails(self):
        from validate_market_monitor_html import validate_report
        report=self._report(); report["meta"]["report_date"]="2026-08-13"
        result=validate_report(report, render_html(report))
        self.assertIn("report_date_not_latest_market", result["failures"])

    def test_hot_count_and_matrix_mismatch_fail(self):
        from validate_market_monitor_html import validate_report
        report=self._report(); report["market_history"][-1]["hot_count"]=3
        result=validate_report(report, render_html(report))
        self.assertIn("hot_detail_count_mismatch", result["failures"])
        self.assertIn("hot_matrix_count_mismatch", result["failures"])

    def test_recoverable_innovation_share_blank_fails(self):
        from validate_market_monitor_html import validate_report
        report=self._report(); report["innovation_history"][-1]["amount_share_of_a"]=None
        result=validate_report(report, render_html(report))
        self.assertIn("recoverable_innovation_share_blank:2026-08-14", result["failures"])

    def test_external_dependency_and_missing_latest_chart_marker_fail(self):
        from validate_market_monitor_html import validate_report
        report=self._report(); html=render_html(report).replace("</body>", '<script src="https://example.com/x.js"></script></body>').replace('data-chart-date="2026-08-14"','data-chart-date="2026-08-13"')
        result=validate_report(report, html)
        self.assertIn("external_dependency", result["failures"])
        self.assertIn("market_chart_latest_date_missing", result["failures"])

    def test_innovation_activity_proxy_is_forbidden(self):
        from validate_market_monitor_html import validate_report
        report=self._report(); report["innovation_history"][-1]["volume_activity_20d"]=1.2
        result=validate_report(report, render_html(report))
        self.assertIn("innovation_activity_proxy_present", result["failures"])


if __name__ == "__main__":
    unittest.main()
