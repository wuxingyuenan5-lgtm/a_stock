from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RendererContractTest(unittest.TestCase):
    def test_entrypoint_uses_v16(self):
        text = (ROOT / "run_excel_renderer.py").read_text(encoding="utf-8")
        self.assertIn("run_excel_renderer_v16", text)
        self.assertNotIn("run_excel_renderer_v12_safe", text)
        self.assertNotIn("run_excel_renderer_v13", text)

    def test_v16_preserves_existing_chart_objects_and_uses_formula_backed_market_series(self):
        text = (ROOT / "run_excel_renderer_v16.py").read_text(encoding="utf-8")
        compile(text, "run_excel_renderer_v16.py", "exec")
        self.assertNotIn("delete_all_drawings", text)
        self.assertNotIn("charts.add", text)
        self.assertIn("category_formula", text)
        self.assertIn("series.formula", text)
        self.assertIn("rebuild_market_chart_helpers", text)
        self.assertIn("layout_dashboard_dynamic", text)
        self.assertIn("06_创新药交易拥挤度", text)
        self.assertNotIn("20日成交量活跃度代理", text)

    def test_v15_base_still_preserves_verified_innovation_history(self):
        text = (ROOT / "run_excel_renderer_v15.py").read_text(encoding="utf-8")
        compile(text, "run_excel_renderer_v15.py", "exec")
        self.assertNotIn("delete_all_drawings", text)
        self.assertNotIn("charts.add", text)
        self.assertIn("update_07_rolling", text)
        self.assertIn("fallback source may fill", text)
        self.assertIn('s1.name = "创新药换手率"', text)

    def test_config_is_v16_rolling_mother_and_six_sheet_contract(self):
        cfg = json.loads((ROOT / "config" / "excel_renderer.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["renderer_version"], "1.6")
        self.assertEqual(cfg["mother_policy"]["mode"], "rolling_previous_validated")
        self.assertEqual(cfg["mother_policy"]["registry"], "data/latest_validated_workbook.json")
        self.assertEqual(cfg["chart_invariants"]["mode"], "existing_excel_native_charts_update_only")
        self.assertTrue(cfg["chart_invariants"]["forbid_delete_all_drawings"])
        self.assertTrue(cfg["chart_invariants"]["market_series_formula_backed"])
        self.assertNotIn("06_综合拥挤度_辅助", cfg["mother_policy"]["required_sheets"])
        self.assertIn("06_创新药交易拥挤度", cfg["mother_policy"]["required_sheets"])
        self.assertNotIn("07_创新药交易拥挤度", cfg["mother_policy"]["required_sheets"])
        innovation = cfg["sheet_contracts"]["06_创新药交易拥挤度"]
        self.assertEqual(innovation["turnover_rule"], "supplier_direct_board_turnover_only")
        self.assertTrue(innovation["preserve_verified_historical_non_null"])

    def test_bundle_is_self_contained_for_web(self):
        text = (ROOT / "prepare_render_bundle.py").read_text(encoding="utf-8")
        self.assertIn("sw_industry_latest.csv", text)
        self.assertIn("renderer_runtime/run_excel_renderer_v16.py", text)
        self.assertIn("renderer_runtime/run_excel_renderer_v15.py", text)
        self.assertIn("latest_validated_workbook.json", text)
        self.assertNotIn('"volume_activity_20d", "return"', text)


if __name__ == "__main__":
    unittest.main()
