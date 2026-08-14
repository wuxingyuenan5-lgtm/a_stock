from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RendererContractTest(unittest.TestCase):
    def test_entrypoint_uses_v15(self):
        text = (ROOT / "run_excel_renderer.py").read_text(encoding="utf-8")
        self.assertIn("run_excel_renderer_v15", text)
        self.assertNotIn("run_excel_renderer_v12_safe", text)
        self.assertNotIn("run_excel_renderer_v13", text)

    def test_v15_preserves_existing_chart_objects_and_turnover_history(self):
        text = (ROOT / "run_excel_renderer_v15.py").read_text(encoding="utf-8")
        self.assertNotIn("delete_all_drawings", text)
        self.assertNotIn("charts.add", text)
        self.assertIn("update_07_rolling", text)
        self.assertIn("fallback source may fill", text)
        self.assertIn("20日成交量活跃度代理已停用", text)
        self.assertIn('s1.name = "创新药换手率"', text)

    def test_v14_base_still_preserves_existing_chart_objects(self):
        text = (ROOT / "run_excel_renderer_v14.py").read_text(encoding="utf-8")
        self.assertNotIn("delete_all_drawings", text)
        self.assertIn("chart_structure", text)
        self.assertIn("chart_structure_changed", text)
        self.assertIn("update_01", text)
        self.assertIn("update_06", text)

    def test_config_is_single_version_and_rolling_mother(self):
        cfg = json.loads((ROOT / "config" / "excel_renderer.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["renderer_version"], "1.5")
        self.assertEqual(cfg["mother_policy"]["mode"], "rolling_previous_validated")
        self.assertEqual(cfg["mother_policy"]["registry"], "data/latest_validated_workbook.json")
        self.assertEqual(cfg["chart_invariants"]["mode"], "existing_excel_native_charts_update_only")
        self.assertTrue(cfg["chart_invariants"]["forbid_delete_all_drawings"])
        innovation = cfg["sheet_contracts"]["07_创新药交易拥挤度"]
        self.assertEqual(innovation["activity_proxy"], "retired")
        self.assertEqual(innovation["turnover_rule"], "supplier_direct_board_turnover_only")
        self.assertTrue(innovation["preserve_verified_historical_non_null"])

    def test_bundle_is_self_contained_for_web(self):
        text = (ROOT / "prepare_render_bundle.py").read_text(encoding="utf-8")
        self.assertIn("sw_industry_latest.csv", text)
        self.assertIn("renderer_runtime/run_excel_renderer_v15.py", text)
        self.assertIn("renderer_runtime/run_excel_renderer_v14.py", text)
        self.assertIn("latest_validated_workbook.json", text)
        self.assertNotIn('"volume_activity_20d", "return"', text)


if __name__ == "__main__":
    unittest.main()
