#!/usr/bin/env python3
"""Run the history backfill with a stable historical stock universe.

Shanghai/Shenzhen securities and IPO dates come from BaoStock's security
master. Beijing securities are appended from Eastmoney's current BSE list.
Daily eligibility is still determined from each target day's actual trade,
ST and listing-date fields inside the backfill process.
"""
from __future__ import annotations

import baostock as bs
import pandas as pd

import backfill_market_and_crowding as backfill


def fetch_baostock_shsz_master() -> pd.DataFrame:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    rows: list[list[str]] = []
    try:
        rs = bs.query_stock_basic()
        if rs.error_code != "0":
            raise RuntimeError(f"BaoStock stock basic failed: {rs.error_code} {rs.error_msg}")
        fields = list(rs.fields)
        while rs.next():
            rows.append(rs.get_row_data())
    finally:
        bs.logout()
    frame = pd.DataFrame(rows, columns=fields)
    required = {"code", "code_name", "ipoDate", "type"}
    if frame.empty or not required.issubset(frame.columns):
        raise RuntimeError(f"BaoStock security master invalid: {list(frame.columns)}")
    frame = frame[frame["type"].eq("1") & frame["code"].str.startswith(("sh.", "sz."))].copy()
    frame["股票代码"] = frame["code"].str.split(".").str[-1].str.zfill(6)
    frame["股票名称"] = frame["code_name"].astype(str).str.strip()
    frame["上市日期"] = pd.to_datetime(frame["ipoDate"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    frame["交易所"] = frame["code"].str[:2]
    return frame[["股票代码", "股票名称", "上市日期", "交易所"]]


def fetch_bse_master() -> pd.DataFrame:
    try:
        current = backfill.base.fetch_stock_universe().copy()
        current["股票代码"] = current["股票代码"].map(backfill.normalize_code)
        current = current[current["股票代码"].map(backfill.infer_exchange).eq("bj")].copy()
        current["上市日期"] = pd.to_datetime(
            current["上市日期"], format="%Y%m%d", errors="coerce"
        ).dt.strftime("%Y-%m-%d").fillna("")
        current["交易所"] = "bj"
        return current[["股票代码", "股票名称", "上市日期", "交易所"]]
    except Exception as exc:
        print(f"BSE master unavailable; continue without BSE: {exc}", flush=True)
        return pd.DataFrame(columns=["股票代码", "股票名称", "上市日期", "交易所"])


def prepare_universe_stable() -> tuple[pd.DataFrame, dict[str, str]]:
    universe = pd.concat([fetch_baostock_shsz_master(), fetch_bse_master()], ignore_index=True)
    universe["股票代码"] = universe["股票代码"].map(backfill.normalize_code)
    universe = universe.drop_duplicates("股票代码", keep="last")
    if len(universe) < 4500:
        raise RuntimeError(f"Historical A-share master too small: {len(universe)}")
    listing_dates = dict(zip(universe["股票代码"], universe["上市日期"]))
    return universe, listing_dates


backfill.prepare_universe = prepare_universe_stable

if __name__ == "__main__":
    backfill.main()
