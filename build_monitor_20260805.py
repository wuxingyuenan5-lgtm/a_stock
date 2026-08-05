#!/usr/bin/env python3
"""One-off data build for the A-share monitor workbook dated 2026-08-05.

Outputs source CSV files only. Workbook formatting remains in ChatGPT/artifact_tool.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import logging
from pathlib import Path
import time
from typing import Any

import pandas as pd
import requests

OUT_DIR = Path("data/monitor_20260805")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36"


def request_json(urls: list[str], params: dict[str, Any], attempts: int = 4) -> dict[str, Any]:
    last: Exception | None = None
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    for attempt in range(attempts):
        for url in urls:
            try:
                response = requests.get(url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last = exc
        time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"request failed: {last}")


def fetch_a_share_snapshot(target_date: str) -> pd.DataFrame:
    urls = [
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        "https://56.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
    ]
    params = {
        "pn": 1,
        "pz": 6000,
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f2,f3,f5,f6,f8,f12,f13,f14,f18,f20,f21,f23,f100,f124",
    }
    payload = request_json(urls, params)
    diff = ((payload.get("data") or {}).get("diff") or [])
    if not diff:
        raise RuntimeError("Eastmoney A-share snapshot returned no rows")
    frame = pd.DataFrame(diff).rename(
        columns={
            "f12": "股票代码",
            "f14": "股票名称",
            "f2": "收盘价",
            "f3": "涨跌幅_pct",
            "f6": "成交额_元",
            "f5": "成交量",
            "f8": "换手率_pct",
            "f18": "昨收",
            "f20": "总市值_元",
            "f21": "流通市值_元",
            "f23": "市净率",
            "f100": "东方财富行业",
            "f124": "行情时间戳",
            "f13": "市场标识",
        }
    )
    frame["股票代码"] = frame["股票代码"].astype(str).str.zfill(6)
    frame["股票名称"] = frame["股票名称"].astype(str).str.strip()
    for col in ["收盘价", "涨跌幅_pct", "成交额_元", "成交量", "换手率_pct", "昨收", "总市值_元", "流通市值_元"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["日期"] = pd.to_datetime(pd.to_numeric(frame["行情时间戳"], errors="coerce"), unit="s", errors="coerce").dt.strftime("%Y-%m-%d")
    expected = datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d")
    observed = sorted(set(frame["日期"].dropna().tolist()))
    if observed and expected not in observed:
        raise RuntimeError(f"snapshot date mismatch: expected {expected}, observed tail {observed[-3:]}")
    # Match the workbook's effective universe: traded A shares, excluding ST and listing-day N shares.
    frame = frame[
        frame["成交额_元"].fillna(0).gt(0)
        & ~frame["股票名称"].str.contains("ST", case=False, na=False)
        & ~frame["股票名称"].str.startswith("N", na=False)
    ].copy()
    frame["涨跌幅"] = frame["涨跌幅_pct"] / 100.0
    frame["成交额（亿元）"] = frame["成交额_元"] / 1e8
    frame.sort_values(["成交额_元", "股票代码"], ascending=[False, True], inplace=True)
    return frame


def fetch_kline(secid: str, name: str, start_date: str, end_date: str) -> pd.DataFrame:
    urls = [
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "https://33.push2his.eastmoney.com/api/qt/stock/kline/get",
    ]
    params = {
        "secid": secid,
        "klt": 101,
        "fqt": 0,
        "lmt": 10000,
        "beg": start_date,
        "end": end_date,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    payload = request_json(urls, params)
    klines = ((payload.get("data") or {}).get("klines") or [])
    rows: list[dict[str, Any]] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 11:
            continue
        rows.append(
            {
                "日期": parts[0],
                "指标": name,
                "开盘": float(parts[1]),
                "收盘": float(parts[2]),
                "最高": float(parts[3]),
                "最低": float(parts[4]),
                "成交量": float(parts[5]),
                "成交额（亿元）": float(parts[6]) / 1e8,
                "涨跌幅": float(parts[8]) / 100.0,
                "换手率": float(parts[10]) / 100.0,
                "数据代码": secid,
            }
        )
    return pd.DataFrame(rows)


def fetch_limit_counts(dates: list[str]) -> pd.DataFrame:
    import akshare as ak

    records = []
    for date in dates:
        row: dict[str, Any] = {"日期": datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")}
        for key, fn in [("涨停家数", ak.stock_zt_pool_em), ("跌停家数", ak.stock_zt_pool_dtgc_em)]:
            error = None
            value = None
            for attempt in range(4):
                try:
                    data = fn(date=date)
                    value = int(len(data))
                    break
                except Exception as exc:
                    error = str(exc)
                    time.sleep(1.5 * (attempt + 1))
            row[key] = value
            if error and value is None:
                row[f"{key}错误"] = error
        records.append(row)
    return pd.DataFrame(records)


def build_historical_100bn(start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute daily turnover >= RMB10bn with BaoStock historical daily bars."""
    import baostock as bs

    start_iso = datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d")
    end_iso = datetime.strptime(end_date, "%Y%m%d").strftime("%Y-%m-%d")
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_msg}")
    try:
        universe_rs = bs.query_all_stock(day=end_iso)
        codes: list[str] = []
        while universe_rs.error_code == "0" and universe_rs.next():
            row = universe_rs.get_row_data()
            if row and (row[0].startswith("sh.") or row[0].startswith("sz.")):
                codes.append(row[0])
        details: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        total = len(codes)
        for i, code in enumerate(codes, start=1):
            rs = bs.query_history_k_data_plus(
                code,
                "date,code,close,pctChg,amount,tradestatus,isST",
                start_date=start_iso,
                end_date=end_iso,
                frequency="d",
                adjustflag="3",
            )
            if rs.error_code != "0":
                failures.append({"代码": code, "错误": rs.error_msg})
                continue
            while rs.next():
                date, bs_code, close, pct, amount, status, is_st = rs.get_row_data()
                try:
                    amount_f = float(amount or 0)
                    pct_f = float(pct or 0) / 100.0
                    close_f = float(close or 0)
                except ValueError:
                    continue
                if status == "1" and is_st != "1" and amount_f >= 10_000_000_000:
                    details.append(
                        {
                            "日期": date,
                            "股票代码": bs_code.split(".")[-1],
                            "收盘价": close_f,
                            "涨跌幅": pct_f,
                            "成交额（亿元）": amount_f / 1e8,
                            "数据来源": "BaoStock日线",
                        }
                    )
            if i % 500 == 0 or i == total:
                logging.info("BaoStock progress %s/%s, hot rows %s", i, total, len(details))
        detail_df = pd.DataFrame(details)
        if detail_df.empty:
            summary_df = pd.DataFrame(columns=["日期", "百亿成交股数", "百亿成交额（亿元）"])
        else:
            summary_df = (
                detail_df.groupby("日期", as_index=False)
                .agg(百亿成交股数=("股票代码", "count"), 百亿成交额_亿元=("成交额（亿元）", "sum"))
                .rename(columns={"百亿成交额_亿元": "百亿成交额（亿元）"})
                .sort_values("日期")
            )
            detail_df.sort_values(["日期", "成交额（亿元）"], ascending=[True, False], inplace=True)
        return summary_df, detail_df, pd.DataFrame(failures)
    finally:
        bs.logout()


def write_csv(df: pd.DataFrame, filename: str) -> None:
    df.to_csv(OUT_DIR / filename, index=False, encoding="utf-8-sig", float_format="%.10f")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", default="20260805")
    parser.add_argument("--history-start", default="20260105")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    snapshot = fetch_a_share_snapshot(args.target_date)
    hot = snapshot[snapshot["成交额_元"] >= 10_000_000_000].copy()
    hot.insert(0, "当日排名", range(1, len(hot) + 1))

    up_count = int((snapshot["涨跌幅"] > 0).sum())
    down_count = int((snapshot["涨跌幅"] < 0).sum())
    flat_count = int((snapshot["涨跌幅"] == 0).sum())
    market_amount = float(snapshot["成交额_元"].sum() / 1e8)

    limit_today = fetch_limit_counts([args.target_date])
    limit_up = limit_today.iloc[0].get("涨停家数") if not limit_today.empty else None
    limit_down = limit_today.iloc[0].get("跌停家数") if not limit_today.empty else None

    summary = pd.DataFrame([
        {
            "日期": datetime.strptime(args.target_date, "%Y%m%d").strftime("%Y-%m-%d"),
            "上涨家数": up_count,
            "下跌家数": down_count,
            "平盘家数": flat_count,
            "涨停家数": limit_up,
            "跌停家数": limit_down,
            "有效股票数": len(snapshot),
            "全部A股成交额（亿元）": market_amount,
            "百亿成交股数": len(hot),
            "百亿成交额（亿元）": float(hot["成交额（亿元）"].sum()),
            "百亿成交集中度": float(hot["成交额（亿元）"].sum()) / market_amount if market_amount else None,
            "数据源": "东方财富全A收盘快照+涨跌停池",
        }
    ])

    index_frames = [
        fetch_kline("1.000016", "上证50", "20260801", args.target_date),
        fetch_kline("1.000985", "中证全指", "20260801", args.target_date),
        fetch_kline("47.800007", "Choice微盘", args.history_start, args.target_date),
    ]
    indexes = pd.concat(index_frames, ignore_index=True)

    early_dates = ["20260105", "20260106", "20260107", "20260108", "20260109", "20260112", "20260113", "20260114", "20260115", "20260116", "20260119", "20260120"]
    early_limits = fetch_limit_counts(early_dates)

    history_summary, history_details, history_failures = build_historical_100bn(args.history_start, args.target_date)

    write_csv(summary, "market_summary_20260805.csv")
    write_csv(snapshot, "all_a_snapshot_20260805.csv")
    write_csv(hot, "turnover_100bn_stocks_20260805.csv")
    write_csv(indexes, "index_history_to_20260805.csv")
    write_csv(early_limits, "early_limit_counts_20260105_20260120.csv")
    write_csv(history_summary, "history_100bn_daily_20260105_20260805.csv")
    write_csv(history_details, "history_100bn_details_20260105_20260805.csv")
    if not history_failures.empty:
        write_csv(history_failures, "history_100bn_failures.csv")

    metadata = {
        "built_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "target_date": args.target_date,
        "snapshot_rows": len(snapshot),
        "hot_rows": len(hot),
        "history_hot_rows": len(history_details),
        "history_failures": len(history_failures),
    }
    (OUT_DIR / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("completed: %s", metadata)


if __name__ == "__main__":
    main()
