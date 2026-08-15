from __future__ import annotations

import unittest

from render_market_monitor_html import render_html


class HtmlV11InteractionsTest(unittest.TestCase):
    def _report(self):
        dates = ["2026-08-12", "2026-08-13", "2026-08-14"]
        market = [
            {"date": d, "advance": 2000+i*100, "decline": 3000-i*100, "flat": 100, "limit_up": 50+i, "limit_down": 3+i, "effective_stocks": 5100, "total_amount_100m": 20000+i*1000, "hot_count": 2, "hot_amount_100m": 300, "hot_concentration": .015, "market_breadth": -.2+i*.1}
            for i, d in enumerate(dates)
        ]
        indices=[]
        for d in dates:
            for name in ("上证50","Choice微盘","中证全指"):
                indices.append({"date":d,"name":name,"return":.01,"amount_100m":100})
        sw=[
            {"行业层级":"一级行业","一级行业":"电子","指数代码":"801080","指数名称":"电子","收盘价":1,"成交额":300,"日收益率":.03,"20日年化波动率":.2,"日期":"2026-08-14"},
            {"行业层级":"二级行业","一级行业":"电子","指数代码":"801081","指数名称":"半导体","收盘价":1,"成交额":500,"日收益率":.01,"20日年化波动率":.3,"日期":"2026-08-14"},
        ]
        crowd=[]
        for i,d in enumerate(dates):
            targets={}
            for j,n in enumerate(("通信设备","计算机设备","元件","半导体")):
                targets[n]={"amount_100m":100+j,"amount_share_of_a":.02+j*.01+i*.001,"turnover":.04+j*.01+i*.001}
            crowd.append({"date":d,"targets":targets,"combined":{"amount_100m":406,"amount_share_of_a":.14}})
        innovation=[{"date":d,"amount_100m":1000,"amount_share_of_a":.05+i*.001,"turnover":.04+i*.001,"return":.01,"volume":1000} for i,d in enumerate(dates)]
        hot_latest=[{"date":"2026-08-14","rank":1,"stock_code":"000001","stock_name":"A","close":10,"return":.01,"amount_100m":150,"sw_level1":"电子","sw_level2":"半导体"},{"date":"2026-08-14","rank":2,"stock_code":"000002","stock_name":"B","close":20,"return":.02,"amount_100m":150,"sw_level1":"通信","sw_level2":"通信设备"}]
        return {
            "meta":{"report_date":"2026-08-14","status":"PASS"},
            "market_history":market,"indices_history":indices,"sw_industry_latest":sw,
            "hot_stock_matrix":{"dates":["2026-08-14","2026-08-13","2026-08-12"],"rows":[{"industry":"半导体","counts":[1,1,1],"history_total":3},{"industry":"通信设备","counts":[1,1,1],"history_total":3}]},
            "hot_stocks_latest":hot_latest,"sw_crowding_history":crowd,"innovation_history":innovation,
            "quality":{"module_latest_dates":{"market":"2026-08-14","indices":"2026-08-14","sw_industry":"2026-08-14","sw_crowding":"2026-08-14","innovation":"2026-08-14"},"unresolved":[],"canonical_validation":{"status":"PASS"}}
        }

    def test_every_time_chart_has_full_history_range_controls(self):
        html=render_html(self._report())
        count=html.count('data-time-chart="1"')
        self.assertGreaterEqual(count, 6)
        self.assertEqual(html.count('class="time-range-start"'), count)
        self.assertEqual(html.count('class="time-range-end"'), count)
        self.assertEqual(html.count('class="time-range-all"'), count)
        self.assertEqual(html.count('class="time-range-label"'), count)
        self.assertIn('start.value="0"', html)
        self.assertIn('end.value=String(Math.max(0,dates.length-1))', html)

    def test_sw_three_state_sort_contract(self):
        html=render_html(self._report())
        self.assertIn('data-sort-field="amount"', html)
        self.assertIn('data-sort-field="return"', html)
        self.assertIn('data-sort-field="volatility"', html)
        self.assertIn("['original','desc','asc']", html)
        self.assertIn('data-original-index="0"', html)

    def test_crowding_and_innovation_use_area_plus_line_and_no_combined_table(self):
        html=render_html(self._report())
        self.assertIn('data-area-chart="crowding-share"', html)
        self.assertIn('data-line-chart="crowding-turnover"', html)
        self.assertIn('data-area-chart="innovation-share"', html)
        self.assertIn('data-direct-turnover="innovation"', html)
        self.assertNotIn('四行业成交额合计</h3>', html)
        self.assertNotIn('>四行业合计<', html)
        self.assertNotIn('20日成交量活跃度代理', html)

    def test_hot_matrix_latest_date_is_leftmost(self):
        html=render_html(self._report())
        start=html.index('最近10个有记录交易日')
        fragment=html[start:start+3000]
        self.assertLess(fragment.index('08-14'), fragment.index('08-13'))
        self.assertLess(fragment.index('08-13'), fragment.index('08-12'))


if __name__ == '__main__':
    unittest.main()
