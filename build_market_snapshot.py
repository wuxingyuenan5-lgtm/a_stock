#!/usr/bin/env python3
"""Build a real A-share daily monitoring snapshot for a specified trading date."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import logging
from pathlib import Path
import time
from typing import Callable, TypeVar

import akshare as ak
import pandas as pd

DATA_DIR = Path("data")
DEFAULT_TARGET_DATE = "20260728"
DEFAULT_WORKERS = 24
T = TypeVar("T")


def retry(call: Callable[[], T], attempts: int = 3, delay: float = 0.8) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay * attempt)
    assert last_error is not None
    raise last_error


def normalize_code(value: object) -> str:
    text = str(value).strip().split(".")[0]
    return text.zfill(6)


def fetch_stock_universe() -> pd.DataFrame:
    raw = retry(ak.stock_zh_a_spot_em)
    required = {"代码", "名称"}
    if raw.empty or not required.issubset(raw.columns):
        raise ValueError(f"A股代码清单字段异常: {list(raw.columns)}")
    frame = raw[["代码", "名称"]].copy()
    frame["代码"] = frame["代码"].map(normalize_code)
    frame["名称"] = frame["名称"].astype(str).str.strip()
    return frame.drop_duplicates("代码")


def fetch_one_stock(row: pd.Series, target_date: str) -> dict[str, object]:
    code = row["代码"]
    raw = retry(
        lambda: ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=target_date,
            end_date=target_date,
            adjust="",
            timeout=20,
        ),
        attempts=3,
        delay=0.5,
    )
    required = {"日期", "收盘", "成交额", "涨跌幅"}
    if raw.empty or not required.issubset(raw.columns):
        raise ValueError("无目标日行情")
    record = raw.iloc[-1]
    return {
        "日期": pd.to_datetime(record["日期"]).strftime("%Y-%m-%d"),
        "股票代码": code,
        "股票名称": row["名称"],
        "收盘价": pd.to_numeric(record["收盘"], errors="coerce"),
        "涨跌幅": pd.to_numeric(record["涨跌幅"], errors="coerce") / 100,
        "成交额": pd.to_numeric(record["成交额"], errors="coerce"),
    }


def fetch_all_stock_history(
    universe: pd.DataFrame, target_date: str, workers: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    rows = [row.copy() for _, row in universe.iterrows()]
    total = len(rows)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(fetch_one_stock, row, target_date): row for row in rows
        }
        for position, future in enumerate(as_completed(future_map), start=1):
            row = future_map[future]
            try:
                records.append(future.result())
            except Exception as exc:
                failures.append(
                    {
                        "股票代码": row["代码"],
                        "股票名称": str(row["名称"]),
                        "错误": str(exc),
                    }
                )
            if position % 250 == 0 or position == total:
                logging.info(
                    "个股行情进度 %s/%s, 成功 %s, 失败 %s",
                    position,
                    total,
                    len(records),
                    len(failures),
                )

    data = pd.DataFrame(records)
    if data.empty:
        raise RuntimeError("未获取到任何目标日个股行情")
    data = data.dropna(subset=["收盘价", "涨跌幅", "成交额"])
    return data, pd.DataFrame(failures)


def fetch_index_row(
    name: str, candidates: list[str], target_date: str
) -> dict[str, object]:
    target_dt = datetime.strptime(target_date, "%Y%m%d")
    start_date = (target_dt - timedelta(days=15)).strftime("%Y%m%d")
    last_error: Exception | None = None

    for symbol in candidates:
        try:
            raw = retry(
                lambda symbol=symbol: ak.stock_zh_index_daily_em(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=target_date,
                )
            )
            if raw.empty:
                continue
            raw = raw.copy()
            raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
            raw = raw.dropna(subset=["date", "close"]).sort_values("date")
            target = raw[raw["date"].dt.strftime("%Y%m%d") == target_date]
            if target.empty:
                continue
            idx = target.index[-1]
            pos = raw.index.get_loc(idx)
            close = float(raw.loc[idx, "close"])
            amount = float(raw.loc[idx, "amount"])
            previous_close = float(raw.iloc[pos - 1]["close"]) if pos > 0 else float("nan")
            daily_return = close / previous_close - 1 if pos > 0 else float("nan")
            return {
                "日期": target_dt.strftime("%Y-%m-%d"),
                "指标": name,
                "数据代码": symbol,
                "收盘点位": close,
                "涨跌幅": daily_return,
                "成交额_亿元": amount / 1e8,
            }
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"{name} 获取失败: {last_error}")


def fetch_index_snapshot(target_date: str) -> pd.DataFrame:
    definitions = [
        ("上证50", ["sh000016"]),
        ("微盘代理（国证2000）", ["sz399303"]),
        ("中证全指", ["csi000985"]),
    ]
    return pd.DataFrame(
        [fetch_index_row(name, candidates, target_date) for name, candidates in definitions]
    )


def fetch_limit_counts(target_date: str) -> tuple[int, int]:
    up_pool = retry(lambda: ak.stock_zt_pool_em(date=target_date))
    down_pool = retry(lambda: ak.stock_zt_pool_dtgc_em(date=target_date))
    return len(up_pool), len(down_pool)


def build_sw_second_mapping() -> pd.DataFrame:
    info = retry(ak.sw_index_second_info)
    required = {"行业代码", "行业名称", "上级行业"}
    if info.empty or not required.issubset(info.columns):
        raise ValueError(f"申万二级行业信息异常: {list(info.columns)}")

    records: list[dict[str, str]] = []
    for _, row in info.iterrows():
        industry_code = normalize_code(row["行业代码"])
        try:
            cons = retry(lambda code=industry_code: ak.index_component_sw(symbol=code))
        except Exception as exc:
            logging.warning("申万二级行业成分获取失败 %s: %s", industry_code, exc)
            continue
        if cons.empty or "证券代码" not in cons.columns:
            continue
        for stock_code in cons["证券代码"].dropna().astype(str):
            records.append(
                {
                    "股票代码": normalize_code(stock_code),
                    "申万一级行业": str(row["上级行业"]).strip(),
                    "申万二级行业": str(row["行业名称"]).strip(),
                }
            )
    if not records:
        return pd.DataFrame(columns=["股票代码", "申万一级行业", "申万二级行业"])
    return pd.DataFrame(records).drop_duplicates("股票代码", keep="first")


def write_outputs(target_date: str, workers: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_label = datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d")

    logging.info("获取A股代码清单")
    universe = fetch_stock_universe()
    logging.info("代码数量: %s", len(universe))

    logging.info("获取 %s 全部A股历史行情", date_label)
    stocks, failures = fetch_all_stock_history(universe, target_date, workers)

    logging.info("获取指数行情")
    indexes = fetch_index_snapshot(target_date)

    logging.info("获取涨跌停股池")
    limit_up, limit_down = fetch_limit_counts(target_date)

    up_count = int((stocks["涨跌幅"] > 0).sum())
    down_count = int((stocks["涨跌幅"] < 0).sum())
    flat_count = int((stocks["涨跌幅"] == 0).sum())
    market_amount = float(stocks["成交额"].sum() / 1e8)

    hot = stocks[stocks["成交额"] >= 10_000_000_000].copy()
    hot["成交额_亿元"] = hot["成交额"] / 1e8
    hot.drop(columns=["成交额"], inplace=True)
    hot.sort_values(["成交额_亿元", "股票代码"], ascending=[False, True], inplace=True)

    logging.info("获取申万二级行业映射")
    sw_map = build_sw_second_mapping()
    hot = hot.merge(sw_map, on="股票代码", how="left")
    hot["申万一级行业"] = hot["申万一级行业"].fillna("未匹配")
    hot["申万二级行业"] = hot["申万二级行业"].fillna("未匹配")
    hot.insert(0, "序号", range(1, len(hot) + 1))

    industry = (
        hot.groupby(["申万一级行业", "申万二级行业"], as_index=False)
        .agg(
            百亿成交个股数=("股票代码", "count"),
            合计成交额_亿元=("成交额_亿元", "sum"),
            平均涨跌幅=("涨跌幅", "mean"),
        )
        .sort_values(
            ["百亿成交个股数", "合计成交额_亿元", "申万二级行业"],
            ascending=[False, False, True],
        )
    )
    industry.insert(0, "排名", range(1, len(industry) + 1))

    summary = pd.DataFrame(
        [
            {
                "日期": date_label,
                "上涨家数": up_count,
                "下跌家数": down_count,
                "平盘家数": flat_count,
                "涨停家数": limit_up,
                "跌停家数": limit_down,
                "可用行情股票数": len(stocks),
                "请求失败数": len(failures),
                "全部A股成交额_亿元": market_amount,
                "成交额超百亿个股数": len(hot),
                "百亿个股成交额合计_亿元": float(hot["成交额_亿元"].sum()),
            }
        ]
    )

    suffix = target_date
    indexes.to_csv(DATA_DIR / f"market_indexes_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    summary.to_csv(DATA_DIR / f"market_breadth_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    hot.to_csv(DATA_DIR / f"turnover_100bn_stocks_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    industry.to_csv(DATA_DIR / f"turnover_100bn_industries_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    if not failures.empty:
        failures.to_csv(DATA_DIR / f"market_snapshot_failures_{suffix}.csv", index=False, encoding="utf-8-sig")

    logging.info(
        "完成 %s: 上涨 %s, 下跌 %s, 涨停 %s, 跌停 %s, 百亿个股 %s, 失败 %s",
        date_label,
        up_count,
        down_count,
        limit_up,
        limit_down,
        len(hot),
        len(failures),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股每日市场监控快照")
    parser.add_argument("--target-date", default=DEFAULT_TARGET_DATE, help="YYYYMMDD")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    write_outputs(args.target_date, args.workers)


if __name__ == "__main__":
    main()
