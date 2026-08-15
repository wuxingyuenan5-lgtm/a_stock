from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class ReportDataContractTest(unittest.TestCase):
    def _csv(self, path: Path, fieldnames: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _fixture(self, root: Path) -> None:
        out = root / "output/2026-08-14"
        out.mkdir(parents=True)
        payload = {
            "date": "2026-08-14",
            "market": {"date": "2026-08-14", "advance": 2306, "decline": 2871, "flat": 154, "limit_up": 62, "limit_down": 13, "effective_stocks": 5331, "total_amount_100m": 21415.4, "hot_count": 2, "hot_amount_100m": 250.0, "hot_concentration": 0.0117, "market_breadth": -0.1091},
            "indices": {
                "上证50": {"date": "2026-08-14", "name": "上证50", "code": "1.000016", "close": 2916.13, "return": -0.0041, "amount_100m": 1523.72, "source": "x", "status": "ok"},
                "Choice微盘": {"date": "2026-08-14", "name": "Choice微盘", "code": "47.800007", "close": 1823.92, "return": 0.0034, "amount_100m": 160.96, "source": "x", "status": "ok"},
                "中证全指": {"date": "2026-08-14", "name": "中证全指", "code": "1.000985", "close": 5991.02, "return": 0.003, "amount_100m": 20797.77, "source": "x", "status": "ok"},
            },
            "hot_stocks": [
                {"rank": 1, "stock_code": "000001", "stock_name": "A", "close": 10, "return": 0.01, "amount_100m": 140, "sw_level1": "电子", "sw_level2": "半导体"},
                {"rank": 2, "stock_code": "000002", "stock_name": "B", "close": 20, "return": -0.01, "amount_100m": 110, "sw_level1": "通信", "sw_level2": "通信设备"},
            ],
        }
        (out / "daily_payload.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (out / "validation.json").write_text(json.dumps({"date": "2026-08-14", "status": "PASS", "checks": []}, ensure_ascii=False), encoding="utf-8")
        (out / "canonical_validation.json").write_text(json.dumps({"target_date":"2026-08-14","status":"PASS","failures":[],"warnings":[],"tables":{}}, ensure_ascii=False), encoding="utf-8")

        self._csv(root / "data/history/market_core.csv", ["date","advance","decline","flat","limit_up","limit_down","effective_stocks","total_amount_100m","hot_count","hot_amount_100m","hot_concentration","market_breadth"], [
            {"date":"2026-08-13","advance":1087,"decline":4166,"flat":77,"limit_up":59,"limit_down":4,"effective_stocks":5330,"total_amount_100m":25484.5,"hot_count":23,"hot_amount_100m":3365.68,"hot_concentration":0.132,"market_breadth":-0.5861},
            {"date":"2026-08-14","advance":2306,"decline":2871,"flat":154,"limit_up":62,"limit_down":13,"effective_stocks":5331,"total_amount_100m":21415.4,"hot_count":2,"hot_amount_100m":250,"hot_concentration":0.0117,"market_breadth":-0.1091},
        ])
        self._csv(root / "data/history/indices_history.csv", ["date","name","code","close","return","amount_100m","source","status"], [
            {"date":"2026-08-13","name":"上证50","code":"1.000016","close":2920,"return":0.001,"amount_100m":1500,"source":"x","status":"ok"},
            {"date":"2026-08-13","name":"Choice微盘","code":"47.800007","close":1817,"return":-0.002,"amount_100m":170,"source":"x","status":"ok"},
            {"date":"2026-08-13","name":"中证全指","code":"1.000985","close":5973,"return":-0.004,"amount_100m":23000,"source":"x","status":"ok"},
            {"date":"2026-08-14","name":"上证50","code":"1.000016","close":2916.13,"return":-0.0041,"amount_100m":1523.72,"source":"x","status":"ok"},
            {"date":"2026-08-14","name":"Choice微盘","code":"47.800007","close":1823.92,"return":0.0034,"amount_100m":160.96,"source":"x","status":"ok"},
            {"date":"2026-08-14","name":"中证全指","code":"1.000985","close":5991.02,"return":0.003,"amount_100m":20797.77,"source":"x","status":"ok"},
        ])
        self._csv(root / "data/history/hot_stocks.csv", ["date","rank","stock_code","stock_name","close","return","amount_100m","sw_level1","sw_level2"], [
            {"date":"2026-08-14","rank":1,"stock_code":"000001","stock_name":"A","close":10,"return":0.01,"amount_100m":140,"sw_level1":"电子","sw_level2":"半导体"},
            {"date":"2026-08-14","rank":2,"stock_code":"000002","stock_name":"B","close":20,"return":-0.01,"amount_100m":110,"sw_level1":"通信","sw_level2":"通信设备"},
        ])
        self._csv(root / "data/sw_industry_latest.csv", ["日期","行业层级","一级行业代码","一级行业","指数代码","指数名称","收盘价","成交额","日收益率","20日年化波动率"], [
            {"日期":"2026-08-14","行业层级":"一级行业","一级行业代码":"801080","一级行业":"电子","指数代码":"801080","指数名称":"电子","收盘价":100,"成交额":1000,"日收益率":0.01,"20日年化波动率":0.2},
        ])
        self._csv(root / "data/history/sw_analysis_daily_second.csv", ["指数代码","指数名称","发布日期","换手率","成交额占比"], [
            {"指数代码":"801102","指数名称":"通信设备","发布日期":"2026-08-13","换手率":9.11,"成交额占比":8.95},
            {"指数代码":"801101","指数名称":"计算机设备","发布日期":"2026-08-13","换手率":5.29,"成交额占比":2.02},
            {"指数代码":"801083","指数名称":"元件","发布日期":"2026-08-13","换手率":10.82,"成交额占比":7.03},
            {"指数代码":"801081","指数名称":"半导体","发布日期":"2026-08-13","换手率":6.95,"成交额占比":16.49},
        ])
        self._csv(root / "data/history/innovation_drug_eastmoney.csv", ["日期","成交额","日收益率","换手率","成交量","数据源"], [
            {"日期":"2026-08-13","成交额":129316966098,"日收益率":0.0187,"换手率":0.047,"成交量":70817912,"数据源":"eastmoney"},
            {"日期":"2026-08-14","成交额":103727030799,"日收益率":-0.0054,"换手率":0.0438,"成交量":65909757,"数据源":"eastmoney"},
        ])
        (root / "config").mkdir(exist_ok=True)
        (root / "config/market_monitor.json").write_text(json.dumps({"sw_crowding_codes":{"通信设备":"801102","计算机设备":"801101","元件":"801083","半导体":"801081"}}, ensure_ascii=False), encoding="utf-8")

    def test_build_report_data_has_single_required_contract(self):
        from build_report_data import build_report_data
        with TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root)
            report = build_report_data("2026-08-14", root)
            self.assertEqual(report["meta"]["report_date"], "2026-08-14")
            self.assertEqual(set(report), {
                "meta", "market_history", "indices_history", "sw_industry_latest",
                "hot_stock_matrix", "hot_stocks_history", "hot_stocks_latest", "sw_crowding_history",
                "innovation_history", "quality",
            })
            self.assertEqual(len(report["hot_stocks_latest"]), 2)
            self.assertEqual(len(report["hot_stocks_history"]), 2)
            self.assertEqual(report["hot_stock_matrix"]["dates"][0], "2026-08-14")

    def test_innovation_contract_has_no_activity_proxy_and_share_uses_same_day_denominator(self):
        from build_report_data import build_report_data
        with TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root)
            report = build_report_data("2026-08-14", root)
            latest = report["innovation_history"][-1]
            self.assertNotIn("volume_activity_20d", latest)
            self.assertNotIn("activity", latest)
            self.assertAlmostEqual(latest["amount_share_of_a"], 1037.27030799 / 21415.4, places=8)
            self.assertEqual(latest["turnover"], 0.0438)

    def test_report_data_business_values_do_not_require_raw_daily_payload(self):
        from build_report_data import build_report_data
        with TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root)
            (root / "output/2026-08-14/daily_payload.json").unlink()
            (root / "output/2026-08-14/validation.json").unlink()
            report = build_report_data("2026-08-14", root)
            self.assertEqual(report["market_history"][-1]["hot_count"], 2)
            self.assertEqual(len(report["hot_stocks_latest"]), 2)
            self.assertEqual(report["meta"]["canonical_validation_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
