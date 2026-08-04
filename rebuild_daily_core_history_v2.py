#!/usr/bin/env python3
"""Run unified history rebuild with official exchange security lists."""
from __future__ import annotations

import pandas as pd

import rebuild_daily_core_history as core
from run_market_snapshot_v2 import fetch_stock_universe_official


def prepare_universe_official() -> tuple[pd.DataFrame, dict[str, str]]:
    universe = fetch_stock_universe_official().copy()
    universe["股票代码"] = universe["股票代码"].map(core.normalize_code)
    universe["上市日期"] = pd.to_datetime(
        universe["上市日期"], format="%Y%m%d", errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    universe["上市日期"] = universe["上市日期"].fillna("")
    listing_dates = dict(zip(universe["股票代码"], universe["上市日期"]))
    return universe.drop_duplicates("股票代码"), listing_dates


core.prepare_universe = prepare_universe_official

if __name__ == "__main__":
    core.main()
