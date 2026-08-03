#!/usr/bin/env python3
"""Current market update with a verified 2026-07-31 universe cache fallback."""
from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

import pandas as pd

import build_market_snapshot as base
_ORIGINAL_EM_UNIVERSE = base.fetch_stock_universe
import run_market_snapshot_v2 as patched
import run_market_snapshot_v3 as report
import run_market_snapshot_v5 as clean_rank
import run_market_snapshot_v6 as v6
import run_market_snapshot_v10 as nonblocking

CACHE_DIR = Path("data/cache_20260731")


def exchange_for(code: str) -> str:
    code = base.normalize_code(code)
    if code.startswith(("6", "68")):
        return "sh"
    if code.startswith(("4", "8", "92")):
        return "bj"
    return "sz"


def load_cached_universe() -> pd.DataFrame:
    path = CACHE_DIR / "market_filtered_stocks_20260731.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"股票代码": str, "上市日期": str})
    frame["股票代码"] = frame["股票代码"].map(base.normalize_code)
    frame["上市日期"] = frame["上市日期"].fillna("").astype(str).str.replace(".0", "", regex=False)
    universe = frame[["股票代码", "股票名称", "上市日期", "总市值", "流通市值"]].copy()
    universe["交易所"] = universe["股票代码"].map(exchange_for)

    errors_path = CACHE_DIR / "market_snapshot_errors_20260731.csv"
    if errors_path.exists():
        errors = pd.read_csv(errors_path, encoding="utf-8-sig", dtype={"股票代码": str})
        errors["股票代码"] = errors["股票代码"].map(base.normalize_code)
        missing = errors.loc[~errors["股票代码"].isin(universe["股票代码"]), ["股票代码", "股票名称"]].copy()
        if not missing.empty:
            missing["上市日期"] = ""
            missing["总市值"] = pd.NA
            missing["流通市值"] = pd.NA
            missing["交易所"] = missing["股票代码"].map(exchange_for)
            universe = pd.concat([universe, missing], ignore_index=True)
    universe = universe.drop_duplicates("股票代码").sort_values("股票代码")
    if len(universe) < 5000:
        raise RuntimeError(f"缓存股票池异常，仅 {len(universe)} 只")
    logging.warning("使用2026-07-31已验证股票池缓存，共%s只；目标日上市首日仍由日期规则排除", len(universe))
    return universe


def fetch_universe_resilient() -> pd.DataFrame:
    try:
        universe = _ORIGINAL_EM_UNIVERSE().copy()
        universe["交易所"] = universe["股票代码"].map(exchange_for)
        return universe
    except Exception as exc:
        logging.warning("当日股票主表失败，启用最近交易日验证缓存: %s", exc)
        return load_cached_universe()


def main() -> None:
    args = base.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base.fetch_stock_universe = fetch_universe_resilient
    base.fetch_index_snapshot = nonblocking.fetch_indices_nonblocking
    report.write_outputs_safe(args.target_date, args.workers)
    clean_rank.postprocess_industry_ranking(args.target_date)
    v6.append_daily_history(args.target_date)
    logging.info("完成缓存降级市场更新: %s", args.target_date)


if __name__ == "__main__":
    main()
