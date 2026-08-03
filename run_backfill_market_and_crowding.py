#!/usr/bin/env python3
"""Run the history backfill with a stable historical stock universe.

Shanghai/Shenzhen securities and IPO dates come from BaoStock's security
master. Beijing securities and IPO dates come from the repository's verified
BSE master file. Daily eligibility is still determined from each target day's
actual trade, ST and listing-date fields inside the backfill process.
"""
from __future__ import annotations

from pathlib import Path
import time

import baostock as bs
import pandas as pd

import backfill_market_and_crowding as backfill

BSE_MASTER = Path("data/bse_security_master.csv")


def baostock_login_with_retry(attempts: int = 10):
    last = None
    for attempt in range(1, attempts + 1):
        result = bs.login()
        if result.error_code == "0":
            return result
        last = result
        time.sleep(min(5 * attempt, 30))
    raise RuntimeError(f"BaoStock login failed: {last.error_code} {last.error_msg}")


def fetch_baostock_shsz_master() -> pd.DataFrame:
    baostock_login_with_retry()
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
    if not BSE_MASTER.exists():
        raise FileNotFoundError(f"Missing BSE master: {BSE_MASTER}")
    frame = pd.read_csv(BSE_MASTER, encoding="utf-8-sig", dtype={"股票代码": str})
    frame["股票代码"] = frame["股票代码"].map(backfill.normalize_code)
    frame["上市日期"] = pd.to_datetime(
        frame["上市日期"].astype(str), format="%Y%m%d", errors="coerce"
    ).dt.strftime("%Y-%m-%d").fillna("")
    frame["交易所"] = "bj"
    return frame[["股票代码", "股票名称", "上市日期", "交易所"]]


def prepare_universe_stable() -> tuple[pd.DataFrame, dict[str, str]]:
    universe = pd.concat([fetch_baostock_shsz_master(), fetch_bse_master()], ignore_index=True)
    universe["股票代码"] = universe["股票代码"].map(backfill.normalize_code)
    universe = universe.drop_duplicates("股票代码", keep="last")
    if len(universe) < 5000:
        raise RuntimeError(f"Historical A-share master too small: {len(universe)}")
    listing_dates = dict(zip(universe["股票代码"], universe["上市日期"]))
    return universe, listing_dates


backfill.prepare_universe = prepare_universe_stable

if __name__ == "__main__":
    backfill.main()
