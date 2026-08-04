#!/usr/bin/env python3
"""Robust unified history rebuild: periodic BaoStock reconnect + curl-cffi Eastmoney."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import time

import pandas as pd
from curl_cffi import requests as curl_requests

import rebuild_daily_core_history as core
from run_market_snapshot_v2 import fetch_stock_universe_official

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def prepare_universe_official() -> tuple[pd.DataFrame, dict[str, str]]:
    universe = fetch_stock_universe_official().copy()
    universe["股票代码"] = universe["股票代码"].map(core.normalize_code)
    universe["上市日期"] = pd.to_datetime(
        universe["上市日期"], format="%Y%m%d", errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    universe["上市日期"] = universe["上市日期"].fillna("")
    listing_dates = dict(zip(universe["股票代码"], universe["上市日期"]))
    return universe.drop_duplicates("股票代码"), listing_dates


def reconnect(bs) -> None:
    try:
        bs.logout()
    except Exception:
        pass
    last_error = None
    for attempt in range(1, 6):
        try:
            result = bs.login()
            if result.error_code == "0":
                return
            last_error = RuntimeError(f"{result.error_code} {result.error_msg}")
        except Exception as exc:
            last_error = exc
        time.sleep(attempt * 0.8)
    raise RuntimeError(f"BaoStock reconnect failed: {last_error}")


def robust_baostock_worker(
    worker_id: int,
    codes: list[str],
    start_date: str,
    end_date: str,
    listing_dates: dict[str, str],
    output_dir: str,
) -> tuple[str, int, int]:
    import baostock as bs

    out_path = Path(output_dir) / f"daily_part_{worker_id:02d}.csv"
    failures = 0
    rows_written = 0
    reconnect(bs)
    try:
        with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "日期", "股票代码", "收盘价", "昨收价", "成交量", "成交额",
                "换手率", "涨跌幅", "交易所", "上市日期",
            ])
            for position, code in enumerate(codes, start=1):
                if position > 1 and (position - 1) % 120 == 0:
                    reconnect(bs)
                exchange = core.infer_exchange(code)
                bs_code = f"{exchange}.{code}"
                stock_rows: list[list[object]] | None = None
                for attempt in range(1, 4):
                    try:
                        rs = bs.query_history_k_data_plus(
                            bs_code,
                            "date,code,close,preclose,volume,amount,turn,tradestatus,pctChg,isST",
                            start_date=start_date,
                            end_date=end_date,
                            frequency="d",
                            adjustflag="3",
                        )
                        if rs.error_code != "0":
                            raise RuntimeError(f"query error {rs.error_code} {rs.error_msg}")
                        ipo_date = listing_dates.get(code, "")
                        candidate: list[list[object]] = []
                        while rs.next():
                            row = rs.get_row_data()
                            if len(row) != 10:
                                continue
                            date, _, close, preclose, volume, amount, turn, trade_status, pct, is_st = row
                            if trade_status != "1" or is_st == "1" or date == ipo_date:
                                continue
                            close_v = core.safe_float(close)
                            preclose_v = core.safe_float(preclose)
                            volume_v = core.safe_float(volume)
                            amount_v = core.safe_float(amount)
                            pct_v = core.safe_float(pct)
                            turn_v = core.safe_float(turn)
                            if (
                                close_v is None or preclose_v is None or volume_v is None
                                or amount_v is None or pct_v is None or close_v <= 0
                                or preclose_v <= 0 or volume_v <= 0 or amount_v <= 0
                            ):
                                continue
                            candidate.append([
                                date, code, close_v, preclose_v, volume_v, amount_v,
                                turn_v / 100.0 if turn_v is not None else None,
                                pct_v / 100.0, exchange, ipo_date,
                            ])
                        stock_rows = candidate
                        break
                    except Exception:
                        if attempt < 3:
                            reconnect(bs)
                            time.sleep(attempt * 0.5)
                if stock_rows is None:
                    failures += 1
                else:
                    writer.writerows(stock_rows)
                    rows_written += len(stock_rows)
                if position % 100 == 0:
                    print(
                        f"worker={worker_id} {position}/{len(codes)} rows={rows_written} failures={failures}",
                        flush=True,
                    )
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    return str(out_path), rows_written, failures


def robust_fetch_em_kline(secid: str, start_date: str, end_date: str) -> pd.DataFrame:
    hosts = [
        "https://push2his.eastmoney.com",
        "https://33.push2his.eastmoney.com",
        "https://54.push2his.eastmoney.com",
        "https://push2delay.eastmoney.com",
    ]
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "beg": start_date.replace("-", ""),
        "end": end_date.replace("-", ""),
        "lmt": "100000",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    errors: list[str] = []
    for host in hosts:
        for attempt in range(1, 4):
            try:
                response = curl_requests.get(
                    f"{host}/api/qt/stock/kline/get",
                    params=params,
                    headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
                    impersonate="chrome",
                    timeout=30,
                    verify=False,
                )
                response.raise_for_status()
                payload = response.json()
                rows = (payload.get("data") or {}).get("klines") or []
                if not rows:
                    raise RuntimeError("empty klines")
                parsed = [line.split(",") for line in rows]
                columns = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
                frame = pd.DataFrame(parsed, columns=columns)
                frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
                for column in columns[1:]:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
                return frame.dropna(subset=["日期", "收盘"]).sort_values("日期").reset_index(drop=True)
            except Exception as exc:
                errors.append(f"{host}#{attempt}:{exc}")
                time.sleep(attempt * 0.8)
    raise RuntimeError(f"Kline failed {secid}: {' | '.join(errors)}")


def robust_fetch_bj_one(row: dict[str, str], start_date: str, end_date: str) -> list[list[object]]:
    code = row["股票代码"]
    if "ST" in row["股票名称"].upper():
        return []
    frame = robust_fetch_em_kline(f"0.{code}", start_date, end_date)
    ipo_date = row["上市日期"]
    records: list[list[object]] = []
    previous_close = None
    for _, item in frame.iterrows():
        date = item["日期"].strftime("%Y-%m-%d")
        close = core.safe_float(item["收盘"])
        volume_lots = core.safe_float(item["成交量"])
        amount = core.safe_float(item["成交额"])
        pct = core.safe_float(item["涨跌幅"])
        turn = core.safe_float(item["换手率"])
        preclose = previous_close
        previous_close = close
        if date == ipo_date or close is None or volume_lots is None or amount is None or pct is None:
            continue
        if preclose is None:
            preclose = close / (1.0 + pct / 100.0) if abs(1.0 + pct / 100.0) > 1e-12 else None
        if close <= 0 or volume_lots <= 0 or amount <= 0 or preclose is None or preclose <= 0:
            continue
        records.append([
            date, code, close, preclose, volume_lots * 100.0, amount,
            turn / 100.0 if turn is not None else None,
            pct / 100.0, "bj", ipo_date,
        ])
    return records


core.prepare_universe = prepare_universe_official
core.baostock_worker = robust_baostock_worker
core.fetch_em_kline = robust_fetch_em_kline
core.fetch_bj_one = robust_fetch_bj_one

if __name__ == "__main__":
    core.main()
