#!/usr/bin/env python3
from __future__ import annotations

import pandas as pd
import akshare as ak
import rebuild_daily_core_history_v3 as robust


def prepare_universe_with_fallback():
    try:
        return robust.prepare_universe_official()
    except Exception as exc:
        print(f"official universe failed, fallback to stock_zh_a_spot: {exc}", flush=True)
    spot = ak.stock_zh_a_spot().copy()
    code_col = "代码" if "代码" in spot.columns else "symbol"
    name_col = "名称" if "名称" in spot.columns else "name"
    universe = pd.DataFrame({
        "股票代码": spot[code_col].astype(str).str.extract(r"(\d{6})", expand=False),
        "股票名称": spot[name_col].astype(str),
        "上市日期": "",
    }).dropna(subset=["股票代码"])
    universe = universe.drop_duplicates("股票代码")
    listing_dates = {code: "" for code in universe["股票代码"]}
    print(f"fallback universe rows={len(universe)}", flush=True)
    return universe, listing_dates


robust.core.prepare_universe = prepare_universe_with_fallback

if __name__ == "__main__":
    robust.core.main()
