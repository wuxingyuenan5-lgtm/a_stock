import unittest

import pandas as pd

from market_monitor.pipeline import _combine_sw_targets, _normalize_sw_targets


class ShenwanNormalizationTests(unittest.TestCase):
    def test_official_share_and_turnover_are_percent_points(self):
        frame = pd.DataFrame([
            {"指数代码": "801102", "指数名称": "通信设备", "发布日期": "2026-08-07", "换手率": 9.44, "成交额占比": 9.94},
            {"指数代码": "801101", "指数名称": "计算机设备", "发布日期": "2026-08-07", "换手率": 5.31, "成交额占比": 2.50},
            {"指数代码": "801083", "指数名称": "元件", "发布日期": "2026-08-07", "换手率": 13.61, "成交额占比": 3.20},
            {"指数代码": "801081", "指数名称": "半导体", "发布日期": "2026-08-07", "换手率": 8.21, "成交额占比": 7.10},
        ])
        codes = {"通信设备":"801102", "计算机设备":"801101", "元件":"801083", "半导体":"801081"}
        result = _normalize_sw_targets(frame, codes, "2026-08-10", 25000.0)
        self.assertAlmostEqual(result["通信设备"]["turnover"], 0.0944)
        self.assertAlmostEqual(result["通信设备"]["amount_share_of_a"], 0.0994)
        self.assertIsNone(result["通信设备"]["amount_100m"])
        self.assertEqual(result["通信设备"]["date"], "2026-08-07")

    def test_amount_is_derived_only_when_dates_match(self):
        frame = pd.DataFrame([
            {"指数代码": "801102", "指数名称": "通信设备", "发布日期": "2026-08-10", "换手率": 9.44, "成交额占比": 10.0},
        ])
        result = _normalize_sw_targets(frame, {"通信设备":"801102"}, "2026-08-10", 25000.0)
        self.assertAlmostEqual(result["通信设备"]["amount_100m"], 2500.0)

    def test_combined_share_can_exist_without_amount(self):
        targets = {
            "a": {"amount_100m": None, "amount_share_of_a": 0.10},
            "b": {"amount_100m": None, "amount_share_of_a": 0.02},
            "c": {"amount_100m": None, "amount_share_of_a": 0.03},
            "d": {"amount_100m": None, "amount_share_of_a": 0.04},
        }
        combined = _combine_sw_targets(targets)
        self.assertIsNone(combined["amount_100m"])
        self.assertAlmostEqual(combined["amount_share_of_a"], 0.19)


if __name__ == "__main__":
    unittest.main()
