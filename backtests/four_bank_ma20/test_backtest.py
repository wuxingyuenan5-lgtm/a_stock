from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import unittest

import pandas as pd

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from backtest import (  # noqa: E402
    BANK_CODES,
    BacktestConfig,
    allocate_equal_weight,
    build_signal_table,
    next_execution_date,
    stamp_duty_rate,
)


class SignalTests(unittest.TestCase):
    def test_mean_reversion_crosses_are_not_lookahead(self) -> None:
        dates = pd.date_range("2024-01-01", periods=8, freq="D")
        close = pd.Series([10.0, 10.0, 10.0, 9.0, 8.0, 10.0, 11.0, 10.0], index=dates)
        signals = build_signal_table(close, ma_window=3, signal_mode="mean_reversion")

        # 2024-01-04 closes below its MA after the prior close was at/above MA.
        self.assertEqual(signals.loc[pd.Timestamp("2024-01-04"), "signal"], "entry")
        # The rebound is only actionable after that day's close, not on an earlier row.
        self.assertEqual(signals.loc[pd.Timestamp("2024-01-06"), "signal"], "exit")
        self.assertEqual(signals.loc[pd.Timestamp("2024-01-05"), "signal"], "")

    def test_trend_following_reverses_signal_direction(self) -> None:
        dates = pd.date_range("2024-01-01", periods=8, freq="D")
        close = pd.Series([10.0, 10.0, 10.0, 9.0, 8.0, 10.0, 11.0, 10.0], index=dates)
        signals = build_signal_table(close, ma_window=3, signal_mode="trend_following")
        self.assertEqual(signals.loc[pd.Timestamp("2024-01-04"), "signal"], "exit")
        self.assertEqual(signals.loc[pd.Timestamp("2024-01-06"), "signal"], "entry")


class ExecutionTests(unittest.TestCase):
    def test_next_execution_date_is_strictly_after_signal(self) -> None:
        execution_dates = pd.DatetimeIndex(
            [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-05")]
        )
        self.assertEqual(
            next_execution_date(pd.Timestamp("2024-01-03"), execution_dates),
            pd.Timestamp("2024-01-05"),
        )
        self.assertIsNone(
            next_execution_date(pd.Timestamp("2024-01-05"), execution_dates)
        )

    def test_equal_weight_allocation_respects_board_lots_and_cash(self) -> None:
        config = BacktestConfig(
            initial_capital=1_000_000,
            commission_rate=0.0003,
            minimum_commission=5.0,
            board_lot=100,
        )
        prices = pd.Series(
            {
                BANK_CODES[0]: 4.0,
                BANK_CODES[1]: 5.0,
                BANK_CODES[2]: 6.0,
                BANK_CODES[3]: 7.0,
            }
        )
        quantities, execution_prices, fees = allocate_equal_weight(
            config.initial_capital,
            prices,
            config,
        )
        total_required = sum(
            quantities[code] * execution_prices[code] + fees[code]
            for code in BANK_CODES
        )
        self.assertLessEqual(total_required, config.initial_capital)
        for quantity in quantities.values():
            self.assertGreater(quantity, 0)
            self.assertEqual(quantity % config.board_lot, 0)


class CostTests(unittest.TestCase):
    def test_historical_stamp_duty_schedule(self) -> None:
        config = BacktestConfig(stamp_duty_mode="historical")
        self.assertEqual(stamp_duty_rate(pd.Timestamp(date(2023, 8, 27)), config), 0.001)
        self.assertEqual(stamp_duty_rate(pd.Timestamp(date(2023, 8, 28)), config), 0.0005)

    def test_fixed_and_none_stamp_duty_modes(self) -> None:
        fixed = BacktestConfig(
            stamp_duty_mode="fixed",
            fixed_stamp_duty_rate=0.0008,
        )
        none = BacktestConfig(stamp_duty_mode="none")
        trade_date = pd.Timestamp("2020-01-01")
        self.assertEqual(stamp_duty_rate(trade_date, fixed), 0.0008)
        self.assertEqual(stamp_duty_rate(trade_date, none), 0.0)


if __name__ == "__main__":
    unittest.main()
