from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProductionV2ContractTest(unittest.TestCase):
    def test_web_runtime_is_single_entrypoint(self):
        cfg = json.loads((ROOT / "config" / "web_production_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["entrypoint"]["renderer_version"], "1.6")
        self.assertTrue(cfg["mother_policy"]["never_rebuild_from_scratch"])
        self.assertTrue(cfg["chart_policy"]["forbid_new_charts"])
        self.assertTrue(cfg["chart_policy"]["market_series_formula_backed"])
        self.assertTrue(cfg["efficiency_policy"]["single_artifact_download"])
        self.assertEqual(cfg["innovation_policy"]["activity_proxy"], "retired")
        self.assertTrue(cfg["index_policy"]["avoid_single_endpoint_failure_across_all_three_indices"])
        self.assertTrue(cfg["history_preflight"]["enabled"])
        self.assertEqual(cfg["history_preflight"]["mode"], "scan_then_targeted_backfill")

    def test_daily_workflow_runs_preflight_before_current_payload(self):
        text = (ROOT / ".github" / "workflows" / "daily_market_monitor.yml").read_text(encoding="utf-8")
        self.assertIn("history_preflight.py", text)
        self.assertLess(text.index("history_preflight.py"), text.index("run_daily.py"))
        self.assertIn("update_sw_industry_fast.py", text)
        self.assertIn("Full unit tests on code review only", text)
        self.assertIn("config/web_production_runtime.json", text)

    def test_historical_target_uses_historical_index_path(self):
        text = (ROOT / "market_monitor" / "production.py").read_text(encoding="utf-8")
        self.assertIn("is_current_china_trading_date", text)
        self.assertIn("fetch_indices_legacy", text)
        self.assertIn("historical target", text.lower())

    def test_renderer_is_chart_preserving_v16(self):
        entry = (ROOT / "run_excel_renderer.py").read_text(encoding="utf-8")
        cfg = json.loads((ROOT / "config" / "excel_renderer.json").read_text(encoding="utf-8"))
        self.assertIn("run_excel_renderer_v16", entry)
        self.assertEqual(cfg["renderer_version"], "1.6")
        self.assertTrue(cfg["chart_invariants"]["forbid_delete_all_drawings"])
        self.assertTrue(cfg["chart_invariants"]["preserve_anchor_positions"])
        self.assertTrue(cfg["chart_invariants"]["market_series_formula_backed"])


if __name__ == "__main__":
    unittest.main()
