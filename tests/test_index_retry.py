import unittest
from unittest.mock import patch

from market_monitor import production


class IndexRetryTest(unittest.TestCase):
    def test_standard_interface_avoids_legacy_direct_call(self):
        definitions = [{"name": "上证50", "secid": "1.000016"}]
        primary = {
            "date": "2026-08-14", "name": "上证50", "code": "1.000016",
            "close": 3000.0, "return": 0.01, "amount_100m": 1000.0,
            "source": "standard", "status": "ok_primary_standard_index",
        }
        with patch.object(production, "_index_record_from_hist", return_value=primary):
            with patch.object(production, "fetch_indices_direct") as direct:
                result = production.fetch_indices_resilient("2026-08-14", definitions)
        self.assertEqual(result[0]["status"], "ok_primary_standard_index")
        direct.assert_not_called()

    def test_bulk_spot_is_second_supported_path(self):
        definitions = [{"name": "Choice微盘", "secid": "47.800007"}]
        spot = {
            "date": "2026-08-14", "name": "Choice微盘", "code": "47.800007",
            "close": 1200.0, "return": -0.01, "amount_100m": 200.0,
            "source": "bulk", "status": "ok_bulk_spot_fallback",
        }
        with patch.object(production, "_index_record_from_hist", side_effect=RuntimeError("no hist")):
            with patch.object(production, "_index_record_from_spot", return_value=spot):
                with patch.object(production, "fetch_indices_direct") as direct:
                    result = production.fetch_indices_resilient("2026-08-14", definitions)
        self.assertEqual(result[0]["status"], "ok_bulk_spot_fallback")
        direct.assert_not_called()

    def test_legacy_second_pass_only_for_supported_path_failures(self):
        definitions = [
            {"name": "A", "secid": "1"},
            {"name": "B", "secid": "2"},
        ]
        first = [
            {"name": "A", "close": None, "return": None, "amount_100m": None, "status": "error"},
            {"name": "B", "close": None, "return": None, "amount_100m": None, "status": "error"},
        ]
        second = [
            {"name": "A", "close": 1.0, "return": 0.01, "amount_100m": 10.0, "status": "ok"},
            {"name": "B", "close": 2.0, "return": 0.02, "amount_100m": 20.0, "status": "ok"},
        ]
        with patch.object(production, "_index_record_from_hist", side_effect=RuntimeError("primary fail")):
            with patch.object(production, "_index_record_from_spot", side_effect=RuntimeError("spot fail")):
                with patch.object(production, "fetch_indices_direct", side_effect=[first, second]) as fetch:
                    with patch.object(production.time, "sleep"):
                        result = production.fetch_indices_resilient("2026-08-14", definitions)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result[0]["status"], "ok_legacy_direct_after_second_pass")
        self.assertEqual(result[1]["status"], "ok_legacy_direct_after_second_pass")


if __name__ == "__main__":
    unittest.main()
