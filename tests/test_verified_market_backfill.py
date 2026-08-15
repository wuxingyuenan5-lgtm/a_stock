from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class VerifiedMarketBackfillTest(unittest.TestCase):
    def _csv(self, path: Path, fieldnames: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_preflight_treats_verified_backfill_as_market_denominator(self):
        from market_monitor.history_preflight import scan_history_gaps
        with TemporaryDirectory() as td:
            root = Path(td)
            self._csv(root / "data/history/market_core.csv", ["date","total_amount_100m"], [
                {"date":"2026-08-14","total_amount_100m":21415.4},
            ])
            self._csv(root / "data/history/market_core_verified_backfill.csv", ["date","total_amount_100m","source"], [
                {"date":"2026-08-13","total_amount_100m":25484.53569867,"source":"verified workbook"},
            ])
            self._csv(root / "data/history/innovation_drug_eastmoney.csv", ["日期","成交额","换手率"], [
                {"日期":"2026-08-13","成交额":129316966098,"换手率":0.047},
                {"日期":"2026-08-14","成交额":103727030799,"换手率":0.0438},
            ])
            gaps = scan_history_gaps(root, "2026-08-14", required_index_dates=[])
            self.assertNotIn("2026-08-13", gaps["market_denominator_dates"])

    def test_report_data_merges_verified_market_row_and_recovers_innovation_share(self):
        from build_report_data import build_report_data
        with TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output/2026-08-14"
            out.mkdir(parents=True)
            payload = {
                "date":"2026-08-14",
                "market":{"date":"2026-08-14","advance":2306,"decline":2871,"flat":154,"limit_up":62,"limit_down":13,"effective_stocks":5331,"total_amount_100m":21415.4,"hot_count":0,"hot_amount_100m":0,"hot_concentration":0,"market_breadth":-0.1091},
                "indices":{},"hot_stocks":[],"sw_crowding":{},"innovation_drug":{}
            }
            (out / "daily_payload.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            (out / "validation.json").write_text(json.dumps({"status":"PASS","checks":[]}), encoding="utf-8")
            self._csv(root / "data/history/market_core.csv", ["date","advance","decline","flat","limit_up","limit_down","effective_stocks","total_amount_100m","hot_count","hot_amount_100m","hot_concentration","market_breadth"], [
                {"date":"2026-08-14","advance":2306,"decline":2871,"flat":154,"limit_up":62,"limit_down":13,"effective_stocks":5331,"total_amount_100m":21415.4,"hot_count":0,"hot_amount_100m":0,"hot_concentration":0,"market_breadth":-0.1091},
            ])
            self._csv(root / "data/history/market_core_verified_backfill.csv", ["date","advance","decline","flat","limit_up","limit_down","effective_stocks","total_amount_100m","hot_count","hot_amount_100m","hot_concentration","market_breadth","source"], [
                {"date":"2026-08-13","advance":1087,"decline":4166,"flat":77,"limit_up":59,"limit_down":4,"effective_stocks":5330,"total_amount_100m":25484.53569867,"hot_count":23,"hot_amount_100m":3365.68102697,"hot_concentration":0.1320675827,"market_breadth":-0.5861412526,"source":"verified workbook"},
            ])
            self._csv(root / "data/history/innovation_drug_eastmoney.csv", ["日期","成交额","换手率","日收益率","成交量","数据源"], [
                {"日期":"2026-08-13","成交额":129316966098,"换手率":0.047,"日收益率":0.0187,"成交量":70817912,"数据源":"eastmoney"},
                {"日期":"2026-08-14","成交额":103727030799,"换手率":0.0438,"日收益率":-0.0054,"成交量":65909757,"数据源":"eastmoney"},
            ])
            for path, fields in [
                (root / "data/history/indices_history.csv", ["date","name","code","close","return","amount_100m","source","status"]),
                (root / "data/history/hot_stocks.csv", ["date","rank","stock_code","stock_name","close","return","amount_100m","sw_level1","sw_level2"]),
                (root / "data/sw_industry_latest.csv", ["日期","行业层级","指数代码","指数名称"]),
                (root / "data/history/sw_analysis_daily_second.csv", ["指数代码","发布日期","换手率","成交额占比"]),
            ]:
                self._csv(path, fields, [])
            report = build_report_data("2026-08-14", root)
            market = {r["date"]: r for r in report["market_history"]}
            innovation = {r["date"]: r for r in report["innovation_history"]}
            self.assertEqual(market["2026-08-13"]["total_amount_100m"], 25484.53569867)
            self.assertAlmostEqual(innovation["2026-08-13"]["amount_share_of_a"], 1293.16966098 / 25484.53569867, places=10)
            self.assertNotIn("2026-08-13", report["quality"]["history_gaps"]["market_denominator_dates"])


if __name__ == "__main__":
    unittest.main()
