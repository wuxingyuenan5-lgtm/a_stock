#!/usr/bin/env python3
"""Download data for the four-bank MA20 portfolio backtest.

Execution and valuation prices are unadjusted. Price history is downloaded from
Tencent in bounded two-year chunks. Corporate actions are downloaded separately
through AKShare so the backtest can account for dividends and share distributions
explicitly.

A small number of source rows can violate basic OHLC bounds. The raw high/low are
preserved and the usable high/low are deterministically repaired to the extrema of
open, close, raw high and raw low. Every repaired row is explicitly flagged.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Callable, TypeVar

import akshare as ak
import pandas as pd
import requests

DATA_DIR = Path("data/four_bank_ma20")
DEFAULT_START_DATE = "2011-01-01"
MIN_EXPECTED_ROWS = 1000
MAX_SOURCE_STALENESS_DAYS = 20
MAX_REPAIRED_OHLC_ROWS = 10
TENCENT_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

SECURITIES: dict[str, dict[str, str]] = {
    "sh.000001": {
        "provider_symbol": "sh000001",
        "symbol": "000001",
        "name": "上证指数",
        "asset_type": "index",
    },
    "sh.601988": {
        "provider_symbol": "sh601988",
        "symbol": "601988",
        "name": "中国银行",
        "asset_type": "stock",
    },
    "sh.601398": {
        "provider_symbol": "sh601398",
        "symbol": "601398",
        "name": "工商银行",
        "asset_type": "stock",
    },
    "sh.601939": {
        "provider_symbol": "sh601939",
        "symbol": "601939",
        "name": "建设银行",
        "asset_type": "stock",
    },
    "sh.601288": {
        "provider_symbol": "sh601288",
        "symbol": "601288",
        "name": "农业银行",
        "asset_type": "stock",
    },
}

PRICE_COLUMNS = [
    "date",
    "code",
    "symbol",
    "name",
    "asset_type",
    "open",
    "high",
    "low",
    "close",
    "high_raw",
    "low_raw",
    "quality_flag",
    "preclose",
    "volume_raw",
    "amount",
    "amplitude_pct",
    "turnover_pct",
    "trade_status",
    "pct_change_pct",
    "change",
    "is_st",
    "adjustment",
    "source",
]

CORPORATE_ACTION_COLUMNS = [
    "code",
    "symbol",
    "name",
    "report_date",
    "pre_notice_date",
    "implementation_announcement_date",
    "record_date",
    "ex_date",
    "payment_date",
    "stock_listing_date",
    "cash_before_tax_per_share",
    "cash_after_tax_per_share_raw",
    "stock_dividend_per_share",
    "capitalisation_issue_per_share",
    "plan_status",
    "plan_description",
    "source",
]

T = TypeVar("T")


def retry(call: Callable[[], T], attempts: int = 4, delay: float = 1.5) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == attempts:
                break
            logging.warning("请求失败，第 %s/%s 次重试: %s", attempt, attempts, exc)
            time.sleep(delay * attempt)
    assert last_error is not None
    raise last_error


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def column_or_na(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series(pd.NA, index=frame.index, dtype="object")


def request_tencent_chunk(
    provider_symbol: str,
    start_date: date,
    end_date: date,
) -> list[list[str]]:
    params = {
        "param": (
            f"{provider_symbol},day,{start_date.isoformat()},"
            f"{end_date.isoformat()},640,"
        ),
        "r": f"0.{time.time_ns()}",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Referer": "https://gu.qq.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    response = requests.get(
        TENCENT_ENDPOINT,
        params=params,
        headers=headers,
        timeout=(10, 45),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"腾讯行情接口错误: {payload.get('code')} {payload.get('msg')}")

    data = payload.get("data")
    security_data = data.get(provider_symbol) if isinstance(data, dict) else None
    rows = security_data.get("day") if isinstance(security_data, dict) else None
    if not rows:
        keys = sorted(security_data.keys()) if isinstance(security_data, dict) else []
        raise RuntimeError(
            f"腾讯行情返回空数据: {provider_symbol} "
            f"{start_date}~{end_date}; keys={keys}"
        )
    return [[str(value) for value in row] for row in rows]


def fetch_price(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    metadata = SECURITIES[code]
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    all_rows: list[list[str]] = []

    chunk_start_year = start.year
    while chunk_start_year <= end.year:
        chunk_start = max(start, date(chunk_start_year, 1, 1))
        chunk_end = min(end, date(chunk_start_year + 1, 12, 31))
        logging.info(
            "下载 %s: %s ~ %s",
            metadata["name"],
            chunk_start,
            chunk_end,
        )
        rows = retry(
            lambda chunk_start=chunk_start, chunk_end=chunk_end: request_tencent_chunk(
                metadata["provider_symbol"],
                chunk_start,
                chunk_end,
            )
        )
        all_rows.extend(rows)
        chunk_start_year += 2
        time.sleep(0.5)

    parsed_rows = [row[:6] for row in all_rows if len(row) >= 6]
    if not parsed_rows:
        raise ValueError(f"{code} 没有可解析的行情记录")

    frame = pd.DataFrame(
        parsed_rows,
        columns=["date", "open", "close", "high", "low", "volume_raw"],
    )
    for column in ["open", "close", "high", "low", "volume_raw"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    frame = frame[
        (frame["date"] >= pd.Timestamp(start_date))
        & (frame["date"] <= pd.Timestamp(end_date))
    ]
    frame.sort_values("date", inplace=True)
    frame.drop_duplicates("date", keep="last", inplace=True)

    frame["high_raw"] = frame["high"]
    frame["low_raw"] = frame["low"]
    frame["quality_flag"] = ""

    invalid_bounds = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    if invalid_bounds.any():
        raw_bounds = frame.loc[
            invalid_bounds,
            ["open", "close", "high_raw", "low_raw"],
        ]
        frame.loc[invalid_bounds, "high"] = raw_bounds.max(axis=1)
        frame.loc[invalid_bounds, "low"] = raw_bounds.min(axis=1)
        frame.loc[invalid_bounds, "quality_flag"] = "ohlc_bounds_repaired"
        logging.warning(
            "%s 修复 %s 条源数据OHLC边界异常",
            metadata["name"],
            int(invalid_bounds.sum()),
        )

    frame["preclose"] = frame["close"].shift(1)
    frame["change"] = frame["close"] - frame["preclose"]
    frame["pct_change_pct"] = frame["change"] / frame["preclose"] * 100.0
    frame["amplitude_pct"] = (
        (frame["high"] - frame["low"]) / frame["preclose"] * 100.0
    )
    frame["amount"] = pd.NA
    frame["turnover_pct"] = pd.NA
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")

    frame["code"] = code
    frame["symbol"] = metadata["symbol"]
    frame["name"] = metadata["name"]
    frame["asset_type"] = metadata["asset_type"]
    frame["trade_status"] = 1
    frame["is_st"] = 0
    frame["adjustment"] = "unadjusted"
    frame["source"] = "tencent_https"
    return frame[PRICE_COLUMNS].reset_index(drop=True)


def fetch_all_prices(start_date: str, end_date: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for code, metadata in SECURITIES.items():
        logging.info("开始下载日线行情: %s %s", code, metadata["name"])
        frames.append(fetch_price(code, start_date, end_date))
        time.sleep(1.0)
    return pd.concat(frames, ignore_index=True).sort_values(["date", "code"])


def fetch_corporate_actions(code: str) -> pd.DataFrame:
    metadata = SECURITIES[code]
    raw = retry(
        lambda: ak.stock_fhps_detail_em(symbol=metadata["symbol"]),
        attempts=5,
        delay=2.0,
    )
    if raw.empty:
        return pd.DataFrame(columns=CORPORATE_ACTION_COLUMNS)

    output = pd.DataFrame(index=raw.index)
    output["code"] = code
    output["symbol"] = metadata["symbol"]
    output["name"] = metadata["name"]
    output["report_date"] = column_or_na(raw, "报告期")
    output["pre_notice_date"] = column_or_na(raw, "预案公告日")
    output["implementation_announcement_date"] = column_or_na(raw, "最新公告日期")
    output["record_date"] = column_or_na(raw, "股权登记日")
    output["ex_date"] = column_or_na(raw, "除权除息日")
    output["payment_date"] = pd.NA
    output["stock_listing_date"] = pd.NA
    output["cash_before_tax_per_share"] = (
        pd.to_numeric(column_or_na(raw, "现金分红-现金分红比例"), errors="coerce") / 10.0
    )
    output["cash_after_tax_per_share_raw"] = pd.NA
    output["stock_dividend_per_share"] = (
        pd.to_numeric(column_or_na(raw, "送转股份-送股比例"), errors="coerce") / 10.0
    )
    output["capitalisation_issue_per_share"] = (
        pd.to_numeric(column_or_na(raw, "送转股份-转股比例"), errors="coerce") / 10.0
    )
    output["plan_status"] = column_or_na(raw, "方案进度")
    output["plan_description"] = column_or_na(raw, "现金分红-现金分红比例描述")
    output["source"] = "akshare_eastmoney"

    for column in [
        "report_date",
        "pre_notice_date",
        "implementation_announcement_date",
        "record_date",
        "ex_date",
        "payment_date",
        "stock_listing_date",
    ]:
        values = pd.to_datetime(output[column], errors="coerce")
        output[column] = values.dt.strftime("%Y-%m-%d")

    output = output[CORPORATE_ACTION_COLUMNS].dropna(subset=["ex_date"])
    output = output.drop_duplicates(
        [
            "code",
            "ex_date",
            "cash_before_tax_per_share",
            "stock_dividend_per_share",
            "capitalisation_issue_per_share",
        ]
    )
    return output.sort_values(["ex_date", "code"]).reset_index(drop=True)


def fetch_all_corporate_actions(start_date: str, end_date: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for code, metadata in SECURITIES.items():
        if metadata["asset_type"] != "stock":
            continue
        logging.info("下载公司行为: %s %s", code, metadata["name"])
        frames.append(fetch_corporate_actions(code))
        time.sleep(1.0)

    output = pd.concat(frames, ignore_index=True)
    return output[(output["ex_date"] >= start_date) & (output["ex_date"] <= end_date)].copy()


def validate_prices(prices: pd.DataFrame, end_date: str) -> None:
    if prices.empty:
        raise ValueError("行情数据为空")
    if prices.duplicated(["date", "code"]).any():
        raise ValueError("行情存在重复的 date+code")

    invalid_ohlc = (
        (prices["open"] <= 0)
        | (prices["high"] <= 0)
        | (prices["low"] <= 0)
        | (prices["close"] <= 0)
        | (prices["high"] < prices[["open", "close", "low"]].max(axis=1))
        | (prices["low"] > prices[["open", "close", "high"]].min(axis=1))
    )
    if invalid_ohlc.any():
        sample = prices.loc[
            invalid_ohlc,
            ["date", "code", "open", "high", "low", "close"],
        ].head()
        raise ValueError(f"行情OHLC校验失败:\n{sample.to_string(index=False)}")

    repaired_rows = int((prices["quality_flag"] == "ohlc_bounds_repaired").sum())
    if repaired_rows > MAX_REPAIRED_OHLC_ROWS:
        raise ValueError(
            f"OHLC边界修复记录过多: {repaired_rows} > {MAX_REPAIRED_OHLC_ROWS}"
        )

    requested_end = parse_iso_date(end_date)
    for code in SECURITIES:
        subset = prices[prices["code"] == code]
        if len(subset) < MIN_EXPECTED_ROWS:
            raise ValueError(f"{code} 历史行数异常，仅 {len(subset)} 行")
        latest = parse_iso_date(str(subset["date"].max()))
        if (requested_end - latest).days > MAX_SOURCE_STALENESS_DAYS:
            raise ValueError(f"{code} 最新数据 {latest} 距请求截止日过久")


def validate_corporate_actions(corporate_actions: pd.DataFrame) -> None:
    if corporate_actions.empty:
        raise ValueError("四只银行股均未获取到公司行为数据")
    expected = {
        code
        for code, metadata in SECURITIES.items()
        if metadata["asset_type"] == "stock"
    }
    missing = expected - set(corporate_actions["code"].unique())
    if missing:
        raise ValueError(f"公司行为缺少标的: {sorted(missing)}")


def write_outputs(
    prices: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    prices_path = DATA_DIR / "daily_prices_unadjusted.csv"
    actions_path = DATA_DIR / "corporate_actions.csv"
    open_path = DATA_DIR / "open_prices_wide.csv"
    close_path = DATA_DIR / "close_prices_wide.csv"
    manifest_path = DATA_DIR / "manifest.json"

    prices.to_csv(prices_path, index=False, encoding="utf-8-sig", float_format="%.8f")
    corporate_actions.to_csv(
        actions_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.8f",
    )
    prices.pivot(index="date", columns="code", values="open").sort_index().to_csv(
        open_path,
        encoding="utf-8-sig",
        float_format="%.8f",
    )
    prices.pivot(index="date", columns="code", values="close").sort_index().to_csv(
        close_path,
        encoding="utf-8-sig",
        float_format="%.8f",
    )

    security_summary: list[dict[str, object]] = []
    for code, metadata in SECURITIES.items():
        subset = prices[prices["code"] == code]
        security_summary.append(
            {
                "code": code,
                "symbol": metadata["symbol"],
                "name": metadata["name"],
                "asset_type": metadata["asset_type"],
                "rows": int(len(subset)),
                "first_date": str(subset["date"].min()),
                "last_date": str(subset["date"].max()),
                "ohlc_repaired_rows": int(
                    (subset["quality_flag"] == "ohlc_bounds_repaired").sum()
                ),
                "source": "tencent_https",
            }
        )

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "price_adjustment": "unadjusted",
        "price_source": "Tencent public HTTPS daily kline",
        "corporate_action_source": "AKShare stock_fhps_detail_em (Eastmoney)",
        "corporate_action_policy": (
            "Apply cash and share distributions explicitly in the backtest account."
        ),
        "price_rows": int(len(prices)),
        "corporate_action_rows": int(len(corporate_actions)),
        "ohlc_repaired_rows": int(
            (prices["quality_flag"] == "ohlc_bounds_repaired").sum()
        ),
        "securities": security_summary,
        "files": [
            prices_path.name,
            actions_path.name,
            open_path.name,
            close_path.name,
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载四大行 MA20 组合回测数据")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="YYYY-MM-DD")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    start_date = parse_iso_date(args.start_date).isoformat()
    end_date = parse_iso_date(args.end_date).isoformat()
    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")

    prices = fetch_all_prices(start_date, end_date)
    corporate_actions = fetch_all_corporate_actions(start_date, end_date)
    validate_prices(prices, end_date)
    validate_corporate_actions(corporate_actions)
    write_outputs(prices, corporate_actions, start_date, end_date)

    logging.info(
        "完成：行情 %s 行，公司行为 %s 行，OHLC修复 %s 行，输出目录 %s",
        len(prices),
        len(corporate_actions),
        int((prices["quality_flag"] == "ohlc_bounds_repaired").sum()),
        DATA_DIR,
    )


if __name__ == "__main__":
    main()
