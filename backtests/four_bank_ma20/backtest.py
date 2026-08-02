#!/usr/bin/env python3
"""Complete event-driven backtest for the four-bank MA20 strategy.

Default rule:
- Shanghai Composite close crosses below SMA20 -> buy four banks next tradable open.
- Shanghai Composite close crosses above SMA20 -> sell all next tradable open.
- Four stocks are equal-weighted and rounded to 100-share board lots.
- Execution and valuation use unadjusted prices; corporate actions are applied
  explicitly on the ex-date before that day's opening execution.
- A suspended stock is valued at its most recent available close. Missing opens
  are never filled, so orders only execute when all four stocks have valid opens.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
import json
import math
from pathlib import Path
from typing import Any

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
            raise ValueError("invalid signal_mode")
        if self.commission_rate < 0 or self.minimum_commission < 0:
            raise ValueError("commission parameters cannot be negative")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")
        if self.board_lot <= 0:
            raise ValueError("board_lot must be positive")
        if not 0 <= self.dividend_tax_rate < 1:
            raise ValueError("dividend_tax_rate must be in [0, 1)")
        if self.stamp_duty_mode not in {"historical", "fixed", "none"}:
            raise ValueError("invalid stamp_duty_mode")


def read_price_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    open_path = data_dir / "open_prices_wide.csv"
    close_path = data_dir / "close_prices_wide.csv"
    if not open_path.exists() or not close_path.exists():
        raise FileNotFoundError("Run download_data.py before the backtest")

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

    dates = open_prices.index.intersection(close_prices.index)
    open_prices = open_prices.loc[dates, required].copy()
    close_prices = close_prices.loc[dates, required].copy()
    if open_prices.empty:
        raise ValueError("No overlapping price dates")

    # Suspensions create blank close fields in the wide table. Carrying the last
    # observable close is the standard mark-to-market treatment. Opens remain raw.
    close_prices[BANK_CODES] = close_prices[BANK_CODES].ffill()
    if close_prices[BANK_CODES].isna().any().any():
        raise ValueError("Bank close prices still contain leading missing values")
    if close_prices[INDEX_CODE].dropna().empty:
        raise ValueError("Index close series is empty")
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
    for column in [
        "cash_before_tax_per_share",
        "stock_dividend_per_share",
        "capitalisation_issue_per_share",
    ]:
        actions[column] = pd.to_numeric(actions[column], errors="coerce").fillna(0.0)
    actions = actions[
        actions["code"].isin(BANK_CODES) & actions["ex_date"].notna()
    ].copy()
    return actions.sort_values(["ex_date", "code"]).reset_index(drop=True)


def build_signal_table(
    index_close: pd.Series,
    ma_window: int,
    signal_mode: str,
) -> pd.DataFrame:
    close = pd.to_numeric(index_close, errors="coerce").sort_index()
    ma = close.rolling(ma_window, min_periods=ma_window).mean()
    previous_close = close.shift(1)
    previous_ma = ma.shift(1)
    valid = ma.notna() & previous_ma.notna()
    cross_below = valid & (previous_close >= previous_ma) & (close < ma)
    cross_above = valid & (previous_close <= previous_ma) & (close > ma)

    if signal_mode == "mean_reversion":
        entry, exit_ = cross_below, cross_above
    elif signal_mode == "trend_following":
        entry, exit_ = cross_above, cross_below
    else:
        raise ValueError(f"Unsupported signal mode: {signal_mode}")

    signal = pd.Series("", index=close.index, dtype="object")
    signal.loc[entry] = "entry"
    signal.loc[exit_] = "exit"
    return pd.DataFrame(
        {
            "index_close": close,
            "ma": ma,
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
    index = execution_dates.searchsorted(signal_date, side="right")
    if index >= len(execution_dates):
        return None
    return pd.Timestamp(execution_dates[index])


def commission(notional: float, config: BacktestConfig) -> float:
    if notional <= 0:
        return 0.0
    return max(notional * config.commission_rate, config.minimum_commission)


def stamp_duty_rate(trade_date: pd.Timestamp, config: BacktestConfig) -> float:
    if config.stamp_duty_mode == "none":
        return 0.0
    if config.stamp_duty_mode == "fixed":
        return config.fixed_stamp_duty_rate
    return 0.001 if trade_date.date() < date(2023, 8, 28) else 0.0005


def effective_price(raw_price: float, side: str, slippage_bps: float) -> float:
    slip = slippage_bps / 10_000.0
    if side == "buy":
        return raw_price * (1.0 + slip)
    if side == "sell":
        return raw_price * (1.0 - slip)
    raise ValueError(f"Unsupported side: {side}")


def allocate_equal_weight(
    cash: float,
    raw_open_prices: pd.Series,
    config: BacktestConfig,
) -> tuple[dict[str, int], dict[str, float], dict[str, float]]:
    prices = {
        code: effective_price(float(raw_open_prices[code]), "buy", config.slippage_bps)
        for code in BANK_CODES
    }
    target = cash / len(BANK_CODES)
    quantities = {
        code: math.floor(target / prices[code] / config.board_lot) * config.board_lot
        for code in BANK_CODES
    }

    def cash_required() -> tuple[float, dict[str, float]]:
        fees: dict[str, float] = {}
        required = 0.0
        for code in BANK_CODES:
            notional = quantities[code] * prices[code]
            fees[code] = commission(notional, config)
            required += notional + fees[code]
        return required, fees

    required, fees = cash_required()
    while required > cash + 1e-8:
        candidates = [code for code in BANK_CODES if quantities[code] >= config.board_lot]
        if not candidates:
            break
        reduce_code = max(candidates, key=lambda code: quantities[code] * prices[code])
        quantities[reduce_code] -= config.board_lot
        required, fees = cash_required()

    if any(quantity <= 0 for quantity in quantities.values()):
        raise ValueError("Capital is insufficient for one board lot of every stock")
    if required > cash + 1e-8:
        raise ValueError("Unable to construct an affordable portfolio")
    return quantities, prices, fees


def action_map(actions: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    return {
        pd.Timestamp(ex_date): group.copy()
        for ex_date, group in actions.groupby("ex_date", sort=True)
    }


def apply_actions(
    trade_date: pd.Timestamp,
    state: dict[str, Any],
    actions_by_date: dict[pd.Timestamp, pd.DataFrame],
    config: BacktestConfig,
    ledger: list[dict[str, Any]],
) -> None:
    rows = actions_by_date.get(trade_date)
    if rows is None:
        return
    for row in rows.itertuples(index=False):
        code = str(row.code)
        quantity_before = float(state["shares"].get(code, 0.0))
        if quantity_before <= 0:
            continue
        cash_ps = float(row.cash_before_tax_per_share)
        stock_ratio = float(row.stock_dividend_per_share)
        cap_ratio = float(row.capitalisation_issue_per_share)
        cash_credit = quantity_before * cash_ps * (1.0 - config.dividend_tax_rate)
        bonus_shares = quantity_before * (stock_ratio + cap_ratio)
        state["cash"] += cash_credit
        state["shares"][code] = quantity_before + bonus_shares
        if state["open_trade"] is not None:
            state["open_trade"]["cash_dividends"] += cash_credit
            state["open_trade"]["bonus_shares"] += bonus_shares
        ledger.append(
            {
                "date": trade_date,
                "code": code,
                "name": BANK_NAMES[code],
                "shares_before": quantity_before,
                "cash_per_share_before_tax": cash_ps,
                "dividend_tax_rate": config.dividend_tax_rate,
                "cash_credit": cash_credit,
                "stock_dividend_ratio": stock_ratio,
                "capitalisation_ratio": cap_ratio,
                "bonus_shares": bonus_shares,
                "shares_after": state["shares"][code],
            }
        )


def execute_buy(
    trade_date: pd.Timestamp,
    pending: dict[str, Any],
    state: dict[str, Any],
    open_prices: pd.DataFrame,
    config: BacktestConfig,
    fills: list[dict[str, Any]],
) -> None:
    starting_equity = float(state["cash"])
    quantities, prices, fees = allocate_equal_weight(
        state["cash"], open_prices.loc[trade_date, BANK_CODES], config
    )
    entry_notional = 0.0
    entry_costs = 0.0
    for code in BANK_CODES:
        quantity = quantities[code]
        price = prices[code]
        notional = quantity * price
        fee = fees[code]
        state["cash"] -= notional + fee
        state["shares"][code] = float(quantity)
        entry_notional += notional
        entry_costs += fee
        fills.append(
            {
                "date": trade_date,
                "signal_date": pending["signal_date"],
                "side": "buy",
                "code": code,
                "name": BANK_NAMES[code],
                "quantity": quantity,
                "raw_open": float(open_prices.loc[trade_date, code]),
                "execution_price": price,
                "notional": notional,
                "commission": fee,
                "stamp_duty": 0.0,
                "slippage_bps": config.slippage_bps,
                "reason": pending["reason"],
            }
        )
    if state["cash"] < -1e-6:
        raise RuntimeError("Negative cash after entry")
    state["open_trade"] = {
        "entry_signal_date": pending["signal_date"],
        "entry_date": trade_date,
        "starting_equity": starting_equity,
        "entry_notional": entry_notional,
        "entry_costs": entry_costs,
        "entry_prices": prices.copy(),
        "entry_shares": {code: float(quantities[code]) for code in BANK_CODES},
        "cash_dividends": 0.0,
        "bonus_shares": 0.0,
    }
    state["pending"] = None


def execute_sell(
    trade_date: pd.Timestamp,
    pending: dict[str, Any],
    state: dict[str, Any],
    open_prices: pd.DataFrame,
    config: BacktestConfig,
    fills: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> None:
    open_trade = state["open_trade"]
    if open_trade is None:
        raise RuntimeError("Sell has no open trade")
    duty_rate = stamp_duty_rate(trade_date, config)
    exit_notional = 0.0
    exit_commission = 0.0
    exit_stamp = 0.0
    exit_prices: dict[str, float] = {}
    exit_shares: dict[str, float] = {}

    for code in BANK_CODES:
        quantity = float(state["shares"][code])
        raw_open = float(open_prices.loc[trade_date, code])
        price = effective_price(raw_open, "sell", config.slippage_bps)
        notional = quantity * price
        fee = commission(notional, config)
        stamp = notional * duty_rate
        state["cash"] += notional - fee - stamp
        state["shares"][code] = 0.0
        exit_notional += notional
        exit_commission += fee
        exit_stamp += stamp
        exit_prices[code] = price
        exit_shares[code] = quantity
        fills.append(
            {
                "date": trade_date,
                "signal_date": pending["signal_date"],
                "side": "sell",
                "code": code,
                "name": BANK_NAMES[code],
                "quantity": quantity,
                "raw_open": raw_open,
                "execution_price": price,
                "notional": notional,
                "commission": fee,
                "stamp_duty": stamp,
                "slippage_bps": config.slippage_bps,
                "reason": pending["reason"],
            }
        )

    ending_equity = float(state["cash"])
    pnl = ending_equity - open_trade["starting_equity"]
    trades.append(
        {
            "entry_signal_date": open_trade["entry_signal_date"],
            "entry_date": open_trade["entry_date"],
            "exit_signal_date": pending["signal_date"],
            "exit_date": trade_date,
            "holding_calendar_days": (trade_date - open_trade["entry_date"]).days,
            "starting_equity": open_trade["starting_equity"],
            "ending_equity": ending_equity,
            "entry_notional": open_trade["entry_notional"],
            "exit_notional": exit_notional,
            "entry_commission": open_trade["entry_costs"],
            "exit_commission": exit_commission,
            "stamp_duty": exit_stamp,
            "cash_dividends": open_trade["cash_dividends"],
            "bonus_shares": open_trade["bonus_shares"],
            "pnl": pnl,
            "return": pnl / open_trade["starting_equity"],
            "entry_prices": json.dumps(open_trade["entry_prices"], ensure_ascii=False),
            "exit_prices": json.dumps(exit_prices, ensure_ascii=False),
            "entry_shares": json.dumps(open_trade["entry_shares"], ensure_ascii=False),
            "exit_shares": json.dumps(exit_shares, ensure_ascii=False),
        }
    )
    state["open_trade"] = None
    state["pending"] = None


def invested(state: dict[str, Any]) -> bool:
    return any(float(state["shares"][code]) > 0 for code in BANK_CODES)


def mark_to_market(
    state: dict[str, Any],
    close_row: pd.Series,
) -> tuple[float, float]:
    position_value = sum(
        float(state["shares"][code]) * float(close_row[code]) for code in BANK_CODES
    )
    return float(state["cash"]) + position_value, position_value


def simulate_strategy(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    actions: pd.DataFrame,
    config: BacktestConfig,
) -> dict[str, Any]:
    signals = build_signal_table(close_prices[INDEX_CODE], config.ma_window, config.signal_mode)
    execution_dates = common_execution_dates(open_prices)
    actions_by_date = action_map(actions)
    state: dict[str, Any] = {
        "cash": config.initial_capital,
        "shares": {code: 0.0 for code in BANK_CODES},
        "pending": None,
        "open_trade": None,
    }
    fills: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    action_ledger: list[dict[str, Any]] = []
    signal_ledger: list[dict[str, Any]] = []
    equity_records: list[dict[str, Any]] = []

    for trade_date in close_prices.index:
        trade_date = pd.Timestamp(trade_date)
        apply_actions(trade_date, state, actions_by_date, config, action_ledger)

        pending = state["pending"]
        if pending is not None and pending["execution_date"] == trade_date:
            if pending["side"] == "buy":
                execute_buy(trade_date, pending, state, open_prices, config, fills)
            else:
                execute_sell(trade_date, pending, state, open_prices, config, fills, trades)

        equity, position_value = mark_to_market(state, close_prices.loc[trade_date])
        equity_records.append(
            {
                "date": trade_date,
                "cash": state["cash"],
                "position_value": position_value,
                "equity": equity,
                "invested": invested(state),
                **{f"shares_{code}": state["shares"][code] for code in BANK_CODES},
            }
        )

        signal = str(signals.loc[trade_date, "signal"])
        if signal in {"entry", "exit"}:
            eligible = (
                signal == "entry" and not invested(state) and state["pending"] is None
            ) or (
                signal == "exit" and invested(state) and state["pending"] is None
            )
            execution_date = next_execution_date(trade_date, execution_dates) if eligible else None
            status = "ignored"
            if eligible and execution_date is not None:
                state["pending"] = {
                    "side": "buy" if signal == "entry" else "sell",
                    "signal_date": trade_date,
                    "execution_date": execution_date,
                    "reason": f"{signal}_signal",
                }
                status = "scheduled"
            elif eligible:
                status = "no_future_execution_date"
            signal_ledger.append(
                {
                    "signal_date": trade_date,
                    "signal": signal,
                    "portfolio_invested": invested(state),
                    "status": status,
                    "execution_date": execution_date,
                }
            )

    equity_curve = pd.DataFrame(equity_records).set_index("date")
    equity_curve["daily_return"] = equity_curve["equity"].pct_change().fillna(0.0)
    equity_curve["running_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown"] = equity_curve["equity"] / equity_curve["running_peak"] - 1.0
    return {
        "equity_curve": equity_curve,
        "trades": pd.DataFrame(trades),
        "fills": pd.DataFrame(fills),
        "signal_ledger": pd.DataFrame(signal_ledger),
        "corporate_action_ledger": pd.DataFrame(action_ledger),
        "signals": signals,
        "final_state": state,
    }


def simulate_buy_hold(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    actions: pd.DataFrame,
    config: BacktestConfig,
) -> pd.Series:
    execution_dates = common_execution_dates(open_prices)
    if execution_dates.empty:
        raise ValueError("No benchmark entry date")
    entry_date = pd.Timestamp(execution_dates[0])
    state: dict[str, Any] = {
        "cash": config.initial_capital,
        "shares": {code: 0.0 for code in BANK_CODES},
        "pending": None,
        "open_trade": None,
    }
    execute_buy(
        entry_date,
        {
            "signal_date": entry_date,
            "execution_date": entry_date,
            "side": "buy",
            "reason": "buy_and_hold_benchmark",
        },
        state,
        open_prices,
        config,
        [],
    )
    actions_by_date = action_map(actions)
    values: dict[pd.Timestamp, float] = {}
    for trade_date in close_prices.index:
        trade_date = pd.Timestamp(trade_date)
        if trade_date < entry_date:
            values[trade_date] = config.initial_capital
            continue
        if trade_date > entry_date:
            apply_actions(trade_date, state, actions_by_date, config, [])
        values[trade_date] = mark_to_market(state, close_prices.loc[trade_date])[0]
    return pd.Series(values, name="bank_buy_hold_equity").sort_index()


def performance_metrics(
    equity: pd.Series,
    initial_capital: float,
    config: BacktestConfig,
) -> dict[str, Any]:
    equity = equity.dropna().astype(float)
    first_date = pd.Timestamp(equity.index[0])
    last_date = pd.Timestamp(equity.index[-1])
    years = max((last_date - first_date).days / 365.2425, 1 / 365.2425)
    total_return = float(equity.iloc[-1] / initial_capital - 1.0)
    cagr = float((equity.iloc[-1] / initial_capital) ** (1.0 / years) - 1.0)
    returns = equity.pct_change().dropna()
    std = float(returns.std(ddof=1))
    annual_volatility = std * math.sqrt(config.trading_days_per_year)
    excess = returns - config.annual_risk_free_rate / config.trading_days_per_year
    sharpe = float(excess.mean() / std * math.sqrt(config.trading_days_per_year)) if std > 0 else None
    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        float(excess.mean() / downside_std * math.sqrt(config.trading_days_per_year))
        if downside_std > 0
        else None
    )
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    trough_date = pd.Timestamp(drawdown.idxmin())
    peak_date = pd.Timestamp(equity.loc[:trough_date].idxmax())
    max_drawdown = float(drawdown.loc[trough_date])
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else None
    return {
        "start_date": first_date,
        "end_date": last_date,
        "initial_equity": initial_capital,
        "final_equity": float(equity.iloc[-1]),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_drawdown,
        "max_drawdown_peak_date": peak_date,
        "max_drawdown_trough_date": trough_date,
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
    pnl = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
    returns = pd.to_numeric(trades["return"], errors="coerce").dropna()
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    return {
        "completed_trades": int(len(trades)),
        "winning_trades": int((pnl > 0).sum()),
        "losing_trades": int((pnl < 0).sum()),
        "win_rate": float((pnl > 0).mean()),
        "average_trade_return": float(returns.mean()),
        "median_trade_return": float(returns.median()),
        "best_trade_return": float(returns.max()),
        "worst_trade_return": float(returns.min()),
        "average_holding_days": float(pd.to_numeric(trades["holding_calendar_days"]).mean()),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "total_realized_pnl": float(pnl.sum()),
        "total_cash_dividends": float(pd.to_numeric(trades["cash_dividends"]).fillna(0.0).sum()),
    }


def add_benchmarks(
    strategy_curve: pd.DataFrame,
    close_prices: pd.DataFrame,
    buy_hold: pd.Series,
    initial_capital: float,
) -> pd.DataFrame:
    output = strategy_curve.copy()
    output["bank_buy_hold_equity"] = buy_hold.reindex(output.index).ffill()
    index_close = close_prices[INDEX_CODE].reindex(output.index).ffill()
    output["index_price_equity"] = initial_capital * index_close / float(index_close.dropna().iloc[0])
    return output


def annual_returns(equity_curve: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    columns = ["equity", "bank_buy_hold_equity", "index_price_equity"]
    year_end = equity_curve[columns].groupby(equity_curve.index.year).last()
    returns = year_end.pct_change()
    returns.iloc[0] = year_end.iloc[0] / initial_capital - 1.0
    returns.index.name = "year"
    returns.columns = ["strategy_return", "bank_buy_hold_return", "index_price_return"]
    return returns


def serialise(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dict):
        return {key: serialise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialise(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def pct(value: Any) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.2%}"


def num(value: Any, digits: int = 3) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"


def build_report(summary: dict[str, Any], annual: pd.DataFrame) -> str:
    strategy = summary["strategy"]
    hold = summary["bank_buy_hold"]
    index = summary["index_price"]
    trades = summary["trades"]
    cfg = summary["config"]
    annual_rows = [
        "| 年度 | 策略 | 四大行买入持有 | 上证指数价格收益 |",
        "|---:|---:|---:|---:|",
    ]
    for year, row in annual.iterrows():
        annual_rows.append(
            f"| {year} | {pct(row['strategy_return'])} | {pct(row['bank_buy_hold_return'])} | {pct(row['index_price_return'])} |"
        )
    return "\n".join(
        [
            "# 四大行 MA20 组合回测报告",
            "",
            "## 回测口径",
            "",
            f"- 信号模式：`{cfg['signal_mode']}`；均线窗口：{cfg['ma_window']}。",
            "- 收盘确认信号，下一可交易日开盘成交；四只银行股必须同时存在有效开盘价。",
            "- 等权、100 股整数手、持有期间不再平衡；停牌日按最近有效收盘价估值。",
            "- 不复权价格成交和估值，公司行为在除权除息日开盘前显式入账。",
            f"- 初始资金 {cfg['initial_capital']:,.2f} 元；佣金 {cfg['commission_rate']:.4%}；最低佣金 {cfg['minimum_commission']:.2f} 元；滑点 {cfg['slippage_bps']:.2f} bps。",
            "",
            "## 核心结果",
            "",
            "| 指标 | MA20 策略 | 四大行买入持有 | 上证指数价格收益 |",
            "|---|---:|---:|---:|",
            f"| 期末权益 | {strategy['final_equity']:,.2f} | {hold['final_equity']:,.2f} | {index['final_equity']:,.2f} |",
            f"| 累计收益 | {pct(strategy['total_return'])} | {pct(hold['total_return'])} | {pct(index['total_return'])} |",
            f"| 年化收益 | {pct(strategy['cagr'])} | {pct(hold['cagr'])} | {pct(index['cagr'])} |",
            f"| 年化波动 | {pct(strategy['annual_volatility'])} | {pct(hold['annual_volatility'])} | {pct(index['annual_volatility'])} |",
            f"| Sharpe | {num(strategy['sharpe_ratio'])} | {num(hold['sharpe_ratio'])} | {num(index['sharpe_ratio'])} |",
            f"| 最大回撤 | {pct(strategy['max_drawdown'])} | {pct(hold['max_drawdown'])} | {pct(index['max_drawdown'])} |",
            f"| Calmar | {num(strategy['calmar_ratio'])} | {num(hold['calmar_ratio'])} | {num(index['calmar_ratio'])} |",
            "",
            "## 交易统计",
            "",
            f"- 完整交易：{trades['completed_trades']} 次；胜率：{pct(trades['win_rate'])}。",
            f"- 平均单笔收益：{pct(trades['average_trade_return'])}；最好：{pct(trades['best_trade_return'])}；最差：{pct(trades['worst_trade_return'])}。",
            f"- 平均持有：{num(trades['average_holding_days'], 1)} 个自然日；Profit Factor：{num(trades['profit_factor'])}。",
            f"- 市场暴露率：{pct(summary['exposure'])}；期末是否持仓：{summary['final_state']['invested']}。",
            "",
            "## 年度收益",
            "",
            *annual_rows,
            "",
            "## 限制",
            "",
            "- 现金分红默认按税前金额计入，可通过 `--dividend-tax-rate` 调整。",
            "- 上证指数基准是价格指数；四大行买入持有基准使用同一交易成本和公司行为口径。",
            "- 样本末仍持仓时按最后收盘价估值，不伪造下一交易日开盘价平仓。",
            "",
        ]
    )


def write_outputs(
    output_dir: Path,
    result: dict[str, Any],
    equity_curve: pd.DataFrame,
    annual: pd.DataFrame,
    summary: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    equity_curve.to_csv(output_dir / "equity_curve.csv", encoding="utf-8-sig", float_format="%.10f")
    annual.to_csv(output_dir / "annual_returns.csv", encoding="utf-8-sig", float_format="%.10f")
    for key, filename, include_index in [
        ("trades", "trades.csv", False),
        ("fills", "fills.csv", False),
        ("signal_ledger", "signal_ledger.csv", False),
        ("corporate_action_ledger", "corporate_action_ledger.csv", False),
        ("signals", "signals.csv", True),
    ]:
        result[key].to_csv(output_dir / filename, index=include_index, encoding="utf-8-sig")
    (output_dir / "summary.json").write_text(
        json.dumps(serialise(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(build_report(summary, annual), encoding="utf-8")


def run_backtest(data_dir: Path, output_dir: Path, config: BacktestConfig) -> dict[str, Any]:
    config.validate()
    open_prices, close_prices = read_price_data(data_dir)
    actions = read_corporate_actions(data_dir)
    result = simulate_strategy(open_prices, close_prices, actions, config)
    buy_hold = simulate_buy_hold(open_prices, close_prices, actions, config)
    curve = add_benchmarks(result["equity_curve"], close_prices, buy_hold, config.initial_capital)
    annual = annual_returns(curve, config.initial_capital)
    fills = result["fills"]
    action_ledger = result["corporate_action_ledger"]
    state = result["final_state"]
    summary = {
        "config": asdict(config),
        "strategy": performance_metrics(curve["equity"], config.initial_capital, config),
        "bank_buy_hold": performance_metrics(curve["bank_buy_hold_equity"], config.initial_capital, config),
        "index_price": performance_metrics(curve["index_price_equity"], config.initial_capital, config),
        "trades": trade_metrics(result["trades"]),
        "exposure": float(curve["invested"].mean()),
        "total_commission": float(pd.to_numeric(fills.get("commission", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()),
        "total_stamp_duty": float(pd.to_numeric(fills.get("stamp_duty", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()),
        "credited_cash_dividends": float(pd.to_numeric(action_ledger.get("cash_credit", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()),
        "final_state": {
            "cash": state["cash"],
            "shares": state["shares"],
            "invested": invested(state),
            "pending": state["pending"],
            "open_trade": state["open_trade"],
        },
    }
    write_outputs(output_dir, result, curve, annual, summary)
    return serialise(summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="四大行 MA20 等权组合回测")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--ma-window", type=int, default=20)
    parser.add_argument("--signal-mode", choices=["mean_reversion", "trend_following"], default="mean_reversion")
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--board-lot", type=int, default=100)
    parser.add_argument("--dividend-tax-rate", type=float, default=0.0)
    parser.add_argument("--stamp-duty-mode", choices=["historical", "fixed", "none"], default="historical")
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
