#!/usr/bin/env python3
"""Download unadjusted prices and corporate actions for the four-bank backtest."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Callable, TypeVar

import baostock as bs
import pandas as pd

DATA_DIR = Path("data/four_bank_ma20")
DEFAULT_START_DATE = "2011-01-01"
MAX_SOURCE_STALENESS_DAYS = 20

SECURITIES: dict[str, dict[str, str]] = {
    "sh.000001": {"symbol": "000001", "name": "上证指数", "asset_type": "index"},
    "sh.601988": {"symbol": "601988", "name": "中国银行", "asset_type": "stock"},
    "sh.601398": {"symbol": "601398", "name": "工商银行", "asset_type": "stock"},
    "sh.601939": {"symbol": "601939", "name": "建设银行", "asset_type": "stock"},
    "sh.601288": {"symbol": "601288", "name": "农业银行", "asset_type": "stock"},
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
    "preclose",
    "volume",
    "amount",
    "turnover_pct",
    "trade_status",
    "pct_change_pct",
    "is_st",
    "adjustment",
    "source",
]

CORPORATE_ACTION_COLUMNS = [
    "code",
    "symbol",
    "name",
    "event_year",
    "pre_notice_date",
    "agm_announcement_date",
    "plan_announcement_date",
    "implementation_announcement_date",
    "record_date",
    "ex_date",
    "payment_date",
    "stock_listing_date",
    "cash_before_tax_per_share",
    "cash_after_tax_per_share_raw",
    "stock_dividend_per_share",
    "capitalisation_issue_per_share",
    "plan_description",
    "source",
]

T = TypeVar("T")


def retry(call: Callable[[], T], attempts: int = 3, delay: float = 1.0) -> T:
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


def result_set_to_frame(result: object, context: str) -> pd.DataFrame:
    error_code = getattr(result, "error_code", None)
    error_msg = getattr(result, "error_msg", "")
    if error_code != "0":
        raise RuntimeError(f"{context}失败: {error_code} {error_msg}")

    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=list(getattr(result, "fields", [])))


def fetch_price(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    fields = (
        "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
        "turn,tradestatus,pctChg,isST"
    )
    result = retry(
        lambda: bs.query_history_k_data_plus(
            code,
            fields,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",
        )
    )
    frame = result_set_to_frame(result, f"{code} 日线")
    if frame.empty:
        raise RuntimeError(f"{code} 返回空行情")

    frame = frame.rename(
        columns={
            "turn": "turnover_pct",
            "tradestatus": "trade_status",
            "pctChg": "pct_change_pct",
            "isST": "is_st",
        }
    )
    metadata = SECURITIES[code]
    frame["code"] = code
    frame["symbol"] = metadata["symbol"]
    frame["name"] = metadata["name"]
    frame["asset_type"] = metadata["asset_type"]
    frame["adjustment"] = "unadjusted"
    frame["source"] = "baostock"

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turnover_pct",
        "trade_status",
        "pct_change_pct",
        "is_st",
    ]
    for column in numeric_columns:
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    return (
        frame[PRICE_COLUMNS]
        .sort_values("date")
        .drop_duplicates(["date", "code"])
        .reset_index(drop=True)
    )


def fetch_all_prices(start_date: str, end_date: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for code, metadata in SECURITIES.items():
        logging.info("下载日线行情: %s %s", code, metadata["name"])
        frames.append(fetch_price(code, start_date, end_date))
    return pd.concat(frames, ignore_index=True).sort_values(["date", "code"])


def fetch_corporate_actions(code: str, start_year: int, end_year: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in range(start_year, end_year + 1):
        result = retry(
            lambda year=year: bs.query_dividend_data(
                code=code,
                year=str(year),
                yearType="operate",
            ),
            attempts=2,
            delay=1.5,
        )
        frame = result_set_to_frame(result, f"{code} {year} 公司行为")
        if not frame.empty:
            frame["event_year"] = year
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=CORPORATE_ACTION_COLUMNS)

    output = pd.concat(frames, ignore_index=True).rename(
        columns={
            "dividPreNoticeDate": "pre_notice_date",
            "dividAgmPumDate": "agm_announcement_date",
            "dividPlanAnnounceDate": "plan_announcement_date",
            "dividPlanDate": "implementation_announcement_date",
            "dividRegistDate": "record_date",
            "dividOperateDate": "ex_date",
            "dividPayDate": "payment_date",
            "dividStockMarketDate": "stock_listing_date",
            "dividCashPsBeforeTax": "cash_before_tax_per_share",
            "dividCashPsAfterTax": "cash_after_tax_per_share_raw",
            "dividStocksPs": "stock_dividend_per_share",
            "dividCashStock": "plan_description",
            "dividReserveToStockPs": "capitalisation_issue_per_share",
        }
    )

    metadata = SECURITIES[code]
    output["code"] = code
    output["symbol"] = metadata["symbol"]
    output["name"] = metadata["name"]
    output["source"] = "baostock"

    for column in CORPORATE_ACTION_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA

    date_columns = [
        "pre_notice_date",
        "agm_announcement_date",
        "plan_announcement_date",
        "implementation_announcement_date",
        "record_date",
        "ex_date",
        "payment_date",
        "stock_listing_date",
    ]
    for column in date_columns:
        values = pd.to_datetime(output[column], errors="coerce")
        output[column] = values.dt.strftime("%Y-%m-%d")

    for column in [
        "cash_before_tax_per_share",
        "stock_dividend_per_share",
        "capitalisation_issue_per_share",
    ]:
        output[column] = pd.to_numeric(output[column], errors="coerce")

    output["event_year"] = pd.to_numeric(output["event_year"], errors="coerce").astype("Int64")
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
    start_year = parse_iso_date(start_date).year
    end_year = parse_iso_date(end_date).year
    frames: list[pd.DataFrame] = []

    for code, metadata in SECURITIES.items():
        if metadata["asset_type"] != "stock":
            continue
        logging.info("下载公司行为: %s %s", code, metadata["name"])
        frames.append(fetch_corporate_actions(code, start_year, end_year))

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

    requested_end = parse_iso_date(end_date)
    for code in SECURITIES:
        subset = prices[prices["code"] == code]
        if len(subset) < 1000:
            raise ValueError(f"{code} 历史行数异常，仅 {len(subset)} 行")
        latest = parse_iso_date(str(subset["date"].max()))
        if (requested_end - latest).days > MAX_SOURCE_STALENESS_DAYS:
            raise ValueError(f"{code} 最新数据 {latest} 距请求截止日过久")


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

    securities_manifest: list[dict[str, object]] = []
    for code, metadata in SECURITIES.items():
        subset = prices[prices["code"] == code]
        securities_manifest.append(
            {
                "code": code,
                **metadata,
                "rows": int(len(subset)),
                "first_date": str(subset["date"].min()),
                "last_date": str(subset["date"].max()),
                "source": "baostock",
            }
        )

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "price_adjustment": "unadjusted",
        "corporate_action_policy": (
            "Apply cash and share distributions explicitly in the backtest account."
        ),
        "price_rows": int(len(prices)),
        "corporate_action_rows": int(len(corporate_actions)),
        "securities": securities_manifest,
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

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock登录失败: {login.error_code} {login.error_msg}")

    try:
        prices = fetch_all_prices(start_date, end_date)
        corporate_actions = fetch_all_corporate_actions(start_date, end_date)
        validate_prices(prices, end_date)
        write_outputs(prices, corporate_actions, start_date, end_date)
    finally:
        bs.logout()

    logging.info(
        "完成：行情 %s 行，公司行为 %s 行，输出目录 %s",
        len(prices),
        len(corporate_actions),
        DATA_DIR,
    )


if __name__ == "__main__":
    main()
