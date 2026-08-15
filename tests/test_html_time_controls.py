from __future__ import annotations

import unittest

from render_market_monitor_html import render_html
from tests.test_html_renderer import HtmlRendererContractTest


class HtmlTimeControlsTest(unittest.TestCase):
    def _report(self):
        report = HtmlRendererContractTest()._report()
        report["sw_crowding_history"] = [
            {
                "date":"2026-08-13",
                "targets":{
                    "通信设备":{"amount_share_of_a":0.0895,"turnover":0.0911},
                    "计算机设备":{"amount_share_of_a":0.0202,"turnover":0.0529},
                    "元件":{"amount_share_of_a":0.0703,"turnover":0.1082},
                    "半导体":{"amount_share_of_a":0.1649,"turnover":0.0695},
                },
                "combined":{"amount_share_of_a":0.3449,"amount_100m":8789.6},
            },
            {
                "date":"2026-08-14",
                "targets":{
                    "通信设备":{"amount_share_of_a":0.0800,"turnover":0.0800},
                    "计算机设备":{"amount_share_of_a":0.0210,"turnover":0.0500},
                    "元件":{"amount_share_of_a":0.0680,"turnover":0.1000},
                    "半导体":{"amount_share_of_a":0.1500,"turnover":0.0650},
                },
                "combined":{"amount_share_of_a":0.3190,"amount_100m":6800.0},
            },
        ]
        report["innovation_history"] = [
            {"date":"2026-08-13","amount_share_of_a":0.0507,"turnover":0.0470,"amount_100m":1293.17},
            {"date":"2026-08-14","amount_share_of_a":0.0484,"turnover":0.0438,"amount_100m":1037.27},
        ]
        return report

    def test_every_time_chart_has_dual_range_controls(self):
        html = render_html(self._report())
        charts = html.count('<div class="time-chart" data-time-chart="1"')
        self.assertGreaterEqual(charts, 6)
        self.assertEqual(html.count('class="time-range-start"'), charts)
        self.assertEqual(html.count('class="time-range-end"'), charts)
        self.assertEqual(html.count('class="time-range-all"'), charts)
        self.assertEqual(html.count('class="time-range-label"'), charts)

    def test_time_runtime_defaults_to_full_history_and_redraws_selected_window(self):
        compact = render_html(self._report()).replace(" ", "")
        self.assertIn('functionmountTimeChart', compact)
        self.assertIn('start.value="0"', compact)
        self.assertIn('end.value=String(Math.max(0,dates.length-1))', compact)
        self.assertIn("start.addEventListener('input',redraw)", compact)
        self.assertIn("end.addEventListener('input',redraw)", compact)
        self.assertIn('drawSvg(', compact)
        self.assertIn('constvisibleSeries=', compact)

    def test_time_runtime_is_fully_inlined_offline(self):
        html = render_html(self._report())
        lower = html.lower()
        self.assertNotIn("<script src=", lower)
        self.assertNotIn("https://", lower)
        self.assertNotIn("http://", lower)
        self.assertIn('class="time-chart-config"', html)


if __name__ == "__main__":
    unittest.main()
