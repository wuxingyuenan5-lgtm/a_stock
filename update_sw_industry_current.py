#!/usr/bin/env python3
"""Build an exact-date Shenwan L1/L2 snapshot from official current/daily APIs.

The historical trend endpoint can publish later than the current quote endpoint.
This script therefore uses:
- index_realtime_sw for target-day close and turnover;
- index_analysis_daily_sw to backfill recent closes;
- index_min_sw to validate the actual trading date;
- existing index_hist_sw history only as the long rolling base.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
import math
from pathlib import Path

import akshare as ak
import pandas as pd

import update_sw_industry as base

BEIJING = timezone(timedelta(hours=8))
DATA_DIR = Path("data")
VOL_WINDOW = 20
ANNUALIZATION_DAYS = 252


def normalize_code(value: object) -> str:
    return str(value).strip().split(".")[0].replace(".0", "")


def fetch_recent_analysis(start_date: str, target_date: str) -> pd.DataFrame:
    """Fetch official Shenwan daily analysis closes for both industry levels."""
    frames: list[pd.DataFrame] = []
    for level in ("一级行业", "二级行业"):
        raw = base.retry(
            lambda level=level: ak.index_analysis_daily_sw(
                symbol=level, start_date=start_date, end_date=target_date
            )
        )
        required = {"指数代码", "发布日期", "收盘指数"}
        if raw.empty or not required.issubset(raw.columns):
            raise RuntimeError(f"申万{level}日报字段异常: {list(raw.columns)}")
        frame = raw[["指数代码", "发布日期", "收盘指数"]].copy()
        frame.columns = ["index_code", "date", "close"]
        frame["index_code"] = frame["index_code"].map(normalize_code)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frames.append(frame.dropna(subset=["date", "close"]))
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        ["index_code", "date"], keep="last"
    )


def fetch_realtime(universe: pd.DataFrame) -> pd.DataFrame:
    """Fetch official current quotes; AKShare documents turnover in million yuan."""
    frames: list[pd.DataFrame] = []
    for level in ("一级行业", "二级行业"):
        raw = base.retry(lambda level=level: ak.index_realtime_sw(symbol=level))
        required = {"指数代码", "指数名称", "昨收盘", "最新价", "成交额"}
        if raw.empty or not required.issubset(raw.columns):
            raise RuntimeError(f"申万{level}实时行情字段异常: {list(raw.columns)}")
        frame = raw[["指数代码", "指数名称", "昨收盘", "最新价", "成交额"]].copy()
        frame.columns = ["index_code", "vendor_name", "previous_close", "close", "amount_million"]
        frame["index_code"] = frame["index_code"].map(normalize_code)
        for column in ("previous_close", "close", "amount_million"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frames.append(frame)
    realtime = pd.concat(frames, ignore_index=True).drop_duplicates("index_code", keep="last")
    realtime = realtime.merge(
        universe[["level", "level1_code", "level1_name", "index_code", "index_name"]],
        on="index_code",
        how="inner",
    )
    realtime["amount"] = realtime["amount_million"] / 100.0
    return realtime


def validate_trading_date(target_date: str, representative_code: str) -> None:
    """Use the official minute endpoint to prove the quote belongs to target_date."""
    raw = base.retry(lambda: ak.index_min_sw(symbol=representative_code))
    if raw.empty or "日期" not in raw.columns:
        raise RuntimeError("申万分时接口为空，无法验证实时行情日期")
    latest = pd.to_datetime(raw["日期"], errors="coerce").dropna().max()
    if pd.isna(latest):
        raise RuntimeError("申万分时接口未返回有效交易日期")
    actual = latest.strftime("%Y%m%d")
    if actual != target_date:
        raise RuntimeError(f"申万实时行情日期为 {actual}，目标日为 {target_date}")


def load_existing_history() -> pd.DataFrame:
    if not base.HISTORY_FILE.exists():
        return pd.DataFrame(columns=["date", "index_code", "close"])
    raw = pd.read_csv(base.HISTORY_FILE, encoding="utf-8-sig")
    required = {"日期", "指数代码", "收盘价"}
    if not required.issubset(raw.columns):
        raise RuntimeError(f"申万历史底表字段异常: {list(raw.columns)}")
    frame = raw[["日期", "指数代码", "收盘价"]].copy()
    frame.columns = ["date", "index_code", "close"]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["index_code"] = frame["index_code"].map(normalize_code)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["date", "close"])


def build_current(target_date: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    universe = base.load_universe().copy()
    universe["index_code"] = universe["index_code"].map(normalize_code)
    representative = str(universe.iloc[0]["index_code"])
    validate_trading_date(target_date, representative)

    target_dt = datetime.strptime(target_date, "%Y%m%d")
    analysis_start = (target_dt - timedelta(days=15)).strftime("%Y%m%d")
    analysis = fetch_recent_analysis(analysis_start, target_date)
    realtime = fetch_realtime(universe)

    target_day = pd.Timestamp(target_dt.date())
    current_close = realtime[["index_code", "close"]].copy()
    current_close["date"] = target_day
    existing = load_existing_history()
    combined = pd.concat(
        [existing[["date", "index_code", "close"]], analysis, current_close],
        ignore_index=True,
    )
    combined = combined.dropna(subset=["date", "index_code", "close"])
    combined = combined.sort_values(["index_code", "date"]).drop_duplicates(
        ["index_code", "date"], keep="last"
    )
    combined["daily_return"] = combined.groupby("index_code")["close"].pct_change(
        fill_method=None
    )
    combined["volatility_20d"] = combined.groupby("index_code")["daily_return"].transform(
        lambda series: series.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=1)
        * math.sqrt(ANNUALIZATION_DAYS)
    )

    target_metrics = combined[combined["date"].eq(target_day)][
        ["index_code", "daily_return", "volatility_20d"]
    ]
    output = realtime.merge(target_metrics, on="index_code", how="left")
    output["date"] = target_day
    output["source"] = "申万官方实时行情+日报回补+历史趋势"
    output["date_status"] = "目标日已由分时接口验证"
    output = output[
        [
            "date", "level", "level1_code", "level1_name", "index_code", "index_name",
            "close", "amount", "daily_return", "volatility_20d", "source", "date_status",
        ]
    ].sort_values(["level", "level1_name", "index_name"])

    target_analysis_count = int(
        analysis[analysis["date"].dt.strftime("%Y%m%d").eq(target_date)]["index_code"].nunique()
    )
    quality = pd.DataFrame(
        [
            {"检查项": "申万实时行情指数数", "数值": len(output), "状态": "通过" if len(output) > 100 else "失败", "说明": "一级和二级行业合计"},
            {"检查项": "目标日分时日期验证", "数值": target_date, "状态": "通过", "说明": representative},
            {"检查项": "目标日日报覆盖指数数", "数值": target_analysis_count, "状态": "通过" if target_analysis_count > 100 else "提示", "说明": "日报用于最近收盘回补"},
            {"检查项": "20日波动率非空指数数", "数值": int(output["volatility_20d"].notna().sum()), "状态": "通过", "说明": "20个日收益率，样本标准差×sqrt(252)"},
            {"检查项": "成交额单位", "数值": "亿元", "状态": "通过", "说明": "实时接口百万元÷100"},
        ]
    )
    return output, combined, quality


def write_outputs(target_date: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current, history, quality = build_current(target_date)
    export = current.rename(
        columns={
            "date": "日期",
            "level": "行业层级",
            "level1_code": "一级行业代码",
            "level1_name": "一级行业",
            "index_code": "指数代码",
            "index_name": "指数名称",
            "close": "收盘价",
            "amount": "成交额_亿元",
            "daily_return": "日收益率",
            "volatility_20d": "20日年化波动率",
            "source": "数据来源",
            "date_status": "日期状态",
        }
    )
    export["日期"] = export["日期"].dt.strftime("%Y-%m-%d")
    export.to_csv(
        DATA_DIR / f"sw_industry_current_{target_date}.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8f",
    )
    history.to_csv(
        DATA_DIR / f"sw_industry_enhanced_history_{target_date}.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8f",
    )
    quality.to_csv(
        DATA_DIR / f"sw_industry_current_quality_{target_date}.csv",
        index=False,
        encoding="utf-8-sig",
    )
    logging.info("申万目标日快照完成: %s, 指数 %s", target_date, len(export))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="申万一级/二级行业目标日实时快照")
    parser.add_argument(
        "--target-date",
        default=datetime.now(BEIJING).strftime("%Y%m%d"),
        help="YYYYMMDD",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    write_outputs(args.target_date)


if __name__ == "__main__":
    main()
