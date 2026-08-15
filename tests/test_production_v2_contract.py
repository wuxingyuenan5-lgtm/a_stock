from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProductionV2ContractTest(unittest.TestCase):
    def test_legacy_excel_runtime_remains_available_but_separate(self):
        cfg = json.loads((ROOT / "config" / "web_production_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["entrypoint"]["renderer_version"], "1.5")
        self.assertTrue(cfg["mother_policy"]["never_rebuild_from_scratch"])
        self.assertTrue(cfg["chart_policy"]["forbid_new_charts"])
        self.assertEqual(cfg["innovation_policy"]["activity_proxy"], "retired")

    def test_html_runtime_is_primary_single_entrypoint(self):
        cfg = json.loads((ROOT / "config" / "html_production_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["runtime_version"], "1.0")
        self.assertEqual(cfg["primary_format"], "html")
        self.assertTrue(cfg["offline_single_file"])
        self.assertFalse(cfg["requires_excel_mother"])
        self.assertEqual(cfg["data_contract"], "report_data.json")
        self.assertEqual(cfg["innovation_turnover_rule"], "supplier_direct_only")
        self.assertEqual(cfg["activity_proxy"], "retired")

    def test_daily_workflow_runs_canonical_html_pipeline_in_required_order(self):
        text = (ROOT / ".github" / "workflows" / "daily_market_monitor.yml").read_text(encoding="utf-8")
        for required in (
            "Full unit tests on code review only",
            "run_history_preflight.py",
            "run_daily.py",
            "validate_canonical_data.py",
            "build_report_data.py",
            "render_market_monitor_html.py",
            "validate_market_monitor_html.py",
            "config/html_production_runtime.json",
        ):
            self.assertIn(required, text)

        names = [
            "History preflight and recoverable backfill",
            "Produce normalized payload",
            "Validate Canonical data",
            "Build normalized report data",
            "Render offline HTML",
            "Validate HTML",
        ]
        positions = [text.index(f"- name: {name}") for name in names]
        self.assertEqual(positions, sorted(positions))

        self.assertNotIn("- name: Refresh Shenwan crowding cache once", text)
        self.assertNotIn("- name: Refresh Shenwan industry snapshot", text)
        self.assertIn("--full-refresh-sw-industry", text)

    def test_excel_renderer_remains_chart_preserving_v15(self):
        entry = (ROOT / "run_excel_renderer.py").read_text(encoding="utf-8")
        cfg = json.loads((ROOT / "config" / "excel_renderer.json").read_text(encoding="utf-8"))
        self.assertIn("run_excel_renderer_v15", entry)
        self.assertEqual(cfg["renderer_version"], "1.5")
        self.assertTrue(cfg["chart_invariants"]["forbid_delete_all_drawings"])
        self.assertTrue(cfg["chart_invariants"]["preserve_anchor_positions"])


if __name__ == "__main__":
    unittest.main()
