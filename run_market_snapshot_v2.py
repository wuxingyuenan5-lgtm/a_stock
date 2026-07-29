#!/usr/bin/env python3
"""Validation runner for the date-consistent market snapshot."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

import build_market_snapshot as base


def fetch_stock_universe_complete() -> pd.DataFrame:
    """Use AKShare's paginated all-A endpoint; do not hand-roll a capped first page."""
    raw = base.retry(base.ak.stock_zh_a_spot_em)
    required = {"代码", "名称", "总市值", "流通市值"}
    if raw.empty or not required.issubset(raw.columns):
        raise RuntimeError(f"A股代码清单字段异常: {list(raw.columns)}")
    frame = raw[["代码", "名称", "总市值", "流通市值"]].copy()
    frame.columns = ["股票代码", "股票名称", "总市值", "流通市值"]
    frame["股票代码"] = frame["股票代码"].map(base.normalize_code)
    frame["股票名称"] = frame["股票名称"].astype(str).str.strip()
    frame["总市值"] = pd.to_numeric(frame["总市值"], errors="coerce")
    frame["流通市值"] = pd.to_numeric(frame["流通市值"], errors="coerce")
    frame["上市日期"] = ""
    frame = frame.drop_duplicates("股票代码")
    if len(frame) < 3000:
        raise RuntimeError(f"A股代码清单异常，仅取得 {len(frame)} 只")
    return frame


def _listing_date_from_individual_info(code: str) -> str:
    try:
        info = base.retry(lambda: base.ak.stock_individual_info_em(symbol=code), attempts=2, delay=0.5)
    except Exception:
        return ""
    if info is None or info.empty or not {"item", "value"}.issubset(info.columns):
        return ""
    values = {str(row["item"]).strip(): row["value"] for _, row in info.iterrows()}
    for key in ("上市时间", "上市日期"):
        text = str(values.get(key, "")).strip().replace("-", "").replace("/", "").replace(".0", "")
        if len(text) == 8 and text.isdigit():
            return text
    return ""


def fetch_one_stock_with_listing_check(row: pd.Series, target_date: str) -> dict[str, object]:
    code = row["股票代码"]
    target_dt = datetime.strptime(target_date, "%Y%m%d")
    start_date = (target_dt - timedelta(days=45)).strftime("%Y%m%d")
    raw = base.retry(
        lambda: base.ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=target_date,
            adjust="",
            timeout=20,
        ),
        attempts=3,
        delay=0.5,
    )
    required = {"日期", "收盘", "成交额", "涨跌幅"}
    if raw.empty or not required.issubset(raw.columns):
        raise base.NoTradingData("目标日无行情")
    frame = raw.copy()
    frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
    frame = frame.dropna(subset=["日期"]).sort_values("日期")
    target = frame[frame["日期"].dt.strftime("%Y%m%d") == target_date]
    if target.empty:
        raise base.NoTradingData("目标日停牌或无交易")
    record = target.iloc[-1]
    amount = pd.to_numeric(record["成交额"], errors="coerce")
    close = pd.to_numeric(record["收盘"], errors="coerce")
    if pd.isna(amount) or pd.isna(close) or float(amount) <= 0 or float(close) <= 0:
        raise base.NoTradingData("目标日停牌或无成交")

    prior = frame[frame["日期"] < target_dt]
    listing_date = ""
    if prior.empty:
        listing_date = _listing_date_from_individual_info(code)
        if listing_date == target_date:
            raise base.NoTradingData("上市首日")

    return {
        "日期": target_dt.strftime("%Y-%m-%d"),
        "股票代码": code,
        "股票名称": row["股票名称"],
        "上市日期": listing_date,
        "收盘价": float(close),
        "涨跌幅": float(pd.to_numeric(record["涨跌幅"], errors="coerce")) / 100,
        "成交额": float(amount),
        "总市值": pd.to_numeric(row.get("总市值"), errors="coerce"),
        "流通市值": pd.to_numeric(row.get("流通市值"), errors="coerce"),
    }


def skip_unavailable_official_sw(target_date: str, workers: int = 6):
    columns = [
        "日期", "行业层级", "一级行业", "指数代码", "指数名称",
        "收盘价", "成交额_亿元", "日收益率", "20日年化波动率",
    ]
    snapshot = pd.DataFrame(columns=columns)
    failures = pd.DataFrame([
        {
            "指数代码": "ALL",
            "指数名称": "申万一级/二级行业",
            "错误": f"官方免费源尚未发布 {target_date}；审核版不混用前一交易日数据",
        }
    ])
    return snapshot, failures


base.fetch_stock_universe = fetch_stock_universe_complete
base.fetch_one_stock = fetch_one_stock_with_listing_check
base.fetch_sw_snapshot = skip_unavailable_official_sw

if __name__ == "__main__":
    base.main()
