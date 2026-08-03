#!/usr/bin/env python3
"""Run the history backfill with a stable historical stock universe.

Shanghai/Shenzhen securities and IPO dates come from BaoStock's security
master. Beijing securities and IPO dates come from the repository's verified
BSE master file. Daily eligibility is determined from each target day's actual
trade, ST and listing-date fields.
"""
from __future__ import annotations

import csv
from pathlib import Path
import time

import baostock as bs
import pandas as pd

import backfill_market_and_crowding as backfill

BSE_MASTER = Path("data/bse_security_master.csv")


def baostock_login_with_retry(attempts: int = 12):
    last = None
    for attempt in range(1, attempts + 1):
        result = bs.login()
        if result.error_code == "0":
            return result
        last = result
        time.sleep(min(3 * attempt, 20))
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


def robust_baostock_worker(
    worker_id: int,
    codes: list[str],
    start_date: str,
    end_date: str,
    listing_dates: dict[str, str],
    output_dir: str,
) -> tuple[str, int, int]:
    """BaoStock worker that reconnects after network faults.

    Hosted runners occasionally lose the BaoStock socket after several minutes.
    The worker therefore reconnects periodically and retries an individual
    security before recording it as failed.
    """
    out_path = Path(output_dir) / f"bs_part_{worker_id:02d}.csv"
    failures = 0
    rows_written = 0

    def reconnect() -> None:
        try:
            bs.logout()
        except Exception:
            pass
        baostock_login_with_retry()

    baostock_login_with_retry()
    try:
        with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["日期", "股票代码", "涨跌幅", "成交额", "换手率", "交易所"])
            for position, code in enumerate(codes, start=1):
                if position > 1 and position % 180 == 1:
                    reconnect()
                exchange = backfill.infer_exchange(code)
                bs_code = f"{exchange}.{code}"
                success = False
                for retry in range(3):
                    try:
                        rs = bs.query_history_k_data_plus(
                            bs_code,
                            "date,code,close,preclose,amount,turn,tradestatus,pctChg,isST",
                            start_date=start_date,
                            end_date=end_date,
                            frequency="d",
                            adjustflag="3",
                        )
                        if rs.error_code != "0":
                            raise RuntimeError(f"query error {rs.error_code}: {rs.error_msg}")
                        ipo_date = listing_dates.get(code, "")
                        while rs.next():
                            row = rs.get_row_data()
                            if len(row) != 9:
                                continue
                            date, _, close, preclose, amount, turn, trade_status, pct, is_st = row
                            if trade_status != "1" or is_st == "1" or date == ipo_date:
                                continue
                            amount_v = backfill.safe_float(amount)
                            close_v = backfill.safe_float(close)
                            pct_v = backfill.safe_float(pct)
                            preclose_v = backfill.safe_float(preclose)
                            if (
                                amount_v is None or close_v is None or pct_v is None
                                or amount_v <= 0 or close_v <= 0
                                or preclose_v is None or preclose_v <= 0
                            ):
                                continue
                            turn_v = backfill.safe_float(turn)
                            writer.writerow([date, code, pct_v / 100.0, amount_v, turn_v, exchange])
                            rows_written += 1
                        success = True
                        break
                    except Exception:
                        if retry < 2:
                            reconnect()
                if not success:
                    failures += 1
                if position % 100 == 0:
                    print(
                        f"worker={worker_id} {position}/{len(codes)} "
                        f"rows={rows_written} failures={failures}",
                        flush=True,
                    )
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    return str(out_path), rows_written, failures


backfill.prepare_universe = prepare_universe_stable
backfill.baostock_worker = robust_baostock_worker

if __name__ == "__main__":
    backfill.main()
