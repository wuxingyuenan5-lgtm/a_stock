#!/usr/bin/env python3
"""Exact-date market runner with official exchange-list universe fallback."""
from __future__ import annotations

import logging

import pandas as pd

import build_market_snapshot as base
_ORIGINAL_EM_UNIVERSE = base.fetch_stock_universe
import run_market_snapshot_v2 as patched
import run_market_snapshot_v3 as report
import run_market_snapshot_v5 as clean_rank
import run_market_snapshot_v6 as v6
import run_market_snapshot_v10 as nonblocking


def exchange_for(code: str) -> str:
    code = base.normalize_code(code)
    if code.startswith(("6", "68")):
        return "sh"
    if code.startswith(("4", "8", "92")):
        return "bj"
    return "sz"


def normalize_universe(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["股票代码"] = result["股票代码"].map(base.normalize_code)
    if "交易所" not in result.columns:
        result["交易所"] = result["股票代码"].map(exchange_for)
    result = result.drop_duplicates("股票代码").sort_values("股票代码").reset_index(drop=True)
    if len(result) < 5000:
        raise RuntimeError(f"股票池异常，仅 {len(result)} 只")
    return result


def fetch_universe_resilient() -> pd.DataFrame:
    try:
        return normalize_universe(_ORIGINAL_EM_UNIVERSE())
    except Exception as exc:
        logging.warning("东方财富股票主表失败，改用沪深京交易所官方清单: %s", exc)
    return normalize_universe(patched.fetch_stock_universe_official())


def main() -> None:
    args = base.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base.fetch_stock_universe = fetch_universe_resilient
    base.fetch_index_snapshot = nonblocking.fetch_indices_nonblocking
    report.write_outputs_safe(args.target_date, args.workers)
    clean_rank.postprocess_industry_ranking(args.target_date)
    v6.append_daily_history(args.target_date)
    logging.info("完成官方股票池降级市场更新: %s", args.target_date)


if __name__ == "__main__":
    main()
