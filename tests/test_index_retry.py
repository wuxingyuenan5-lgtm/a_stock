import unittest
from unittest.mock import patch

from market_monitor import production


class IndexRetryTest(unittest.TestCase):
    def test_current_quote_avoids_legacy_fallback(self):
        definitions = [{"name": "上证50", "secid": "1.000016"}]
        primary = {
            "date": "2026-08-14", "name": "上证50", "code": "1.000016",
            "close": 3000.0, "return": 0.01, "amount_100m": 1000.0,
            "source": "quote", "status": "ok_current_quote_hard_timeout",
        }

        with patch.object(production, "_index_current_quote", return_value=primary):
            with patch.object(production, "fetch_indices_legacy") as legacy:
                result = production.fetch_indices_resilient("2026-08-14", definitions)
        self.assertEqual(result[0]["status"], "ok_current_quote_hard_timeout")
        legacy.assert_not_called()

    def test_only_failed_current_quotes_enter_legacy_fallback(self):
        definitions = [
            {"name": "A", "secid": "1"},
            {"name": "B", "secid": "2"},
        ]
        primary_a = {
            "date": "2026-08-14", "name": "A", "code": "1",
            "close": 1.0, "return": 0.01, "amount_100m": 10.0,
            "source": "quote", "status": "ok_current_quote_hard_timeout",
        }
        fallback_b = {
            "date": "2026-08-14", "name": "B", "code": "2",
            "close": 2.0, "return": 0.02, "amount_100m": 20.0,
            "source": "legacy", "status": "ok",
        }

        def quote(_date, definition):
            if definition["name"] == "A":
                return primary_a
            raise RuntimeError("quote unavailable")

        with patch.object(production, "_index_current_quote", side_effect=quote):
            with patch.object(production, "fetch_indices_legacy", return_value=[fallback_b]) as legacy:
                result = production.fetch_indices_resilient("2026-08-14", definitions)
        self.assertEqual(legacy.call_count, 1)
        self.assertEqual(legacy.call_args.args[1], [definitions[1]])
        self.assertEqual(result[0]["name"], "A")
        self.assertEqual(result[1]["name"], "B")

    def test_innovation_quote_uses_direct_turnover_field(self):
        payload = {"data": {"f48": 128777000000.0, "f168": 470.0, "f170": -27.0}}
        with patch.object(production, "_request_json", return_value=payload):
            result = production.fetch_innovation_current_reliable("2026-08-14")
        self.assertAlmostEqual(result["amount_100m"], 1287.77)
        self.assertAlmostEqual(result["turnover"], 0.047)
        self.assertAlmostEqual(result["return"], -0.0027)
        self.assertIn("供应商直接换手率", result["source"])


if __name__ == "__main__":
    unittest.main()
