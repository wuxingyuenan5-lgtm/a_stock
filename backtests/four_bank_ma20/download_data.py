#!/usr/bin/env python3
"""Download auditable daily data for the four-bank MA20 portfolio backtest.

Primary source: BaoStock. AKShare is used only as a per-dataset fallback.
Execution prices are deliberately unadjusted. Cash dividends, stock dividends,
and capitalisation issues are stored separately so the backtest can account for
corporate actions explicitly rather than trading on adjusted prices.
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

DIVIDEND_COLUMNS = [
    "code",
    "symbol",
    "name",
    "report_year",
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
        except Exception as exc:  # noqa: BLE001 - retries must preserve source errors
            last_error = exc
            if attempt == attempts:
                break
            logging.warning("请求失败，第 %s/%s 次重试: %s", attempt, attempts, exc)
            time.sleep(delay * attempt)
    assert last_error is not None
    raise last_error


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def yyyymmdd(value: str) -> str:
    return value.replace("-", "")


def result_set_to_frame(result: object, context: str) -> pd.DataFrame:
    error_code = getattr(result, "error_code", None)
    error_msg = getattr(result, "error_msg", "")
    if error_code != "0":
        raise RuntimeError(f"{context}失败: {error_code} {error_msg}")

    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    fields = list(getattr(result, "fields", []))
    return pd.DataFrame(rows, columns=fields)


def add_security_metadata(frame: pd.DataFrame, code: str, source: str) -> pd.DataFrame:
    metadata = SECURITIES[code]
    output = frame.copy()
    output["code"] = code
    output["symbol"] = metadata["symbol"]
    output["name"] = metadata["name"]
    output["asset_type"] = metadata["asset_type"]
    output["adjustment"] = "unadjusted"
    output["source"] = source
    return output


def normalize_price_frame(frame: pd.DataFrame, code: str, source: str) -> pd.DataFrame:
    rename_map = {
        "turn": "turnover_pct",
        "tradestatus": "trade_status",
        "pctChg": "pct_change_pct",
        "isST": "is_st",
    }
    output = frame.rename(columns=rename_map).copy()
    output = add_security_metadata(output, code, source)

    for column in [
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
    ]:
        if column not in output.columns:
            output[column] = pd.NA
        output[column] = pd.to_numeric(output[column], errors="coerce")

    output["date"] = pd.to_datetime(output["date"], errors="coerce")
    output = output.dropna(subset=["date", "open", "high", "low", "close"])
    output["date"] = output["date"].dt.strftime("%Y-%m-%d")
    output = output[PRICE_COLUMNS].sort_values("date").drop_duplicates(["date", "code"])
    return output.reset_index(drop=True)


def fetch_price_baostock(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    fields = (
        "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
        "turn,tradestatus,pctChg,isST"
    )
    result = bs.query_history_k_data_plus(
        code,
        fields,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="3",
    )
    frame = result_set_to_frame(result, f"BaoStock {code} 日线")
    if frame.empty:
        raise RuntimeError(f"BaoStock {code} 返回空行情")
    return normalize_price_frame(frame, code, "baostock")


def fetch_price_akshare(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    metadata = SECURITIES[code]
    if metadata["asset_type"] == "index":
        raw = retry(
            lambda: ak.stock_zh_index_daily_em(
                symbol="sh000001",
                start_date=yyyymmdd(start_date),
                end_date=yyyymmdd(end_date),
            )
        )
        frame = raw.rename(
            columns={
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
                "amount": "amount",
            }
        )
    else:
        raw = retry(
            lambda: ak.stock_zh_a_hist(
                symbol=metadata["symbol"],
                period="daily",
                start_date=yyyymmdd(start_date),
                end_date=yyyymmdd(end_date),
                adjust="",
                timeout=30,
            )
        )
        frame = raw.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover_pct",
                "涨跌幅": "pct_change_pct",
            }
        )

    if frame.empty:
        raise RuntimeError(f"AKShare {code} 返回空行情")
    frame["preclose"] = pd.to_numeric(frame.get("close"), errors="coerce").shift(1)
    frame["trade_status"] = 1
    frame["is_st"] = 0
    return normalize_price_frame(frame, code, "akshare_fallback")


def fetch_all_prices(start_date: str, end_date: str, baostock_available: bool) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for code in SECURITIES:
        logging.info("下载日线行情: %s %s", code, SECURITIES[code]["name"])
        if baostock_available:
            try:
                frame = retry(lambda code=code: fetch_price_baostock(code, start_date, end_date))
            except Exception as exc:  # noqa: BLE001
                logging.warning("BaoStock行情失败，改用AKShare: %s", exc)
                frame = fetch_price_akshare(code, start_date, end_date)
        else:
            frame = fetch_price_akshare(code, start_date, end_date)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["date", "code"])


def normalize_baostock_dividends(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    metadata = SECURITIES[code]
    rename_map = {
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
    output = frame.rename(columns=rename_map).copy()
    output["code"] = code
    output["symbol"] = metadata["symbol"]
    output["name"] = metadata["name"]
    output["source"] = "baostock"
    output["report_year"] = pd.to_datetime(
        output.get("plan_announcement_date"), errors="coerce"
    ).dt.year
    return normalize_dividend_frame(output)


def normalize_akshare_dividends(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    metadata = SECURITIES[code]
    output = pd.DataFrame()
    output["code"] = code
    output["symbol"] = metadata["symbol"]
    output["name"] = metadata["name"]
    output["report_year"] = pd.to_datetime(frame.get("报告期"), errors="coerce").dt.year
    output["pre_notice_date"] = frame.get("预案公告日")
    output["agm_announcement_date"] = pd.NA
    output["plan_announcement_date"] = frame.get("预案公告日")
    output["implementation_announcement_date"] = frame.get("最新公告日期")
    output["record_date"] = frame.get("股权登记日")
    output["ex_date"] = frame.get("除权除息日")
    output["payment_date"] = pd.NA
    output["stock_listing_date"] = pd.NA
    output["cash_before_tax_per_share"] = (
        pd.to_numeric(frame.get("现金分红-现金分红比例"), errors="coerce") / 10.0
    )
    output["cash_after_tax_per_share_raw"] = pd.NA
    output["stock_dividend_per_share"] = (
        pd.to_numeric(frame.get("送转股份-送股比例"), errors="coerce") / 10.0
    )
    output["capitalisation_issue_per_share"] = (
        pd.to_numeric(frame.get("送转股份-转股比例"), errors="coerce") / 10.0
    )
    output["plan_description"] = frame.get("现金分红-现金分红比例描述")
    output["source"] = "akshare_fallback"
    return normalize_dividend_frame(output)


def normalize_dividend_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in DIVIDEND_COLUMNS:
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

    output["report_year"] = pd.to_numeric(output["report_year"], errors="coerce").astype("Int64")
    output = output[DIVIDEND_COLUMNS]
    output = output.dropna(subset=["ex_date"])
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


def fetch_dividends_baostock(code: str, start_year: int, end_year: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in range(start_year, end_year + 1):
        result = bs.query_dividend_data(code=code, year=str(year), yearType="operate")
        frame = result_set_to_frame(result, f"BaoStock {code} {year} 分红")
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=DIVIDEND_COLUMNS)
    return normalize_baostock_dividends(pd.concat(frames, ignore_index=True), code)


def fetch_dividends_akshare(code: str) -> pd.DataFrame:
    symbol = SECURITIES[code]["symbol"]
    raw = retry(lambda: ak.stock_fhps_detail_em(symbol=symbol))
    if raw.empty:
        return pd.DataFrame(columns=DIVIDEND_COLUMNS)
    return normalize_akshare_dividends(raw, code)


def fetch_all_dividends(start_date: str, end_date: str, baostock_available: bool) -> pd.DataFrame:
    start_year = parse_iso_date(start_date).year
    end_year = parse_iso_date(end_date).year
    frames: list[pd.DataFrame] = []

    for code, metadata in SECURITIES.items():
        if metadata["asset_type"] != "stock":
            continue
        logging.info("下载公司行为: %s %s", code, metadata["name"])
        if baostock_available:
            try:
                frame = retry(
                    lambda code=code: fetch_dividends_baostock(code, start_year, end_year),
                    attempts=2,
                    delay=1.5,
                )
            except Exception as exc:  # noqa: BLE001
                logging.warning("BaoStock分红失败，改用AKShare: %s", exc)
                frame = fetch_dividends_akshare(code)
        else:
            frame = fetch_dividends_akshare(code)
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=DIVIDEND_COLUMNS)
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
        sample = prices.loc[invalid_ohlc, ["date", "code", "open", "high", "low", "close"]].head()
        raise ValueError(f"行情OHLC校验失败:\n{sample.to_string(index=False)}")

    requested_end = parse_iso_date(end_date)
    for code in SECURITIES:
        subset = prices[prices["code"] == code]
        if len(subset) < 1000:
            raise ValueError(f"{code} 历史行数异常，仅 {len(subset)} 行")
        latest = parse_iso_date(str(subset["date"].max()))
        if (requested_end - latest).days > MAX_SOURCE_STALENESS_DAYS:
            raise ValueError(f"{code} 最新数据 {latest} 距请求截止日过久")


def write_outputs(prices: pd.DataFrame, dividends: pd.DataFrame, start_date: str, end_date: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    prices_path = DATA_DIR / "daily_prices_unadjusted.csv"
    dividends_path = DATA_DIR / "corporate_actions.csv"
    open_path = DATA_DIR / "open_prices_wide.csv"
    close_path = DATA_DIR / "close_prices_wide.csv"
    manifest_path = DATA_DIR / "manifest.json"

    prices.to_csv(prices_path, index=False, encoding="utf-8-sig", float_format="%.8f")
    dividends.to_csv(dividends_path, index=False, encoding="utf-8-sig", float_format="%.8f")

    open_wide = prices.pivot(index="date", columns="code", values="open").sort_index()
    close_wide = prices.pivot(index="date", columns="code", values="close").sort_index()
    open_wide.to_csv(open_path, encoding="utf-8-sig", float_format="%.8f")
    close_wide.to_csv(close_path, encoding="utf-8-sig", float_format="%.8f")

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
                "source": sorted(subset["source"].dropna().astype(str).unique().tolist()),
            }
        )

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "price_adjustment": "unadjusted",
        "corporate_action_policy": (
            "Cash and stock distributions are stored separately and must be applied by the backtest engine."
        ),
        "price_rows": int(len(prices)),
        "corporate_action_rows": int(len(dividends)),
        "securities": securities_manifest,
        "files": [
            prices_path.name,
            dividends_path.name,
            open_path.name,
            close_path.name,
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载四大行MA20组合回测数据")
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
    baostock_available = login.error_code == "0"
    if baostock_available:
        logging.info("BaoStock登录成功")
    else:
        logging.warning("BaoStock登录失败，将使用AKShare: %s", login.error_msg)

    try:
        prices = fetch_all_prices(start_date, end_date, baostock_available)
        dividends = fetch_all_dividends(start_date, end_date, baostock_available)
        validate_prices(prices, end_date)
        write_outputs(prices, dividends, start_date, end_date)
    finally:
        if baostock_available:
            bs.logout()

    logging.info(
        "完成：行情 %s 行，公司行为 %s 行，输出目录 %s",
        len(prices),
        len(dividends),
        DATA_DIR,
    )


if __name__ == "__main__":
    main()
