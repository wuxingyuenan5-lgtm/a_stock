from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RendererContractTest(unittest.TestCase):
    def test_entrypoint_uses_stable_native_renderer(self):
        text = (ROOT / "run_excel_renderer.py").read_text(encoding="utf-8")
        self.assertIn("run_excel_renderer_v12_safe", text)
        self.assertNotIn("run_excel_renderer_v13", text)

    def test_market_structure_keeps_zero_baseline(self):
        text = (ROOT / "run_excel_renderer_v12_safe.py").read_text(encoding="utf-8")
        self.assertIn('is_market_structure', text)
        self.assertIn('chart.y_axis.min = -limit', text)
        self.assertIn('chart.y_axis.max = limit', text)
        self.assertIn('if not is_market_structure:', text)

    def test_external_output_removes_engineering_labels(self):
        text = (ROOT / "run_excel_renderer_v12_safe.py").read_text(encoding="utf-8")
        self.assertIn('"关键走势图总览"', text)
        self.assertIn('"创新药独立主题"', text)
        self.assertIn('"多源数据校验"', text)
        self.assertNotIn('"关键走势图总览｜Renderer', text)
        self.assertNotIn('"关键走势图总览｜Excel原生图表', text)


if __name__ == "__main__":
    unittest.main()
