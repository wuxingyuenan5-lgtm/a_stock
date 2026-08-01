#!/usr/bin/env python3
"""Download auditable daily data for the four-bank MA20 portfolio backtest.

The downloader uses unadjusted prices. Tencent's HTTPS daily-kline endpoint is
primary; Eastmoney's HTTPS endpoint is retained as a fallback. Corporate actions
are fetched through AKShare's Eastmoney-backed stock_fhps_detail_em interface and
stored separately for explicit accounting by the backtest engine.
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
MAX_SOURCE_STALENESS_DAYS = 20
MIN_EXPECTED_ROWS = 1000

TENCENT_PRICE_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
EASTMONEY_PRICE_ENDPOINTS = [
    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    "https://33.push2his.eastmoney.com/api/qt/stock/kline/get",
    "https://63.push2his.eastmoney.com/api/qt/stock/kline/get",
]

SECURITIES: dict[str, dict[str, str]] = {
    "sh.000001": {
        "tencent_symbol": "sh000001",
        "eastmoney_secid": "1.000001",
        "symbol": "000001",
        "name": "上证指数",
        "asset_type": "index",
    },
    "sh.601988": {
        "tencent_symbol": "sh601988",
        "eastmoney_secid": "1.601988",
        "symbol": "601988",
        "name": "中国银行",
        "asset_type": "stock",
    },
    "sh.601398": {
        "tencent_symbol": "sh601398",
        "eastmoney_secid": "1.601398",
        "symbol": "601398",
        "name": "工商银行",
        "asset_type": "stock",
    },
    "sh.601939": {
        "tencent_symbol": "sh601939",
        "eastmoney_secid": "1.601939",
        "symbol": "601939",
        "name": "建设银行",
        "asset_type": "stock",
    },
    "sh.601288": {
        "tencent_symbol": "sh601288",
        "eastmoney_secid": "1.601288",
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


def retry(call: Callable[[], T], attempts: int = 4, delay: float = 1.0) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - preserve upstream errors
            last_error = exc
            if attempt == attempts:
                break
            logging.warning("请求失败，第 %s/%s 次重试: %s", attempt, attempts, exc)
            time.sleep(delay * attempt)
    assert last_error is not None
    raise last_error


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def compact_date(value: str) -> str:
    return value.replace("-", "")


def column_or_na(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series(pd.NA, index=frame.index, dtype="object")


def request_json(
    url: str,
    params: dict[str, str],
    referer: str,
    timeout: tuple[int, int] = (10, 45),
) -> dict[str, object]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "application/json,text/plain,*/*",
    }
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("接口未返回JSON对象")
    return payload


def tencent_rows(
    tencent_symbol: str,
    start_date: str,
    end_date: str,
    count: int,
) -> list[list[str]]:
    params = {
        "param": f"{tencent_symbol},day,{start_date},{end_date},{count},",
        "r": str(time.time_ns()),
    }
    payload = request_json(
        TENCENT_PRICE_ENDPOINT,
        params,
        referer="https://gu.qq.com/",
    )
    if payload.get("code") != 0:
        raise RuntimeError(f"腾讯行情接口错误: {payload.get('code')} {payload.get('msg')}")
    data = payload.get("data")
    security_data = data.get(tencent_symbol) if isinstance(data, dict) else None
    rows = security_data.get("day") if isinstance(security_data, dict) else None
    if not rows:
        raise RuntimeError(f"腾讯行情返回空数据: {tencent_symbol}")
    return [[str(value) for value in row] for row in rows]


def fetch_tencent_rows(tencent_symbol: str, start_date: str, end_date: str) -> list[list[str]]:
    full_rows = retry(
        lambda: tencent_rows(tencent_symbol, start_date, end_date, 6400),
        attempts=3,
        delay=1.5,
    )
    if len(full_rows) >= MIN_EXPECTED_ROWS:
        return full_rows

    logging.info(
        "腾讯单次返回 %s 行，改为按两年区间分段下载: %s",
        len(full_rows),
        tencent_symbol,
    )
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    chunk_rows: list[list[str]] = []
    chunk_start_year = start.year
    while chunk_start_year <= end.year:
        chunk_start = max(start, date(chunk_start_year, 1, 1))
        chunk_end = min(end, date(chunk_start_year + 1, 12, 31))
        rows = retry(
            lambda chunk_start=chunk_start, chunk_end=chunk_end: tencent_rows(
                tencent_symbol,
                chunk_start.isoformat(),
                chunk_end.isoformat(),
                640,
            ),
            attempts=3,
            delay=1.5,
        )
        chunk_rows.extend(rows)
        chunk_start_year += 2
        time.sleep(0.4)
    return chunk_rows


def normalize_tencent_price(
    rows: list[list[str]],
    code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    parsed_rows = [row[:6] for row in rows if len(row) >= 6]
    if not parsed_rows:
        raise ValueError(f"{code} 腾讯行情字段为空")

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

    frame["preclose"] = frame["close"].shift(1)
    frame["change"] = frame["close"] - frame["preclose"]
    frame["pct_change_pct"] = frame["change"] / frame["preclose"] * 100.0
    frame["amplitude_pct"] = (
        (frame["high"] - frame["low"]) / frame["preclose"] * 100.0
    )
    frame["amount"] = pd.NA
    frame["turnover_pct"] = pd.NA
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")

    metadata = SECURITIES[code]
    frame["code"] = code
    frame["symbol"] = metadata["symbol"]
    frame["name"] = metadata["name"]
    frame["asset_type"] = metadata["asset_type"]
    frame["trade_status"] = 1
    frame["is_st"] = 0
    frame["adjustment"] = "unadjusted"
    frame["source"] = "tencent_https"
    return frame[PRICE_COLUMNS].reset_index(drop=True)


def request_eastmoney_payload(secid: str, start_date: str, end_date: str) -> dict[str, object]:
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": "0",
        "secid": secid,
        "beg": compact_date(start_date),
        "end": compact_date(end_date),
        "lmt": "1000000",
    }
    errors: list[str] = []
    for endpoint in EASTMONEY_PRICE_ENDPOINTS:
        try:
            payload = request_json(
                endpoint,
                params,
                referer="https://quote.eastmoney.com/",
            )
            data = payload.get("data")
            klines = data.get("klines") if isinstance(data, dict) else None
            if not klines:
                raise RuntimeError(f"接口返回空行情: {payload.get('rc')}")
            return payload
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{endpoint}: {exc}")
            time.sleep(0.8)
    raise RuntimeError("；".join(errors))


def normalize_eastmoney_price(payload: dict[str, object], code: str) -> pd.DataFrame:
    data = payload["data"]
    rows = [str(item).split(",") for item in data["klines"]]
    expected_columns = [
        "date",
        "open",
        "close",
        "high",
        "low",
        "volume_raw",
        "amount",
        "amplitude_pct",
        "pct_change_pct",
        "change",
        "turnover_pct",
    ]
    if any(len(row) != len(expected_columns) for row in rows):
        raise ValueError(f"{code} 东方财富行情字段数量异常")

    frame = pd.DataFrame(rows, columns=expected_columns)
    numeric_columns = [column for column in expected_columns if column != "date"]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    frame.sort_values("date", inplace=True)
    frame["preclose"] = frame["close"].shift(1)
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")

    metadata = SECURITIES[code]
    frame["code"] = code
    frame["symbol"] = metadata["symbol"]
    frame["name"] = metadata["name"]
    frame["asset_type"] = metadata["asset_type"]
    frame["trade_status"] = 1
    frame["is_st"] = 0
    frame["adjustment"] = "unadjusted"
    frame["source"] = "eastmoney_https_fallback"
    return frame[PRICE_COLUMNS].reset_index(drop=True)


def fetch_price(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    metadata = SECURITIES[code]
    try:
        rows = fetch_tencent_rows(metadata["tencent_symbol"], start_date, end_date)
        frame = normalize_tencent_price(rows, code, start_date, end_date)
        if len(frame) < MIN_EXPECTED_ROWS:
            raise ValueError(f"腾讯行情仅返回 {len(frame)} 行")
        return frame
    except Exception as exc:  # noqa: BLE001
        logging.warning("腾讯行情失败，改用东方财富: %s %s", code, exc)

    payload = retry(
        lambda: request_eastmoney_payload(
            metadata["eastmoney_secid"], start_date, end_date
        ),
        attempts=4,
        delay=3.0,
    )
    return normalize_eastmoney_price(payload, code)


def fetch_all_prices(start_date: str, end_date: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for code, metadata in SECURITIES.items():
        logging.info("下载日线行情: %s %s", code, metadata["name"])
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

    date_columns = [
        "report_date",
        "pre_notice_date",
        "implementation_announcement_date",
        "record_date",
        "ex_date",
        "payment_date",
        "stock_listing_date",
    ]
    for column in date_columns:
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

    if not frames:
        return pd.DataFrame(columns=CORPORATE_ACTION_COLUMNS)
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
        if len(subset) < MIN_EXPECTED_ROWS:
            raise ValueError(f"{code} 历史行数异常，仅 {len(subset)} 行")
        latest = parse_iso_date(str(subset["date"].max()))
        if (requested_end - latest).days > MAX_SOURCE_STALENESS_DAYS:
            raise ValueError(f"{code} 最新数据 {latest} 距请求截止日过久")


def validate_corporate_actions(corporate_actions: pd.DataFrame) -> None:
    if corporate_actions.empty:
        raise ValueError("四只银行股均未获取到公司行为数据")
    expected_codes = {
        code
        for code, metadata in SECURITIES.items()
        if metadata["asset_type"] == "stock"
    }
    missing_codes = expected_codes - set(corporate_actions["code"].unique())
    if missing_codes:
        raise ValueError(f"公司行为缺少标的: {sorted(missing_codes)}")


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
                "symbol": metadata["symbol"],
                "name": metadata["name"],
                "asset_type": metadata["asset_type"],
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
        "price_source_priority": ["Tencent HTTPS", "Eastmoney HTTPS fallback"],
        "corporate_action_source": "AKShare stock_fhps_detail_em (Eastmoney)",
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

    prices = fetch_all_prices(start_date, end_date)
    corporate_actions = fetch_all_corporate_actions(start_date, end_date)
    validate_prices(prices, end_date)
    validate_corporate_actions(corporate_actions)
    write_outputs(prices, corporate_actions, start_date, end_date)

    logging.info(
        "完成：行情 %s 行，公司行为 %s 行，输出目录 %s",
        len(prices),
        len(corporate_actions),
        DATA_DIR,
    )


if __name__ == "__main__":
    main()
