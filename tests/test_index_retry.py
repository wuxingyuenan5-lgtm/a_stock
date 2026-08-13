import unittest
from unittest.mock import patch

from market_monitor import production


class IndexRetryTest(unittest.TestCase):
    def test_second_pass_only_retries_failed_indices(self):
        definitions = [
            {"name": "A", "secid": "1"},
            {"name": "B", "secid": "2"},
        ]
        first = [
            {"name": "A", "close": 1.0, "return": 0.01, "amount_100m": 10.0, "status": "ok"},
            {"name": "B", "close": None, "return": None, "amount_100m": None, "status": "error"},
        ]
        second = [
            {"name": "B", "close": 2.0, "return": 0.02, "amount_100m": 20.0, "status": "ok"},
        ]
        with patch.object(production, "fetch_indices_primary", side_effect=[first, second]) as fetch:
            with patch.object(production.time, "sleep"):
                result = production.fetch_indices_with_second_pass("2026-08-13", definitions)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[1].args[1], [definitions[1]])
        self.assertEqual(result[0]["name"], "A")
        self.assertEqual(result[1]["name"], "B")
        self.assertEqual(result[1]["status"], "ok_after_same_source_second_pass")


if __name__ == "__main__":
    unittest.main()
