#!/usr/bin/env python3
"""Fetch Tencent index history and Beijing Stock Exchange supplement."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time

import akshare as ak
import pandas as pd

import run_market_snapshot_v2 as universe_source

DATA_DIR = Path("data")
CHOICE_CANDIDATES = ["800007.EI", "sz800007", "sh800007", "bj800007", "zs800007", "jj800007"]


def fetch_tx(symbol: str, start: str, end: str, attempts: int = 4) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            frame = ak.stock_zh_a_hist_tx(
                symbol=symbol,
                start_date=start,
                end_date=end,
                adjust="",
                timeout=35,
            )
            if frame is None or frame.empty:
                raise RuntimeError("empty history")
            return frame
        except Exception as exc:
            last_error = exc
            time.sleep(attempt * 0.8)
    assert last_error is not None
    raise last_error


def index_history(symbol: str, name: str, start: str, end: str) -> pd.DataFrame:
    frame = fetch_tx(symbol, start, end).copy()
    frame["日期"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["收盘"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["成交额_亿元"] = pd.to_numeric(frame["amount"], errors="coerce") / 1e8
    frame["涨跌幅"] = frame["收盘"].pct_change(fill_method=None)
    frame["指标"] = name
    frame["供应商代码"] = symbol
    return frame[["日期", "指标", "供应商代码", "收盘", "涨跌幅", "成交额_亿元"]].dropna(subset=["日期", "收盘"])


def fetch_bj_one(row: dict[str, str], start: str, end: str) -> pd.DataFrame:
    code = str(row["股票代码"]).zfill(6)
    name = str(row["股票名称"])
    listing = pd.to_datetime(row["上市日期"], format="%Y%m%d", errors="coerce")
    if "ST" in name.upper():
        return pd.DataFrame()
    frame = fetch_tx(f"bj{code}", start, end).copy()
    frame["日期"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["收盘价"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["成交量"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame["成交额"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame["换手率"] = pd.to_numeric(frame["turnover"], errors="coerce")
    frame["昨收价"] = frame["收盘价"].shift(1)
    frame["涨跌幅"] = frame["收盘价"] / frame["昨收价"] - 1
    frame["股票代码"] = code
    frame["股票名称"] = name
    frame["上市日期"] = listing
    frame = frame[(frame["日期"] != listing) & (frame["成交额"] > 0) & (frame["成交量"] > 0)]
    return frame[["日期", "股票代码", "股票名称", "上市日期", "收盘价", "昨收价", "成交量", "成交额", "换手率", "涨跌幅"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="20260101")
    parser.add_argument("--end-date", default="20260803")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    DATA_DIR.mkdir(exist_ok=True)

    index_frames = []
    quality = []
    for symbol, name in [("sh000016", "上证50"), ("sh000985", "中证全指")]:
        try:
            frame = index_history(symbol, name, args.start_date, args.end_date)
            index_frames.append(frame)
            quality.append({"检查项": f"{name}腾讯历史", "数值": len(frame), "状态": "通过", "说明": symbol})
        except Exception as exc:
            quality.append({"检查项": f"{name}腾讯历史", "数值": 0, "状态": "失败", "说明": str(exc)})

    choice_success = None
    for candidate in CHOICE_CANDIDATES:
        try:
            frame = index_history(candidate, "Choice微盘股指数", args.start_date, args.end_date)
            if len(frame) >= 20:
                choice_success = candidate
                index_frames.append(frame)
                quality.append({"检查项": "Choice微盘腾讯历史", "数值": len(frame), "状态": "通过", "说明": candidate})
                break
        except Exception as exc:
            quality.append({"检查项": f"Choice候选{candidate}", "数值": 0, "状态": "提示", "说明": str(exc)})
    if choice_success is None:
        quality.append({"检查项": "Choice微盘腾讯历史", "数值": 0, "状态": "提示", "说明": "腾讯未识别候选代码"})

    if index_frames:
        pd.concat(index_frames, ignore_index=True).to_csv(
            DATA_DIR / "tx_index_history_2026.csv", index=False, encoding="utf-8-sig", float_format="%.8f"
        )

    universe = universe_source.fetch_stock_universe_official()
    bj_rows = universe[universe["股票代码"].astype(str).str.startswith(("4", "8", "9"))][
        ["股票代码", "股票名称", "上市日期"]
    ].to_dict("records")
    frames = []
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch_bj_one, row, args.start_date, args.end_date): row for row in bj_rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
            except Exception as exc:
                failures.append({"股票代码": row["股票代码"], "股票名称": row["股票名称"], "错误": str(exc)})
    bj = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not bj.empty:
        bj.sort_values(["日期", "股票代码"], inplace=True)
        bj.to_csv(DATA_DIR / "bj_stock_history_tx_2026.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    pd.DataFrame(failures).to_csv(DATA_DIR / "bj_stock_history_tx_errors_2026.csv", index=False, encoding="utf-8-sig")
    quality.append({"检查项": "北交所腾讯历史股票数", "数值": int(bj["股票代码"].nunique()) if not bj.empty else 0, "状态": "通过" if not bj.empty and bj["股票代码"].nunique() > 200 else "提示", "说明": f"失败={len(failures)}"})
    quality.append({"检查项": "北交所腾讯历史记录数", "数值": len(bj), "状态": "通过" if len(bj) > 20000 else "提示", "说明": f"{args.start_date}-{args.end_date}"})
    pd.DataFrame(quality).to_csv(DATA_DIR / "tx_index_bj_quality_2026.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
