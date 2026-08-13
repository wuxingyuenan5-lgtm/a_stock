#!/usr/bin/env python3
"""Fast daily Shenwan level-1/level-2 snapshot refresh.

Two bulk SWS realtime calls replace ~150 per-index history calls on the normal
daily path. Existing history remains the authoritative rolling cache; this
script only appends/upserts the target day and recomputes 20d volatility.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import akshare as ak
import pandas as pd

DATA_DIR = Path("data")
HISTORY_FILE = DATA_DIR / "sw_industry_history.csv"
LATEST_FILE = DATA_DIR / "sw_industry_latest.csv"
KEEP_HISTORY_ROWS = 260
VOL_WINDOW = 20
ANNUALIZATION_DAYS = 252
MIN_COVERAGE = 0.90

EXPORT_COLUMNS = {
    "date": "日期",
    "level": "行业层级",
    "level1_code": "一级行业代码",
    "level1_name": "一级行业",
    "index_code": "指数代码",
    "index_name": "指数名称",
    "close": "收盘价",
    "amount": "成交额",
    "daily_return": "日收益率",
    "volatility_20d": "20日年化波动率",
}
REVERSE_COLUMNS = {v: k for k, v in EXPORT_COLUMNS.items()}


def strip_suffix(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.split(".")[0]


def load_existing() -> pd.DataFrame:
    if not HISTORY_FILE.exists():
        raise RuntimeError("missing data/sw_industry_history.csv; run full bootstrap first")
    frame = pd.read_csv(HISTORY_FILE, encoding="utf-8-sig").rename(columns=REVERSE_COLUMNS)
    required = {
        "date", "level", "level1_code", "level1_name", "index_code",
        "index_name", "close", "amount",
    }
    if not required.issubset(frame.columns):
        raise RuntimeError(f"invalid Shenwan history columns: {list(frame.columns)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["index_code"] = frame["index_code"].map(strip_suffix)
    frame["level1_code"] = frame["level1_code"].map(strip_suffix)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    return frame.dropna(subset=["date", "index_code", "close"])


def fetch_bulk(symbol: str) -> pd.DataFrame:
    raw = ak.index_realtime_sw(symbol=symbol)
    required = {"指数代码", "指数名称", "昨收盘", "最新价", "成交额"}
    if raw is None or raw.empty or not required.issubset(raw.columns):
        raise RuntimeError(f"index_realtime_sw({symbol}) invalid: {list(raw.columns)}")
    out = raw.copy()
    out["index_code"] = out["指数代码"].map(strip_suffix)
    out["close"] = pd.to_numeric(out["最新价"], errors="coerce")
    out["prev_close"] = pd.to_numeric(out["昨收盘"], errors="coerce")
    # AKShare documents this realtime field in CNY million; workbook history uses CNY 100m.
    out["amount"] = pd.to_numeric(out["成交额"], errors="coerce") / 100.0
    return out[["index_code", "close", "prev_close", "amount"]].dropna(
        subset=["index_code", "close"]
    )


def calculate_metrics(data: pd.DataFrame) -> pd.DataFrame:
    data = (
        data.sort_values(["index_code", "date"])
        .drop_duplicates(["index_code", "date"], keep="last")
        .copy()
    )
    data["daily_return"] = data.groupby("index_code")["close"].pct_change(fill_method=None)
    data["volatility_20d"] = data.groupby("index_code")["daily_return"].transform(
        lambda s: s.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=1)
        * math.sqrt(ANNUALIZATION_DAYS)
    )
    return data.groupby("index_code", group_keys=False).tail(KEEP_HISTORY_ROWS)


def write_outputs(data: pd.DataFrame) -> None:
    columns = [
        "date", "level", "level1_code", "level1_name", "index_code",
        "index_name", "close", "amount", "daily_return", "volatility_20d",
    ]
    exported = data[columns].sort_values(
        ["date", "level", "level1_name", "index_name"]
    ).rename(columns=EXPORT_COLUMNS)
    exported["日期"] = pd.to_datetime(exported["日期"]).dt.strftime("%Y-%m-%d")
    exported.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig", float_format="%.8f")

    latest = (
        data.sort_values("date")
        .groupby("index_code", as_index=False, group_keys=False)
        .tail(1)[columns]
        .sort_values(["level", "level1_name", "index_name"])
        .rename(columns=EXPORT_COLUMNS)
    )
    latest["日期"] = pd.to_datetime(latest["日期"]).dt.strftime("%Y-%m-%d")
    latest.to_csv(LATEST_FILE, index=False, encoding="utf-8-sig", float_format="%.8f")


def update(target_date: str) -> dict[str, object]:
    existing = load_existing()
    metadata = (
        existing.sort_values("date")
        .groupby("index_code", as_index=False, group_keys=False)
        .tail(1)[["level", "level1_code", "level1_name", "index_code", "index_name"]]
        .drop_duplicates("index_code")
    )
    if metadata.empty:
        raise RuntimeError("Shenwan metadata cache is empty")

    live = pd.concat(
        [fetch_bulk("一级行业"), fetch_bulk("二级行业")],
        ignore_index=True,
    ).drop_duplicates("index_code", keep="last")

    fresh = metadata.merge(live, on="index_code", how="inner")
    coverage = len(fresh) / len(metadata)
    if coverage < MIN_COVERAGE:
        raise RuntimeError(
            f"Shenwan bulk realtime coverage too low: {len(fresh)}/{len(metadata)}={coverage:.1%}"
        )

    fresh["date"] = pd.Timestamp(target_date)
    fresh = fresh[
        [
            "date", "level", "level1_code", "level1_name", "index_code",
            "index_name", "close", "amount",
        ]
    ]

    base = existing[
        [
            "date", "level", "level1_code", "level1_name", "index_code",
            "index_name", "close", "amount",
        ]
    ]
    combined = pd.concat([base, fresh], ignore_index=True)
    data = calculate_metrics(combined)
    write_outputs(data)

    target_rows = int((pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d") == target_date).sum())
    result = {
        "mode": "bulk_realtime_incremental",
        "target_date": target_date,
        "cached_indices": int(len(metadata)),
        "updated_indices": int(len(fresh)),
        "coverage": round(coverage, 6),
        "target_date_rows": target_rows,
    }
    print(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast daily Shenwan industry refresh")
    parser.add_argument("--target-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    update(args.target_date)


if __name__ == "__main__":
    main()
