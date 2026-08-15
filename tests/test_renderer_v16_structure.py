from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RendererV16StructureTest(unittest.TestCase):
    def test_renderer_has_dynamic_dashboard_sections(self):
        text = (ROOT / "run_excel_renderer_v16.py").read_text(encoding="utf-8")
        self.assertIn("DASHBOARD_HOT_DETAIL_START_ROW", text)
        self.assertIn("hot_detail_rows", text)
        self.assertIn("section_05_start", text)
        self.assertIn("section_06_start", text)
        self.assertNotIn('get_range("H17:O23")', text)

    def test_market_charts_reference_helper_ranges(self):
        text = (ROOT / "run_excel_renderer_v16.py").read_text(encoding="utf-8")
        self.assertIn("MARKET_HELPER_START_ROW", text)
        self.assertIn("03_市场宽度图", text)
        self.assertIn("category_formula", text)
        self.assertIn("series.formula", text)
        self.assertIn("tick_label_interval", text)

    def test_style_normalization_and_legacy_cleanup_are_explicit(self):
        text = (ROOT / "run_excel_renderer_v16.py").read_text(encoding="utf-8")
        self.assertIn("normalize_table_styles", text)
        self.assertIn("clear_legacy_ranges", text)
        self.assertIn("05_申万行业资金拥挤度", text)
        self.assertIn("06_创新药交易拥挤度", text)
        self.assertIn("99_口径与质量", text)

    def test_preflight_module_exposes_gap_scan(self):
        text = (ROOT / "market_monitor" / "history_preflight.py").read_text(encoding="utf-8")
        self.assertIn("def scan_history_gaps", text)
        self.assertIn("def backfill_index_gaps", text)
        self.assertIn("def recover_innovation_share", text)
        self.assertIn("unresolved", text)


if __name__ == "__main__":
    unittest.main()
