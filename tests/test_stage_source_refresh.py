from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class StageSourceRefreshTest(unittest.TestCase):
    def test_stage_refresh_routes_crowding_and_industry_outputs_under_stage(self):
        import run_daily

        with TemporaryDirectory() as td:
            stage = Path(td) / "stage"
            stage.mkdir(parents=True)
            calls = {}

            def fake_crowding(target_date, cache_path, history_path):
                calls["crowding"] = (target_date, Path(cache_path), Path(history_path))
                return []

            def fake_fast(target_date, data_dir):
                calls["fast"] = (target_date, Path(data_dir))
                return {"target_date": target_date}

            result = run_daily.refresh_stage_sources(
                stage_root=stage,
                target_date="2026-08-14",
                full_refresh_sw_industry=False,
                crowding_refresh_fn=fake_crowding,
                fast_industry_refresh_fn=fake_fast,
            )

            self.assertEqual(calls["crowding"][1], stage / "data/cache/sw_analysis_daily_second.csv")
            self.assertEqual(calls["crowding"][2], stage / "data/history/sw_analysis_daily_second.csv")
            self.assertEqual(calls["fast"][1], stage / "data")
            self.assertEqual(result["sw_crowding"], "ok")
            self.assertEqual(result["sw_industry"], "ok_fast")

    def test_production_run_reads_shenwan_cache_from_supplied_root(self):
        import market_monitor.production as production

        with TemporaryDirectory() as td:
            root = Path(td)
            cache = root / "data/cache/sw_analysis_daily_second.csv"
            cache.parent.mkdir(parents=True)
            with cache.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["发布日期", "指数代码", "换手率"])
                writer.writeheader()
                writer.writerow({"发布日期":"2026-08-14","指数代码":"801102","换手率":"7.6"})

            original_run = production.pipeline.run
            try:
                def fake_pipeline_run(**kwargs):
                    frame = production.pipeline.fetch_sw_analysis("2026-08-14")
                    self.assertEqual(len(frame), 1)
                    self.assertEqual(str(frame.iloc[0]["指数代码"]), "801102")
                    self.assertEqual(kwargs["root"], root)
                    return {"ok": True}

                production.pipeline.run = fake_pipeline_run
                result = production.run(
                    target_date="2026-08-14",
                    config_path=root / "config/market_monitor.json",
                    root=root,
                )
            finally:
                production.pipeline.run = original_run

            self.assertEqual(result, {"ok": True})


if __name__ == "__main__":
    unittest.main()
