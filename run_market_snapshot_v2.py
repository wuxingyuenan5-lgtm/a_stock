#!/usr/bin/env python3
"""Validation runner for the date-consistent market snapshot."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

import build_market_snapshot as base

BEIJING = timezone(timedelta(hours=8))
_QUOTE_CACHE: list[pd.DataFrame | None] = [None]
_ORIGINAL_FETCH_ALL = base.fetch_all_stock_history


def _date_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y%m%d")


def _spot_snapshot() -> pd.DataFrame:
    if _QUOTE_CACHE[0] is None:
        raw = base.retry(base.ak.stock_zh_a_spot_em)
        required = {"代码", "名称", "最新价", "涨跌幅", "成交额", "总市值", "流通市值"}
        if raw.empty or not required.issubset(raw.columns):
            raise RuntimeError(f"全A收盘快照字段异常: {list(raw.columns)}")
        _QUOTE_CACHE[0] = raw.copy()
    return _QUOTE_CACHE[0].copy()


def fetch_stock_universe_official() -> pd.DataFrame:
    """Build the A-share universe from SSE, SZSE and BSE official lists.

    Exchange lists define codes, names and listing dates. The current all-A
    quote snapshot only enriches market values for the explicit micro fallback.
    """
    frames: list[pd.DataFrame] = []

    sh_main = base.retry(lambda: base.ak.stock_info_sh_name_code(symbol="主板A股"))
    sh_star = base.retry(lambda: base.ak.stock_info_sh_name_code(symbol="科创板"))
    for raw in (sh_main, sh_star):
        frame = raw[["证券代码", "证券简称", "上市日期"]].copy()
        frame.columns = ["股票代码", "股票名称", "上市日期"]
        frames.append(frame)

    sz = base.retry(lambda: base.ak.stock_info_sz_name_code(symbol="A股列表"))
    sz_frame = sz[["A股代码", "A股简称", "A股上市日期"]].copy()
    sz_frame.columns = ["股票代码", "股票名称", "上市日期"]
    frames.append(sz_frame)

    bj = base.retry(base.ak.stock_info_bj_name_code)
    bj_frame = bj[["证券代码", "证券简称", "上市日期"]].copy()
    bj_frame.columns = ["股票代码", "股票名称", "上市日期"]
    frames.append(bj_frame)

    universe = pd.concat(frames, ignore_index=True)
    universe["股票代码"] = universe["股票代码"].map(base.normalize_code)
    universe["股票名称"] = universe["股票名称"].astype(str).str.strip()
    universe["上市日期"] = universe["上市日期"].map(_date_text)
    universe = universe.dropna(subset=["股票代码", "股票名称"]).drop_duplicates("股票代码")
    if len(universe) < 3000:
        raise RuntimeError(f"沪深京官方A股清单异常，仅取得 {len(universe)} 只")

    quote = _spot_snapshot()[["代码", "总市值", "流通市值"]].copy()
    quote.columns = ["股票代码", "总市值", "流通市值"]
    quote["股票代码"] = quote["股票代码"].map(base.normalize_code)
    quote["总市值"] = pd.to_numeric(quote["总市值"], errors="coerce")
    quote["流通市值"] = pd.to_numeric(quote["流通市值"], errors="coerce")
    return universe.merge(quote.drop_duplicates("股票代码"), on="股票代码", how="left")


def fetch_current_close_snapshot(
    universe: pd.DataFrame, target_date: str, workers: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Use one complete post-close snapshot for the current Beijing date.

    Historical target dates still fall back to the original per-security daily
    history implementation.
    """
    today = datetime.now(BEIJING).strftime("%Y%m%d")
    if target_date != today:
        return _ORIGINAL_FETCH_ALL(universe, target_date, workers)

    raw = _spot_snapshot()[["代码", "名称", "最新价", "涨跌幅", "成交额", "总市值", "流通市值"]].copy()
    raw.columns = ["股票代码", "行情名称", "收盘价", "涨跌幅", "成交额", "行情总市值", "行情流通市值"]
    raw["股票代码"] = raw["股票代码"].map(base.normalize_code)
    for column in ("收盘价", "涨跌幅", "成交额", "行情总市值", "行情流通市值"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw["涨跌幅"] = raw["涨跌幅"] / 100
    raw = raw.drop_duplicates("股票代码")

    merged = universe.merge(raw, on="股票代码", how="left")
    valid_mask = (
        merged["收盘价"].notna()
        & merged["成交额"].notna()
        & merged["涨跌幅"].notna()
        & merged["收盘价"].gt(0)
        & merged["成交额"].gt(0)
    )
    valid = merged[valid_mask].copy()
    no_trade = merged[~valid_mask][["股票代码", "股票名称"]].copy()
    no_trade["原因"] = "目标日停牌、无成交或行情缺失"

    valid["日期"] = datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d")
    valid["总市值"] = valid["行情总市值"].combine_first(valid["总市值"])
    valid["流通市值"] = valid["行情流通市值"].combine_first(valid["流通市值"])
    valid = valid[
        [
            "日期", "股票代码", "股票名称", "上市日期", "收盘价",
            "涨跌幅", "成交额", "总市值", "流通市值",
        ]
    ].sort_values("股票代码")

    if len(valid) < 3000:
        raise RuntimeError(f"统一股票池有效行情异常，仅取得 {len(valid)} 只")
    return valid, no_trade, pd.DataFrame(columns=["股票代码", "股票名称", "错误"])


def skip_sw_in_market_snapshot(target_date: str, workers: int = 6):
    """SW is produced by the dedicated industry workflow and merged in the report.

    Keeping it out of this snapshot avoids duplicate requests and still enforces
    exact-date consistency when the final workbook is assembled.
    """
    columns = [
        "日期", "行业层级", "一级行业", "指数代码", "指数名称",
        "收盘价", "成交额_亿元", "日收益率", "20日年化波动率",
    ]
    snapshot = pd.DataFrame(columns=columns)
    failures = pd.DataFrame([
        {
            "指数代码": "ALL",
            "指数名称": "申万一级/二级行业",
            "错误": "由独立申万行业流水线生成，最终报告仅合并同一目标日数据",
        }
    ])
    return snapshot, failures


base.fetch_stock_universe = fetch_stock_universe_official
base.fetch_all_stock_history = fetch_current_close_snapshot
base.fetch_sw_snapshot = skip_sw_in_market_snapshot

if __name__ == "__main__":
    base.main()
