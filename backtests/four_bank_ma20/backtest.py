#!/usr/bin/env python3
"""Event-driven backtest for a four-bank equal-weight MA20 strategy.

Default strategy
----------------
1. Calculate the 20-session simple moving average of the Shanghai Composite.
2. When the index close crosses below MA20, buy the four bank stocks at the
   next common tradable session's open, equally weighted and rounded to 100-share
   board lots.
3. When the index close crosses above MA20, sell all holdings at the next common
   tradable session's open.
4. Use unadjusted execution/valuation prices and apply corporate actions
   explicitly on the ex-date before that day's opening execution.

The engine is intentionally configuration-driven. Signal direction, initial
capital, commission, slippage, dividend tax and stamp duty can all be changed
from the command line without modifying source code.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "four_bank_ma20"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "four_bank_ma20"

INDEX_CODE = "sh.000001"
BANK_CODES = ["sh.601988", "sh.601398", "sh.601939", "sh.601288"]
BANK_NAMES = {
    "sh.601988": "中国银行",
    "sh.601398": "工商银行",
    "sh.601939": "建设银行",
    "sh.601288": "农业银行",
}


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    ma_window: int = 20
    signal_mode: str = "mean_reversion"
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    slippage_bps: float = 0.0
    board_lot: int = 100
    dividend_tax_rate: float = 0.0
    stamp_duty_mode: str = "historical"
    fixed_stamp_duty_rate: float = 0.0005
    annual_risk_free_rate: float = 0.0
    trading_days_per_year: int = 252

    def validate(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.ma_window < 2:
            raise ValueError("ma_window must be at least 2")
        if self.signal_mode not in {"mean_reversion", "trend_following"}:
            raise ValueError("signal_mode must be mean_reversion or trend_following")
        if self.commission_rate < 0 or self.minimum_commission < 0:
            raise ValueError("commission parameters cannot be negative")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")
        if self.board_lot <= 0:
            raise ValueError("board_lot must be positive")
        if not 0 <= self.dividend_tax_rate < 1:
            raise ValueError("dividend_tax_rate must be in [0, 1)")
        if self.stamp_duty_mode not in {"historical", "fixed", "none"}:
            raise ValueError("stamp_duty_mode must be historical, fixed or none")
        if self.fixed_stamp_duty_rate < 0:
            raise ValueError("fixed_stamp_duty_rate cannot be negative")


@dataclass
class PendingOrder:
    side: str
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp
    reason: str


@dataclass
class OpenTrade:
    entry_signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    starting_equity: float
    entry_notional: float
    entry_costs: float
    entry_prices: dict[str, float]
    entry_shares: dict[str, float]
    cash_dividends: float = 0.0
    bonus_shares: float = 0.0


@dataclass
class PortfolioState:
    cash: float
    shares: dict[str, float]
    pending: PendingOrder | None = None
    open_trade: OpenTrade | None = None

    @property
    def invested(self) -> bool:
        return any(quantity > 0 for quantity in self.shares.values())


def read_price_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    open_path = data_dir / "open_prices_wide.csv"
    close_path = data_dir / "close_prices_wide.csv"
    if not open_path.exists() or not close_path.exists():
        raise FileNotFoundError(
            "Price files are missing. Run download_data.py before the backtest."
        )

    open_prices = pd.read_csv(open_path, encoding="utf-8-sig", parse_dates=["date"])
    close_prices = pd.read_csv(close_path, encoding="utf-8-sig", parse_dates=["date"])
    open_prices = open_prices.set_index("date").sort_index()
    close_prices = close_prices.set_index("date").sort_index()

    required = [INDEX_CODE, *BANK_CODES]
    for label, frame in (("open", open_prices), ("close", close_prices)):
        missing = set(required) - set(frame.columns)
        if missing:
            raise ValueError(f"{label} prices missing columns: {sorted(missing)}")
        frame[required] = frame[required].apply(pd.to_numeric, errors="coerce")
        if frame.index.duplicated().any():
            raise ValueError(f"{label} prices contain duplicate dates")

    common_dates = open_prices.index.intersection(close_prices.index)
    open_prices = open_prices.loc[common_dates, required]
    close_prices = close_prices.loc[common_dates, required]
    if open_prices.empty:
        raise ValueError("No overlapping open and close price dates")
    return open_prices, close_prices


def read_corporate_actions(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "corporate_actions.csv"
    if not path.exists():
        raise FileNotFoundError("corporate_actions.csv is missing")

    actions = pd.read_csv(path, encoding="utf-8-sig")
    required = {
        "code",
        "ex_date",
        "cash_before_tax_per_share",
        "stock_dividend_per_share",
        "capitalisation_issue_per_share",
    }
    missing = required - set(actions.columns)
    if missing:
        raise ValueError(f"Corporate actions missing columns: {sorted(missing)}")

    actions["ex_date"] = pd.to_datetime(actions["ex_date"], errors="coerce")
    numeric_columns = [
        "cash_before_tax_per_share",
        "stock_dividend_per_share",
        "capitalisation_issue_per_share",
    ]
    for column in numeric_columns:
        actions[column] = pd.to_numeric(actions[column], errors="coerce").fillna(0.0)

    actions = actions[
        actions["code"].isin(BANK_CODES) & actions["ex_date"].notna()
    ].copy()
    actions.sort_values(["ex_date", "code"], inplace=True)
    return actions.reset_index(drop=True)


def build_signal_table(
    index_close: pd.Series,
    ma_window: int,
    signal_mode: str,
) -> pd.DataFrame:
    close = pd.to_numeric(index_close, errors="coerce").sort_index()
    moving_average = close.rolling(ma_window, min_periods=ma_window).mean()
    previous_close = close.shift(1)
    previous_ma = moving_average.shift(1)
    valid_pair = moving_average.notna() & previous_ma.notna()

    cross_below = valid_pair & (previous_close >= previous_ma) & (close < moving_average)
    cross_above = valid_pair & (previous_close <= previous_ma) & (close > moving_average)

    if signal_mode == "mean_reversion":
        entry = cross_below
        exit_ = cross_above
    elif signal_mode == "trend_following":
        entry = cross_above
        exit_ = cross_below
    else:
        raise ValueError(f"Unsupported signal mode: {signal_mode}")

    signal = pd.Series("", index=close.index, dtype="object")
    signal.loc[entry] = "entry"
    signal.loc[exit_] = "exit"
    return pd.DataFrame(
        {
            "index_close": close,
            "ma": moving_average,
            "cross_below": cross_below,
            "cross_above": cross_above,
            "signal": signal,
        }
    )


def common_execution_dates(open_prices: pd.DataFrame) -> pd.DatetimeIndex:
    valid = open_prices[BANK_CODES].notna().all(axis=1)
    valid &= (open_prices[BANK_CODES] > 0).all(axis=1)
    return pd.DatetimeIndex(open_prices.index[valid]).sort_values()


def next_execution_date(
    signal_date: pd.Timestamp,
    execution_dates: pd.DatetimeIndex,
) -> pd.Timestamp | None:
    position = execution_dates.searchsorted(signal_date, side="right")
    if position >= len(execution_dates):
        return None
    return pd.Timestamp(execution_dates[position])


def commission(notional: float, config: BacktestConfig) -> float:
    if notional <= 0:
        return 0.0
    return max(notional * config.commission_rate, config.minimum_commission)


def stamp_duty_rate(trade_date: pd.Timestamp, config: BacktestConfig) -> float:
    if config.stamp_duty_mode == "none":
        return 0.0
    if config.stamp_duty_mode == "fixed":
        return config.fixed_stamp_duty_rate
    # A-share stamp duty on stock sales was halved from 0.1% to 0.05%
    # from 2023-08-28. The backtest starts in 2011.
    return 0.001 if trade_date.date() < date(2023, 8, 28) else 0.0005


def effective_price(raw_price: float, side: str, slippage_bps: float) -> float:
    multiplier = 1.0 + slippage_bps / 10_000.0
    if side == "buy":
        return raw_price * multiplier
    if side == "sell":
        return raw_price / multiplier
    raise ValueError(f"Unsupported side: {side}")


def allocate_equal_weight(
    cash: float,
    raw_open_prices: pd.Series,
    config: BacktestConfig,
) -> tuple[dict[str, int], dict[str, float], dict[str, float]]:
    if cash <= 0:
        raise ValueError("Cannot allocate a non-positive cash balance")

    execution_prices = {
        code: effective_price(float(raw_open_prices[code]), "buy", config.slippage_bps)
        for code in BANK_CODES
    }
    target_cash = cash / len(BANK_CODES)
    quantities: dict[str, int] = {}
    for code in BANK_CODES:
        lot_value = execution_prices[code] * config.board_lot
        lots = math.floor(target_cash / lot_value)
        quantities[code] = lots * config.board_lot

    def required_cash() -> tuple[float, dict[str, float]]:
        order_costs: dict[str, float] = {}
        total = 0.0
        for code, quantity in quantities.items():
            notional = quantity * execution_prices[code]
            fee = commission(notional, config)
            order_costs[code] = fee
            total += notional + fee
        return total, order_costs

    total_required, fees = required_cash()
    while total_required > cash + 1e-8:
        reducible = [code for code, quantity in quantities.items() if quantity >= config.board_lot]
        if not reducible:
            break
        code_to_reduce = max(
            reducible,
            key=lambda code: quantities[code] * execution_prices[code],
        )
        quantities[code_to_reduce] -= config.board_lot
        total_required, fees = required_cash()

    if any(quantity <= 0 for quantity in quantities.values()):
        raise ValueError(
            "Initial capital is insufficient to buy at least one board lot of every stock"
        )
    if total_required > cash + 1e-8:
        raise ValueError("Unable to construct an affordable equal-weight portfolio")
    return quantities, execution_prices, fees


def group_actions_by_date(actions: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    return {
        pd.Timestamp(ex_date): group.copy()
        for ex_date, group in actions.groupby("ex_date", sort=True)
    }


def apply_corporate_actions(
    trade_date: pd.Timestamp,
    state: PortfolioState,
    actions_by_date: dict[pd.Timestamp, pd.DataFrame],
    config: BacktestConfig,
    action_records: list[dict[str, Any]],
) -> None:
    daily_actions = actions_by_date.get(pd.Timestamp(trade_date))
    if daily_actions is None or not state.invested:
        return

    for row in daily_actions.itertuples(index=False):
        code = str(row.code)
        quantity_before = float(state.shares.get(code, 0.0))
        if quantity_before <= 0:
            continue

        cash_per_share = float(row.cash_before_tax_per_share or 0.0)
        stock_ratio = float(row.stock_dividend_per_share or 0.0)
        capitalisation_ratio = float(row.capitalisation_issue_per_share or 0.0)
        bonus_ratio = stock_ratio + capitalisation_ratio

        cash_credit = quantity_before * cash_per_share * (1.0 - config.dividend_tax_rate)
        bonus_shares = quantity_before * bonus_ratio
        state.cash += cash_credit
        state.shares[code] = quantity_before + bonus_shares

        if state.open_trade is not None:
            state.open_trade.cash_dividends += cash_credit
            state.open_trade.bonus_shares += bonus_shares

        action_records.append(
            {
                "date": trade_date,
                "code": code,
                "name": BANK_NAMES[code],
                "shares_before": quantity_before,
                "cash_per_share_before_tax": cash_per_share,
                "dividend_tax_rate": config.dividend_tax_rate,
                "cash_credit": cash_credit,
                "stock_dividend_ratio": stock_ratio,
                "capitalisation_ratio": capitalisation_ratio,
                "bonus_shares": bonus_shares,
                "shares_after": state.shares[code],
            }
        )


def execute_buy(
    execution_date: pd.Timestamp,
    order: PendingOrder,
    state: PortfolioState,
    open_prices: pd.DataFrame,
    config: BacktestConfig,
    fills: list[dict[str, Any]],
) -> None:
    starting_equity = state.cash
    quantities, prices, fees = allocate_equal_weight(
        state.cash,
        open_prices.loc[execution_date, BANK_CODES],
        config,
    )

    total_notional = 0.0
    total_costs = 0.0
    for code in BANK_CODES:
        quantity = quantities[code]
        price = prices[code]
        notional = quantity * price
        fee = fees[code]
        state.cash -= notional + fee
        state.shares[code] = float(quantity)
        total_notional += notional
        total_costs += fee
        fills.append(
            {
                "date": execution_date,
                "signal_date": order.signal_date,
                "side": "buy",
                "code": code,
                "name": BANK_NAMES[code],
                "quantity": quantity,
                "raw_open": float(open_prices.loc[execution_date, code]),
                "execution_price": price,
                "notional": notional,
                "commission": fee,
                "stamp_duty": 0.0,
                "slippage_bps": config.slippage_bps,
                "reason": order.reason,
            }
        )

    if state.cash < -1e-6:
        raise RuntimeError(f"Negative cash after entry: {state.cash}")
    state.open_trade = OpenTrade(
        entry_signal_date=order.signal_date,
        entry_date=execution_date,
        starting_equity=starting_equity,
        entry_notional=total_notional,
        entry_costs=total_costs,
        entry_prices=prices.copy(),
        entry_shares={code: float(quantities[code]) for code in BANK_CODES},
    )
    state.pending = None


def execute_sell(
    execution_date: pd.Timestamp,
    order: PendingOrder,
    state: PortfolioState,
    open_prices: pd.DataFrame,
    config: BacktestConfig,
    fills: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> None:
    if state.open_trade is None:
        raise RuntimeError("Sell execution has no matching open trade")

    total_notional = 0.0
    total_commission = 0.0
    total_stamp_duty = 0.0
    exit_prices: dict[str, float] = {}
    exit_shares: dict[str, float] = {}
    duty_rate = stamp_duty_rate(execution_date, config)

    for code in BANK_CODES:
        quantity = float(state.shares[code])
        raw_open = float(open_prices.loc[execution_date, code])
        price = effective_price(raw_open, "sell", config.slippage_bps)
        notional = quantity * price
        fee = commission(notional, config)
        duty = notional * duty_rate
        state.cash += notional - fee - duty
        total_notional += notional
        total_commission += fee
        total_stamp_duty += duty
        exit_prices[code] = price
        exit_shares[code] = quantity
        state.shares[code] = 0.0

        fills.append(
            {
                "date": execution_date,
                "signal_date": order.signal_date,
                "side": "sell",
                "code": code,
                "name": BANK_NAMES[code],
                "quantity": quantity,
                "raw_open": raw_open,
                "execution_price": price,
                "notional": notional,
                "commission": fee,
                "stamp_duty": duty,
                "slippage_bps": config.slippage_bps,
                "reason": order.reason,
            }
        )

    open_trade = state.open_trade
    ending_equity = state.cash
    pnl = ending_equity - open_trade.starting_equity
    trade_return = pnl / open_trade.starting_equity
    trades.append(
        {
            "entry_signal_date": open_trade.entry_signal_date,
            "entry_date": open_trade.entry_date,
            "exit_signal_date": order.signal_date,
            "exit_date": execution_date,
            "holding_calendar_days": (execution_date - open_trade.entry_date).days,
            "starting_equity": open_trade.starting_equity,
            "ending_equity": ending_equity,
            "entry_notional": open_trade.entry_notional,
            "exit_notional": total_notional,
            "entry_commission": open_trade.entry_costs,
            "exit_commission": total_commission,
            "stamp_duty": total_stamp_duty,
            "cash_dividends": open_trade.cash_dividends,
            "bonus_shares": open_trade.bonus_shares,
            "pnl": pnl,
            "return": trade_return,
            "entry_prices": json.dumps(open_trade.entry_prices, ensure_ascii=False),
            "exit_prices": json.dumps(exit_prices, ensure_ascii=False),
            "entry_shares": json.dumps(open_trade.entry_shares, ensure_ascii=False),
            "exit_shares": json.dumps(exit_shares, ensure_ascii=False),
        }
    )
    state.open_trade = None
    state.pending = None


def mark_to_market(
    state: PortfolioState,
    close_row: pd.Series,
) -> tuple[float, float]:
    position_value = 0.0
    for code in BANK_CODES:
        quantity = float(state.shares[code])
        if quantity <= 0:
            continue
        price = float(close_row[code])
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"Invalid close price for {code}: {price}")
        position_value += quantity * price
    return state.cash + position_value, position_value


def schedule_signal(
    trade_date: pd.Timestamp,
    signal: str,
    state: PortfolioState,
    execution_dates: pd.DatetimeIndex,
    signal_records: list[dict[str, Any]],
) -> None:
    if signal not in {"entry", "exit"}:
        return

    eligible = (
        signal == "entry" and not state.invested and state.pending is None
    ) or (
        signal == "exit" and state.invested and state.pending is None
    )
    execution_date = next_execution_date(trade_date, execution_dates) if eligible else None
    status = "ignored"
    if eligible and execution_date is not None:
        state.pending = PendingOrder(
            side="buy" if signal == "entry" else "sell",
            signal_date=trade_date,
            execution_date=execution_date,
            reason=f"{signal}_signal",
        )
        status = "scheduled"
    elif eligible:
        status = "no_future_execution_date"

    signal_records.append(
        {
            "signal_date": trade_date,
            "signal": signal,
            "portfolio_invested": state.invested,
            "status": status,
            "execution_date": execution_date,
        }
    )


def run_strategy(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    config: BacktestConfig,
) -> dict[str, pd.DataFrame | dict[str, Any]]:
    config.validate()
    signals = build_signal_table(
        close_prices[INDEX_CODE],
        config.ma_window,
        config.signal_mode,
    )
    execution_dates = common_execution_dates(open_prices)
    actions_by_date = group_actions_by_date(corporate_actions)
    state = PortfolioState(
        cash=config.initial_capital,
        shares={code: 0.0 for code in BANK_CODES},
    )

    fills: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    action_records: list[dict[str, Any]] = []
    signal_records: list[dict[str, Any]] = []
    equity_records: list[dict[str, Any]] = []

    for trade_date in close_prices.index:
        trade_date = pd.Timestamp(trade_date)
        apply_corporate_actions(
            trade_date,
            state,
            actions_by_date,
            config,
            action_records,
        )

        if state.pending is not None and state.pending.execution_date == trade_date:
            if state.pending.side == "buy":
                execute_buy(
                    trade_date,
                    state.pending,
                    state,
                    open_prices,
                    config,
                    fills,
                )
            elif state.pending.side == "sell":
                execute_sell(
                    trade_date,
                    state.pending,
                    state,
                    open_prices,
                    config,
                    fills,
                    trades,
                )
            else:
                raise RuntimeError(f"Unknown pending side: {state.pending.side}")

        equity, position_value = mark_to_market(state, close_prices.loc[trade_date])
        equity_records.append(
            {
                "date": trade_date,
                "cash": state.cash,
                "position_value": position_value,
                "equity": equity,
                "invested": state.invested,
                **{f"shares_{code}": state.shares[code] for code in BANK_CODES},
            }
        )

        signal_value = str(signals.loc[trade_date, "signal"])
        schedule_signal(
            trade_date,
            signal_value,
            state,
            execution_dates,
            signal_records,
        )

    equity_curve = pd.DataFrame(equity_records).set_index("date")
    equity_curve["daily_return"] = equity_curve["equity"].pct_change().fillna(0.0)
    equity_curve["running_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown"] = equity_curve["equity"] / equity_curve["running_peak"] - 1.0

    return {
        "equity_curve": equity_curve,
        "fills": pd.DataFrame(fills),
        "trades": pd.DataFrame(trades),
        "corporate_action_ledger": pd.DataFrame(action_records),
        "signal_ledger": pd.DataFrame(signal_records),
        "signals": signals,
        "final_state": {
            "cash": state.cash,
            "shares": state.shares.copy(),
            "invested": state.invested,
            "pending": asdict(state.pending) if state.pending is not None else None,
            "open_trade": asdict(state.open_trade) if state.open_trade is not None else None,
        },
    }


def run_buy_and_hold_benchmark(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    config: BacktestConfig,
) -> pd.Series:
    execution_dates = common_execution_dates(open_prices)
    if execution_dates.empty:
        raise ValueError("No date is available for buy-and-hold benchmark entry")
    entry_date = pd.Timestamp(execution_dates[0])
    state = PortfolioState(
        cash=config.initial_capital,
        shares={code: 0.0 for code in BANK_CODES},
    )
    benchmark_order = PendingOrder(
        side="buy",
        signal_date=entry_date,
        execution_date=entry_date,
        reason="buy_and_hold_benchmark",
    )
    benchmark_fills: list[dict[str, Any]] = []
    execute_buy(
        entry_date,
        benchmark_order,
        state,
        open_prices,
        config,
        benchmark_fills,
    )
    actions_by_date = group_actions_by_date(corporate_actions)
    action_records: list[dict[str, Any]] = []
    records: list[tuple[pd.Timestamp, float]] = []

    for trade_date in close_prices.index:
        trade_date = pd.Timestamp(trade_date)
        if trade_date < entry_date:
            records.append((trade_date, config.initial_capital))
            continue
        if trade_date > entry_date:
            apply_corporate_actions(
                trade_date,
                state,
                actions_by_date,
                config,
                action_records,
            )
        equity, _ = mark_to_market(state, close_prices.loc[trade_date])
        records.append((trade_date, equity))
    return pd.Series(dict(records), name="bank_buy_hold_equity").sort_index()


def max_drawdown_details(equity: pd.Series) -> dict[str, Any]:
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    trough_date = pd.Timestamp(drawdown.idxmin())
    peak_date = pd.Timestamp(equity.loc[:trough_date].idxmax())
    return {
        "max_drawdown": float(drawdown.loc[trough_date]),
        "peak_date": peak_date,
        "trough_date": trough_date,
    }


def performance_metrics(
    equity: pd.Series,
    initial_capital: float,
    config: BacktestConfig,
) -> dict[str, Any]:
    equity = equity.dropna().astype(float)
    if equity.empty:
        raise ValueError("Cannot calculate metrics from an empty equity curve")

    first_date = pd.Timestamp(equity.index[0])
    last_date = pd.Timestamp(equity.index[-1])
    elapsed_years = max((last_date - first_date).days / 365.2425, 1 / 365.2425)
    total_return = equity.iloc[-1] / initial_capital - 1.0
    cagr = (equity.iloc[-1] / initial_capital) ** (1.0 / elapsed_years) - 1.0

    daily_returns = equity.pct_change().dropna()
    annual_volatility = float(daily_returns.std(ddof=1) * math.sqrt(config.trading_days_per_year))
    daily_rf = config.annual_risk_free_rate / config.trading_days_per_year
    excess = daily_returns - daily_rf
    return_std = float(daily_returns.std(ddof=1))
    sharpe = (
        float(excess.mean() / return_std * math.sqrt(config.trading_days_per_year))
        if return_std > 0
        else None
    )
    downside = daily_returns[daily_returns < daily_rf] - daily_rf
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        float(excess.mean() / downside_std * math.sqrt(config.trading_days_per_year))
        if downside_std > 0
        else None
    )
    dd = max_drawdown_details(equity)
    calmar = cagr / abs(dd["max_drawdown"]) if dd["max_drawdown"] < 0 else None

    return {
        "start_date": first_date,
        "end_date": last_date,
        "initial_equity": initial_capital,
        "final_equity": float(equity.iloc[-1]),
        "total_return": float(total_return),
        "cagr": float(cagr),
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": dd["max_drawdown"],
        "max_drawdown_peak_date": dd["peak_date"],
        "max_drawdown_trough_date": dd["trough_date"],
        "calmar_ratio": float(calmar) if calmar is not None else None,
    }


def trade_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "completed_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": None,
            "average_trade_return": None,
            "median_trade_return": None,
            "best_trade_return": None,
            "worst_trade_return": None,
            "average_holding_days": None,
            "profit_factor": None,
            "total_realized_pnl": 0.0,
            "total_cash_dividends": 0.0,
        }

    returns = pd.to_numeric(trades["return"], errors="coerce").dropna()
    pnl = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]
    gross_profit = float(winners.sum())
    gross_loss = float(-losers.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    return {
        "completed_trades": int(len(trades)),
        "winning_trades": int((pnl > 0).sum()),
        "losing_trades": int((pnl < 0).sum()),
        "win_rate": float((pnl > 0).mean()),
        "average_trade_return": float(returns.mean()),
        "median_trade_return": float(returns.median()),
        "best_trade_return": float(returns.max()),
        "worst_trade_return": float(returns.min()),
        "average_holding_days": float(
            pd.to_numeric(trades["holding_calendar_days"], errors="coerce").mean()
        ),
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "total_realized_pnl": float(pnl.sum()),
        "total_cash_dividends": float(
            pd.to_numeric(trades["cash_dividends"], errors="coerce").fillna(0.0).sum()
        ),
    }


def add_benchmarks(
    equity_curve: pd.DataFrame,
    close_prices: pd.DataFrame,
    bank_buy_hold: pd.Series,
    initial_capital: float,
) -> pd.DataFrame:
    output = equity_curve.copy()
    output["bank_buy_hold_equity"] = bank_buy_hold.reindex(output.index).ffill()
    index_close = close_prices[INDEX_CODE].reindex(output.index).ffill()
    first_valid = float(index_close.dropna().iloc[0])
    output["index_price_equity"] = initial_capital * index_close / first_valid
    return output


def annual_returns(equity_curve: pd.DataFrame) -> pd.DataFrame:
    columns = ["equity", "bank_buy_hold_equity", "index_price_equity"]
    year_end = equity_curve[columns].groupby(equity_curve.index.year).last()
    returns = year_end.pct_change()
    first_year = year_end.index[0]
    base = equity_curve[columns].iloc[0]
    returns.loc[first_year] = year_end.loc[first_year] / base - 1.0
    returns.index.name = "year"
    returns.columns = [
        "strategy_return",
        "bank_buy_hold_return",
        "index_price_return",
    ]
    return returns


def serialise(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: serialise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialise(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def percentage(value: Any) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.2%}"


def decimal(value: Any, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.{digits}f}"


def build_report(
    summary: dict[str, Any],
    annual: pd.DataFrame,
) -> str:
    strategy = summary["strategy"]
    bank_hold = summary["bank_buy_hold"]
    index = summary["index_price"]
    trades = summary["trades"]
    config = summary["config"]

    annual_lines = [
        "| 年度 | 策略 | 四大行买入持有 | 上证指数价格收益 |",
        "|---:|---:|---:|---:|",
    ]
    for year, row in annual.iterrows():
        annual_lines.append(
            f"| {year} | {percentage(row['strategy_return'])} | "
            f"{percentage(row['bank_buy_hold_return'])} | "
            f"{percentage(row['index_price_return'])} |"
        )

    return "\n".join(
        [
            "# 四大行 MA20 组合回测报告",
            "",
            "## 策略口径",
            "",
            f"- 信号模式：`{config['signal_mode']}`；MA 窗口：{config['ma_window']} 个交易日。",
            "- 默认均值回归模式：上证指数收盘价下穿 MA 时产生买入信号，上穿 MA 时产生卖出信号。",
            "- 信号在收盘后确认，统一在下一可交易日开盘执行，不使用当日收盘成交。",
            "- 四只银行股等权配置，按 100 股整数手买入；持有期间不再平衡。",
            "- 使用不复权价格，公司行为在除权除息日显式计入现金和持股数量。",
            f"- 初始资金：{config['initial_capital']:,.2f} 元；佣金率：{config['commission_rate']:.4%}；单笔最低佣金：{config['minimum_commission']:.2f} 元。",
            f"- 滑点：{config['slippage_bps']:.2f} bps；印花税模式：`{config['stamp_duty_mode']}`。",
            "",
            "## 核心结果",
            "",
            "| 指标 | MA20 策略 | 四大行买入持有 | 上证指数价格收益 |",
            "|---|---:|---:|---:|",
            f"| 期末净值 | {strategy['final_equity']:,.2f} | {bank_hold['final_equity']:,.2f} | {index['final_equity']:,.2f} |",
            f"| 累计收益 | {percentage(strategy['total_return'])} | {percentage(bank_hold['total_return'])} | {percentage(index['total_return'])} |",
            f"| 年化收益 | {percentage(strategy['cagr'])} | {percentage(bank_hold['cagr'])} | {percentage(index['cagr'])} |",
            f"| 年化波动率 | {percentage(strategy['annual_volatility'])} | {percentage(bank_hold['annual_volatility'])} | {percentage(index['annual_volatility'])} |",
            f"| Sharpe | {decimal(strategy['sharpe_ratio'])} | {decimal(bank_hold['sharpe_ratio'])} | {decimal(index['sharpe_ratio'])} |",
            f"| 最大回撤 | {percentage(strategy['max_drawdown'])} | {percentage(bank_hold['max_drawdown'])} | {percentage(index['max_drawdown'])} |",
            f"| Calmar | {decimal(strategy['calmar_ratio'])} | {decimal(bank_hold['calmar_ratio'])} | {decimal(index['calmar_ratio'])} |",
            "",
            "## 交易统计",
            "",
            f"- 完整交易：{trades['completed_trades']} 次；胜率：{percentage(trades['win_rate'])}。",
            f"- 平均单笔收益：{percentage(trades['average_trade_return'])}；最好：{percentage(trades['best_trade_return'])}；最差：{percentage(trades['worst_trade_return'])}。",
            f"- 平均持有：{decimal(trades['average_holding_days'], 1)} 个自然日；Profit Factor：{decimal(trades['profit_factor'])}。",
            f"- 样本内市场暴露率：{percentage(summary['exposure'])}；期末是否持仓：{summary['final_state']['invested']}。",
            "",
            "## 年度收益",
            "",
            *annual_lines,
            "",
            "## 解释限制",
            "",
            "- 现金分红按税前金额计入，默认股息税率为 0，可通过参数调整。",
            "- 上证指数基准为价格指数收益，不包含不可直接获得的指数分红再投资。",
            "- 四大行买入持有基准使用同一组不复权价格、交易成本和公司行为处理。",
            "- 若样本末仍持仓，策略净值按最后一个交易日收盘价估值，不在缺少下一交易日开盘价时强制平仓。",
            "",
        ]
    )


def write_outputs(
    output_dir: Path,
    result: dict[str, pd.DataFrame | dict[str, Any]],
    equity_curve: pd.DataFrame,
    annual: pd.DataFrame,
    summary: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    equity_curve.to_csv(
        output_dir / "equity_curve.csv",
        encoding="utf-8-sig",
        float_format="%.10f",
    )
    annual.to_csv(
        output_dir / "annual_returns.csv",
        encoding="utf-8-sig",
        float_format="%.10f",
    )

    for key, filename in (
        ("trades", "trades.csv"),
        ("fills", "fills.csv"),
        ("signal_ledger", "signal_ledger.csv"),
        ("corporate_action_ledger", "corporate_action_ledger.csv"),
        ("signals", "signals.csv"),
    ):
        frame = result[key]
        assert isinstance(frame, pd.DataFrame)
        frame.to_csv(output_dir / filename, index=True, encoding="utf-8-sig")

    (output_dir / "summary.json").write_text(
        json.dumps(serialise(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        build_report(summary, annual),
        encoding="utf-8",
    )


def run_backtest(
    data_dir: Path,
    output_dir: Path,
    config: BacktestConfig,
) -> dict[str, Any]:
    open_prices, close_prices = read_price_data(data_dir)
    corporate_actions = read_corporate_actions(data_dir)
    result = run_strategy(open_prices, close_prices, corporate_actions, config)

    strategy_equity = result["equity_curve"]
    assert isinstance(strategy_equity, pd.DataFrame)
    bank_buy_hold = run_buy_and_hold_benchmark(
        open_prices,
        close_prices,
        corporate_actions,
        config,
    )
    equity_curve = add_benchmarks(
        strategy_equity,
        close_prices,
        bank_buy_hold,
        config.initial_capital,
    )
    annual = annual_returns(equity_curve)

    trades = result["trades"]
    assert isinstance(trades, pd.DataFrame)
    final_state = result["final_state"]
    assert isinstance(final_state, dict)
    summary: dict[str, Any] = {
        "config": asdict(config),
        "strategy": performance_metrics(
            equity_curve["equity"], config.initial_capital, config
        ),
        "bank_buy_hold": performance_metrics(
            equity_curve["bank_buy_hold_equity"], config.initial_capital, config
        ),
        "index_price": performance_metrics(
            equity_curve["index_price_equity"], config.initial_capital, config
        ),
        "trades": trade_metrics(trades),
        "exposure": float(equity_curve["invested"].mean()),
        "total_commission": float(
            pd.to_numeric(result["fills"].get("commission", pd.Series(dtype=float)), errors="coerce")
            .fillna(0.0)
            .sum()
        ),
        "total_stamp_duty": float(
            pd.to_numeric(result["fills"].get("stamp_duty", pd.Series(dtype=float)), errors="coerce")
            .fillna(0.0)
            .sum()
        ),
        "credited_cash_dividends": float(
            pd.to_numeric(
                result["corporate_action_ledger"].get(
                    "cash_credit", pd.Series(dtype=float)
                ),
                errors="coerce",
            )
            .fillna(0.0)
            .sum()
        ),
        "final_state": final_state,
    }
    write_outputs(output_dir, result, equity_curve, annual, summary)
    return serialise(summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="四大行 MA20 等权组合回测")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--ma-window", type=int, default=20)
    parser.add_argument(
        "--signal-mode",
        choices=["mean_reversion", "trend_following"],
        default="mean_reversion",
    )
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--board-lot", type=int, default=100)
    parser.add_argument("--dividend-tax-rate", type=float, default=0.0)
    parser.add_argument(
        "--stamp-duty-mode",
        choices=["historical", "fixed", "none"],
        default="historical",
    )
    parser.add_argument("--fixed-stamp-duty-rate", type=float, default=0.0005)
    parser.add_argument("--annual-risk-free-rate", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BacktestConfig(
        initial_capital=args.initial_capital,
        ma_window=args.ma_window,
        signal_mode=args.signal_mode,
        commission_rate=args.commission_rate,
        minimum_commission=args.minimum_commission,
        slippage_bps=args.slippage_bps,
        board_lot=args.board_lot,
        dividend_tax_rate=args.dividend_tax_rate,
        stamp_duty_mode=args.stamp_duty_mode,
        fixed_stamp_duty_rate=args.fixed_stamp_duty_rate,
        annual_risk_free_rate=args.annual_risk_free_rate,
    )
    summary = run_backtest(args.data_dir, args.output_dir, config)
    strategy = summary["strategy"]
    trades = summary["trades"]
    print(
        "Backtest complete | "
        f"final equity={strategy['final_equity']:.2f} | "
        f"total return={strategy['total_return']:.2%} | "
        f"CAGR={strategy['cagr']:.2%} | "
        f"max drawdown={strategy['max_drawdown']:.2%} | "
        f"trades={trades['completed_trades']}"
    )
    print(f"Results: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
