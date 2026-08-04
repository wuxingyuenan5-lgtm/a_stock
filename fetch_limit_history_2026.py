#!/usr/bin/env python3
"""Fetch 2026 historical limit-up/down counts from Eastmoney pools.

The date grid is read from the existing market breadth history so non-trading
calendar dates are never invented. ST names are excluded. Failed dates remain
blank and are reported explicitly; they are never forward-filled or estimated.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import time

import akshare as ak
import pandas as pd

DATA_DIR = Path("data")


def count_pool(fetcher, date_text: str) -> tuple[int | None, str]:
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            frame = fetcher(date=date_text)
            if frame is None:
                raise RuntimeError("returned None")
            if frame.empty:
                return 0, "empty pool"
            name_col = next((c for c in ["名称", "股票名称"] if c in frame.columns), None)
            if name_col:
                names = frame[name_col].astype(str).str.upper()
                frame = frame[~names.str.contains("ST", na=False)]
            code_col = next((c for c in ["代码", "股票代码"] if c in frame.columns), None)
            count = int(frame[code_col].astype(str).nunique()) if code_col else int(len(frame))
            return count, "ok"
        except Exception as exc:
            last_error = exc
            time.sleep(0.8 * attempt)
    return None, str(last_error)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="20260101")
    parser.add_argument("--end-date", default="20260804")
    args = parser.parse_args()

    source = DATA_DIR / "market_daily_history_backfilled.csv"
    if not source.exists():
        source = DATA_DIR / "market_daily_history.csv"
    frame = pd.read_csv(source, encoding="utf-8-sig")
    frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
    start = pd.to_datetime(args.start_date, format="%Y%m%d")
    end = pd.to_datetime(args.end_date, format="%Y%m%d")
    dates = frame.loc[frame["日期"].between(start, end), "日期"].dropna().drop_duplicates().sort_values()

    records = []
    for position, date in enumerate(dates, start=1):
        text = date.strftime("%Y%m%d")
        up, up_status = count_pool(ak.stock_zt_pool_em, text)
        down, down_status = count_pool(ak.stock_zt_pool_dtgc_em, text)
        records.append({
            "日期": date.strftime("%Y-%m-%d"),
            "涨停家数": up,
            "跌停家数": down,
            "涨停状态": up_status,
            "跌停状态": down_status,
        })
        print(f"[{position}/{len(dates)}] {text}: up={up} down={down}", flush=True)
        time.sleep(0.12)

    out = pd.DataFrame(records)
    DATA_DIR.mkdir(exist_ok=True)
    out.to_csv(DATA_DIR / "limit_history_2026.csv", index=False, encoding="utf-8-sig")
    failed = out[out[["涨停家数", "跌停家数"]].isna().any(axis=1)]
    quality = pd.DataFrame([
        {"检查项":"交易日数量","数值":len(out),"状态":"通过","说明":f"{args.start_date}-{args.end_date}"},
        {"检查项":"完整涨跌停日期数","数值":int(out[["涨停家数","跌停家数"]].notna().all(axis=1).sum()),"状态":"通过" if failed.empty else "提示","说明":f"失败={len(failed)}"},
        {"检查项":"ST过滤","数值":"名称包含ST排除","状态":"通过","说明":"保持日报统一口径"},
    ])
    quality.to_csv(DATA_DIR / "limit_history_quality_2026.csv", index=False, encoding="utf-8-sig")
    if not failed.empty:
        failed.to_csv(DATA_DIR / "limit_history_errors_2026.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
