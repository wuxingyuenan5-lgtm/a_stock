from __future__ import annotations

import unittest


class HtmlRendererContractTest(unittest.TestCase):
    def _report(self, hot_count: int = 12):
        hot = [{
            "date":"2026-08-14","rank":i+1,"stock_code":f"{i+1:06d}","stock_name":f"股票{i+1}",
            "close":10+i,"return":0.01 if i%2==0 else -0.01,"amount_100m":100+i,
            "sw_level1":"电子","sw_level2":"半导体",
        } for i in range(hot_count)]
        return {
            "meta":{"report_name":"A股每日市场监控","report_date":"2026-08-14","status":"PASS","latest_market_date":"2026-08-14"},
            "market_history":[
                {"date":"2026-08-13","advance":1087,"decline":4166,"flat":77,"limit_up":59,"limit_down":4,"total_amount_100m":25484.5,"hot_count":23,"market_breadth":-0.5861},
                {"date":"2026-08-14","advance":2306,"decline":2871,"flat":154,"limit_up":62,"limit_down":13,"total_amount_100m":21415.4,"hot_count":hot_count,"market_breadth":-0.1091},
            ],
            "indices_history":[
                {"date":"2026-08-14","name":"上证50","return":-0.0041,"amount_100m":1523.72,"close":2916.13},
                {"date":"2026-08-14","name":"Choice微盘","return":0.0034,"amount_100m":160.96,"close":1823.92},
                {"date":"2026-08-14","name":"中证全指","return":0.003,"amount_100m":20797.77,"close":5991.02},
            ],
            "sw_industry_latest":[],
            "hot_stock_matrix":{"dates":["2026-08-13","2026-08-14"],"rows":[{"industry":"半导体","counts":[5,hot_count],"history_total":5+hot_count}]},
            "hot_stocks_latest":hot,
            "sw_crowding_history":[],
            "innovation_history":[{"date":"2026-08-14","amount_100m":1037.27,"amount_share_of_a":0.0484,"turnover":0.0438,"return":-0.0054,"volume":65909757}],
            "quality":{"status":"PASS","unresolved":[],"module_latest_dates":{"market":"2026-08-14","indices":"2026-08-14","sw_industry":"2026-08-14","sw_crowding":"2026-08-13","innovation":"2026-08-14"},"history_gaps":{"indices":[],"market_denominator_dates":[]},"payload_checks":[]},
        }

    def test_render_is_single_file_without_external_dependencies(self):
        from render_market_monitor_html import render_html
        html = render_html(self._report())
        lower = html.lower()
        self.assertNotIn("http://", lower)
        self.assertNotIn("https://", lower)
        self.assertNotIn("<script src=", lower)
        self.assertNotIn("<link href=", lower)
        self.assertIn("<svg", lower)

    def test_hot_stock_table_is_not_capped_at_seven_rows(self):
        from render_market_monitor_html import render_html
        for count in (12, 23, 30):
            html = render_html(self._report(count))
            self.assertIn(f"股票{count}", html)
            self.assertEqual(html.count('data-hot-row="1"'), count)

    def test_market_structure_chart_contains_latest_four_series_values(self):
        from render_market_monitor_html import render_html
        html = render_html(self._report())
        self.assertIn('data-chart-date="2026-08-14"', html)
        self.assertIn('data-advance="2306"', html)
        self.assertIn('data-decline="2871"', html)
        self.assertIn('data-limit-up="62"', html)
        self.assertIn('data-limit-down="13"', html)


if __name__ == "__main__":
    unittest.main()
