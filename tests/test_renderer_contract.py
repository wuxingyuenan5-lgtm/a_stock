from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RendererContractTest(unittest.TestCase):
    def test_entrypoint_uses_v14(self):
        text = (ROOT / "run_excel_renderer.py").read_text(encoding="utf-8")
        self.assertIn("run_excel_renderer_v14", text)
        self.assertNotIn("run_excel_renderer_v12_safe", text)
        self.assertNotIn("run_excel_renderer_v13", text)

    def test_v14_preserves_existing_chart_objects(self):
        text = (ROOT / "run_excel_renderer_v14.py").read_text(encoding="utf-8")
        self.assertNotIn("delete_all_drawings", text)
        self.assertIn("chart_structure", text)
        self.assertIn("chart_structure_changed", text)
        self.assertIn("update_01", text)
        self.assertIn("update_06", text)

    def test_config_is_single_version_and_rolling_mother(self):
        cfg = json.loads((ROOT / "config" / "excel_renderer.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["renderer_version"], "1.4")
        self.assertEqual(cfg["mother_policy"]["mode"], "rolling_previous_validated")
        self.assertEqual(cfg["chart_invariants"]["mode"], "existing_excel_native_charts_update_only")
        self.assertTrue(cfg["chart_invariants"]["forbid_delete_all_drawings"])
        self.assertIn("01_申万行业", cfg["sheet_contracts"])
        self.assertIn("06_综合拥挤度_辅助", cfg["sheet_contracts"])

    def test_bundle_is_self_contained_for_web(self):
        text = (ROOT / "prepare_render_bundle.py").read_text(encoding="utf-8")
        self.assertIn("sw_industry_latest.csv", text)
        self.assertIn("renderer_runtime/run_excel_renderer_v14.py", text)
        self.assertIn("web_production_manifest.json", text)
        self.assertIn("expected_mother_filename", text)


if __name__ == "__main__":
    unittest.main()
