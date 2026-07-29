#!/usr/bin/env python3
"""Validation runner for the date-consistent market snapshot."""
from __future__ import annotations

import pandas as pd

import build_market_snapshot as base


def _date_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y%m%d")


def fetch_stock_universe_official() -> pd.DataFrame:
    """Build the A-share universe from SSE, SZSE and BSE official lists.

    Exchange lists define codes, names and listing dates. A single all-A quote
    snapshot is merged only to add total/float market value for the explicit
    micro-cap fallback; it does not define the stock universe.
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

    try:
        quote = base.retry(base.ak.stock_zh_a_spot_em)
        market_value = quote[["代码", "总市值", "流通市值"]].copy()
        market_value.columns = ["股票代码", "总市值", "流通市值"]
        market_value["股票代码"] = market_value["股票代码"].map(base.normalize_code)
        market_value["总市值"] = pd.to_numeric(market_value["总市值"], errors="coerce")
        market_value["流通市值"] = pd.to_numeric(market_value["流通市值"], errors="coerce")
        universe = universe.merge(market_value.drop_duplicates("股票代码"), on="股票代码", how="left")
    except Exception:
        universe["总市值"] = pd.NA
        universe["流通市值"] = pd.NA

    return universe


def fetch_sw_snapshot_exact_date(target_date: str, workers: int = 6):
    """Fetch SW data only when the official free source has the target date.

    A single representative index is checked first. If the source has not
    published the target date yet, return an explicit missing-data record and
    never substitute the previous trading day.
    """
    try:
        probe = base.retry(lambda: base.ak.index_hist_sw(symbol="801010", period="day"))
        dates = pd.to_datetime(probe.get("日期"), errors="coerce")
        available = dates.dt.strftime("%Y%m%d").eq(target_date).any()
    except Exception as exc:
        available = False
        probe_error = str(exc)
    else:
        probe_error = "目标日尚未发布"

    if available:
        return base.fetch_sw_snapshot(target_date, workers)

    columns = [
        "日期", "行业层级", "一级行业", "指数代码", "指数名称",
        "收盘价", "成交额_亿元", "日收益率", "20日年化波动率",
    ]
    snapshot = pd.DataFrame(columns=columns)
    failures = pd.DataFrame([
        {
            "指数代码": "ALL",
            "指数名称": "申万一级/二级行业",
            "错误": f"官方免费源未提供 {target_date}：{probe_error}；不混用前一交易日数据",
        }
    ])
    return snapshot, failures


base.fetch_stock_universe = fetch_stock_universe_official
base.fetch_sw_snapshot = fetch_sw_snapshot_exact_date

if __name__ == "__main__":
    base.main()
