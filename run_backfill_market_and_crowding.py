#!/usr/bin/env python3
"""Run the history backfill with the official-exchange A-share universe."""
from __future__ import annotations

import pandas as pd

import backfill_market_and_crowding as backfill
import run_market_snapshot_v2 as official


def prepare_universe_official() -> tuple[pd.DataFrame, dict[str, str]]:
    universe = official.fetch_stock_universe_official().copy()
    universe["股票代码"] = universe["股票代码"].map(backfill.normalize_code)
    universe["上市日期"] = pd.to_datetime(
        universe["上市日期"], format="%Y%m%d", errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    universe["上市日期"] = universe["上市日期"].fillna("")
    listing_dates = dict(zip(universe["股票代码"], universe["上市日期"]))
    return universe, listing_dates


backfill.prepare_universe = prepare_universe_official

if __name__ == "__main__":
    backfill.main()
