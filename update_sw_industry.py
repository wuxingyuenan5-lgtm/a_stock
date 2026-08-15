#!/usr/bin/env python3
"""Update Shenwan level-1 and level-2 industry close/turnover data."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import math
import time
from pathlib import Path
from typing import Callable, TypeVar

import akshare as ak
import pandas as pd

VOL_WINDOW = 20
ANNUALIZATION_DAYS = 252
DEFAULT_HISTORY_ROWS = 260
DEFAULT_WORKERS = 4
DATA_DIR = Path("data")

T = TypeVar("T")

INTERNAL_COLUMNS = [
    "date", "level", "level1_code", "level1_name", "index_code", "index_name",
    "close", "amount", "daily_return", "volatility_20d",
]
EXPORT_COLUMNS = {
    "date": "日期", "level": "行业层级", "level1_code": "一级行业代码",
    "level1_name": "一级行业", "index_code": "指数代码", "index_name": "指数名称",
    "close": "收盘价", "amount": "成交额", "daily_return": "日收益率",
    "volatility_20d": "20日年化波动率",
}


def retry(call: Callable[[], T], attempts: int = 3, delay: float = 1.0) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            logging.warning("请求失败，第 %s/%s 次重试：%s", attempt, attempts, exc)
            time.sleep(delay * attempt)
    assert last_error is not None
    raise last_error


def strip_suffix(value: object) -> str:
    return str(value).strip().split(".")[0]


def load_universe() -> pd.DataFrame:
    first_raw = retry(ak.sw_index_first_info)
    second_raw = retry(ak.sw_index_second_info)
    required_first = {"行业代码", "行业名称"}
    required_second = {"行业代码", "行业名称", "上级行业"}
    if not required_first.issubset(first_raw.columns):
        raise ValueError(f"申万一级行业字段异常：{list(first_raw.columns)}")
    if not required_second.issubset(second_raw.columns):
        raise ValueError(f"申万二级行业字段异常：{list(second_raw.columns)}")

    first = first_raw[["行业代码", "行业名称"]].copy()
    first.columns = ["index_code", "index_name"]
    first["index_code"] = first["index_code"].map(strip_suffix)
    first["index_name"] = first["index_name"].astype(str).str.strip()
    first["level"] = "一级行业"
    first["level1_code"] = first["index_code"]
    first["level1_name"] = first["index_name"]
    name_to_code = dict(zip(first["index_name"], first["index_code"], strict=False))

    second = second_raw[["行业代码", "行业名称", "上级行业"]].copy()
    second.columns = ["index_code", "index_name", "level1_name"]
    second["index_code"] = second["index_code"].map(strip_suffix)
    second["index_name"] = second["index_name"].astype(str).str.strip()
    second["level1_name"] = second["level1_name"].astype(str).str.strip()
    second["level"] = "二级行业"
    second["level1_code"] = second["level1_name"].map(name_to_code)
    missing_parent = second[second["level1_code"].isna()]
    if not missing_parent.empty:
        names = ", ".join(sorted(missing_parent["level1_name"].astype(str).unique()))
        raise ValueError(f"以下二级行业无法匹配一级行业：{names}")

    universe = pd.concat([
        first[["level", "level1_code", "level1_name", "index_code", "index_name"]],
        second[["level", "level1_code", "level1_name", "index_code", "index_name"]],
    ], ignore_index=True)
    return universe.drop_duplicates("index_code").sort_values(["level", "level1_name", "index_name"])


def fetch_one_history(row: pd.Series, history_rows: int) -> pd.DataFrame:
    code = row["index_code"]
    raw = retry(lambda: ak.index_hist_sw(symbol=code, period="day"))
    required = {"日期", "收盘", "成交额"}
    if raw.empty or not required.issubset(raw.columns):
        raise ValueError(f"{code} 返回空数据或字段异常：{list(raw.columns)}")
    frame = raw[["日期", "收盘", "成交额"]].rename(columns={"日期":"date","收盘":"close","成交额":"amount"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last").tail(history_rows)
    frame["level"] = row["level"]
    frame["level1_code"] = row["level1_code"]
    frame["level1_name"] = row["level1_name"]
    frame["index_code"] = code
    frame["index_name"] = row["index_name"]
    return frame


def load_existing_history(history_file: Path) -> pd.DataFrame:
    if not history_file.exists():
        return pd.DataFrame()
    existing = pd.read_csv(history_file, encoding="utf-8-sig")
    existing = existing.rename(columns={value:key for key,value in EXPORT_COLUMNS.items()})
    if "date" in existing.columns:
        existing["date"] = pd.to_datetime(existing["date"], errors="coerce")
    for column in ("level1_code", "index_code"):
        if column in existing.columns:
            existing[column] = existing[column].astype(str).str.replace(r"\.0$", "", regex=True)
    for column in ("close", "amount"):
        if column in existing.columns:
            existing[column] = pd.to_numeric(existing[column], errors="coerce")
    return existing


def calculate_metrics(data: pd.DataFrame, history_rows: int) -> pd.DataFrame:
    data = data.sort_values(["index_code", "date"]).drop_duplicates(["index_code", "date"], keep="last")
    data["daily_return"] = data.groupby("index_code")["close"].pct_change(fill_method=None)
    data["volatility_20d"] = data.groupby("index_code")["daily_return"].transform(
        lambda series: series.rolling(window=VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=1) * math.sqrt(ANNUALIZATION_DAYS)
    )
    data = data.groupby("index_code", group_keys=False).tail(history_rows)
    return data[INTERNAL_COLUMNS].sort_values(["date", "level", "level1_name", "index_name"])


def write_outputs(data: pd.DataFrame, failures: list[dict[str, str]], data_dir: Path) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    history_file = data_dir / "sw_industry_history.csv"
    latest_file = data_dir / "sw_industry_latest.csv"
    failures_file = data_dir / "sw_industry_failures.csv"

    exported = data.rename(columns=EXPORT_COLUMNS).copy()
    exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(history_file, index=False, encoding="utf-8-sig", float_format="%.8f")

    latest = (
        data.sort_values("date").groupby("index_code", as_index=False, group_keys=False).tail(1)
        .sort_values(["level", "level1_name", "index_name"]).rename(columns=EXPORT_COLUMNS)
    )
    latest["日期"] = latest["日期"].dt.strftime("%Y-%m-%d")
    latest.to_csv(latest_file, index=False, encoding="utf-8-sig", float_format="%.8f")

    if failures:
        pd.DataFrame(failures).to_csv(failures_file, index=False, encoding="utf-8-sig")
    elif failures_file.exists():
        failures_file.unlink()


def update(history_rows: int, sleep_seconds: float, workers: int, data_dir: Path = DATA_DIR) -> dict[str, object]:
    if history_rows < VOL_WINDOW + 1:
        raise ValueError(f"history_rows 至少为 {VOL_WINDOW + 1}")
    if workers < 1:
        raise ValueError("workers 至少为 1")
    data_dir = Path(data_dir)
    universe = load_universe()
    existing = load_existing_history(data_dir / "sw_industry_history.csv")
    fresh_frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []
    rows = [row.copy() for _, row in universe.iterrows()]
    total = len(rows)

    def run_one(position: int, row: pd.Series) -> pd.DataFrame:
        code = row["index_code"]
        logging.info("[%s/%s] 更新 %s %s", position, total, code, row["index_name"])
        if sleep_seconds > 0:
            time.sleep(sleep_seconds * ((position - 1) % workers) / workers)
        return fetch_one_history(row, history_rows)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(run_one, position, row): row for position, row in enumerate(rows, start=1)}
        for future in as_completed(future_map):
            row = future_map[future]
            code = row["index_code"]
            try:
                fresh_frames.append(future.result())
            except Exception as exc:
                logging.error("%s %s 更新失败：%s", code, row["index_name"], exc)
                failures.append({"指数代码": code, "指数名称": str(row["index_name"]), "错误": str(exc)})

    if not fresh_frames and existing.empty:
        raise RuntimeError("全部指数均更新失败，且没有可回退的历史数据")
    fresh = pd.concat(fresh_frames, ignore_index=True) if fresh_frames else pd.DataFrame()
    if existing.empty:
        combined = fresh
    elif fresh.empty:
        combined = existing
    else:
        refreshed_codes = set(fresh["index_code"].astype(str))
        fallback = existing[~existing["index_code"].astype(str).isin(refreshed_codes)].copy()
        combined = pd.concat([fallback, fresh], ignore_index=True)

    data = calculate_metrics(combined, history_rows)
    write_outputs(data, failures, data_dir)
    latest_date = data["date"].max().strftime("%Y-%m-%d")
    result = {
        "mode":"full_history_refresh", "updated_indices":int(data["index_code"].nunique()),
        "latest_date":latest_date, "failures":len(failures), "data_dir":str(data_dir),
    }
    logging.info("完成：%s 个指数，最新交易日 %s，失败 %s 个", result["updated_indices"], latest_date, len(failures))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="申万一级/二级行业每日跟踪")
    parser.add_argument("--history-rows", type=int, default=DEFAULT_HISTORY_ROWS)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--data-dir", default="data")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    update(args.history_rows, args.sleep_seconds, args.workers, Path(args.data_dir))


if __name__ == "__main__":
    main()
