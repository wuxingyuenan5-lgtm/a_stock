#!/usr/bin/env python3
"""Resilient 2026 runner: authoritative Choice index with exact-date K-line fallback."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time

import pandas as pd

import run_market_snapshot_v6 as v6
from backfill_market_and_crowding import fetch_em_kline


def fetch_choice_micro_index_resilient(target_date: str) -> dict[str, object]:
    """Use the Choice current quote first, then its own exact-date history.

    The fallback remains the published Choice Micro-cap Index (800007.EI,
    secid 47.800007); it is not a self-built portfolio.
    """
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            return v6.fetch_choice_micro_index(target_date)
        except Exception as exc:
            last_error = exc
            logging.warning("Choice current quote attempt %s failed: %s", attempt, exc)
            time.sleep(attempt * 1.0)

    target_dt = datetime.strptime(target_date, "%Y%m%d")
    start = (target_dt - timedelta(days=20)).strftime("%Y-%m-%d")
    end = target_dt.strftime("%Y-%m-%d")
    frame = fetch_em_kline("47.800007", start, end).copy()
    frame["日期文本"] = frame["日期"].dt.strftime("%Y%m%d")
    frame = frame.sort_values("日期").reset_index(drop=True)
    matches = frame.index[frame["日期文本"].eq(target_date)].tolist()
    if not matches:
        raise RuntimeError(f"Choice微盘指数历史行情缺少 {target_date}; current_error={last_error}")
    pos = matches[-1]
    if pos == 0:
        raise RuntimeError("Choice微盘指数缺少前一交易日，无法计算涨跌幅")

    close = pd.to_numeric(frame.loc[pos, "收盘"], errors="coerce")
    previous = pd.to_numeric(frame.loc[pos - 1, "收盘"], errors="coerce")
    amount = pd.to_numeric(frame.loc[pos, "成交额"], errors="coerce")
    if pd.isna(close) or pd.isna(previous) or float(close) <= 0 or float(previous) <= 0:
        raise RuntimeError("Choice微盘指数历史收盘数据异常")

    return {
        "日期": target_dt.strftime("%Y-%m-%d"),
        "指标": "Choice微盘股指数",
        "数据代码": "800007.EI",
        "收盘点位": float(close),
        "涨跌幅": float(close) / float(previous) - 1,
        "成交额_亿元": float(amount) / 1e8 if not pd.isna(amount) else pd.NA,
        "数据来源": "东方财富Choice指数历史行情",
        "数据口径": "Choice正式发布指数精确交易日日线成交额",
        "替代状态": "原始权威指数；仅由实时快照降级到同指数历史行情",
    }


v6.fetch_choice_micro_index = fetch_choice_micro_index_resilient

if __name__ == "__main__":
    v6.main()
