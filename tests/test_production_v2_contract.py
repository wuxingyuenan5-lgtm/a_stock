from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProductionV2ContractTest(unittest.TestCase):
    def test_web_runtime_is_single_entrypoint(self):
        cfg = json.loads((ROOT / "config" / "web_production_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["entrypoint"]["renderer_version"], "1.5")
        self.assertTrue(cfg["mother_policy"]["never_rebuild_from_scratch"])
        self.assertTrue(cfg["chart_policy"]["forbid_new_charts"])
        self.assertTrue(cfg["efficiency_policy"]["single_artifact_download"])
        self.assertEqual(cfg["innovation_policy"]["activity_proxy"], "retired")
        self.assertTrue(cfg["index_policy"]["avoid_single_endpoint_failure_across_all_three_indices"])

    def test_daily_workflow_uses_fast_sw_refresh(self):
        text = (ROOT / ".github" / "workflows" / "daily_market_monitor.yml").read_text(encoding="utf-8")
        self.assertIn("update_sw_industry_fast.py", text)
        self.assertIn("Full unit tests on code review only", text)
        self.assertIn("config/web_production_runtime.json", text)

    def test_renderer_is_chart_preserving_v15(self):
        entry = (ROOT / "run_excel_renderer.py").read_text(encoding="utf-8")
        cfg = json.loads((ROOT / "config" / "excel_renderer.json").read_text(encoding="utf-8"))
        self.assertIn("run_excel_renderer_v15", entry)
        self.assertEqual(cfg["renderer_version"], "1.5")
        self.assertTrue(cfg["chart_invariants"]["forbid_delete_all_drawings"])
        self.assertTrue(cfg["chart_invariants"]["preserve_anchor_positions"])


if __name__ == "__main__":
    unittest.main()
