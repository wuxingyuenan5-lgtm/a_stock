#!/usr/bin/env python3
"""Build the 2026-07-28 review snapshot from real public market data."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import logging
from pathlib import Path
import time
from typing import Callable, TypeVar

import akshare as ak
import pandas as pd

DATA_DIR = Path("data")
DEFAULT_TARGET_DATE = "20260728"
T = TypeVar("T")

# 2026-07-28 全市场成交额超过 100 亿元的完整名单。
# 名单数量由北京商报收盘报道交叉核验；行情字段优先由 AKShare 重新获取。
HOT_STOCKS = [
    ("300308", "中际旭创", "通信", "通信设备", 516.00, -0.1569, 908.00),
    ("688825", "长鑫科技", "电子", "半导体", 444.28, -0.0408, 47.00),
    ("300502", "新易盛", "通信", "通信设备", 334.25, -0.1713, 406.90),
    ("000938", "紫光股份", "计算机", "计算机设备", 179.20, 0.0002, 41.48),
    ("603986", "兆易创新", "电子", "半导体", 176.04, -0.1000, 390.63),
    ("688256", "寒武纪", "电子", "半导体", 166.18, -0.0911, 1128.00),
    ("300750", "宁德时代", "电力设备", "电池", 146.53, -0.0229, 390.86),
    ("002384", "东山精密", "电子", "元件", 142.07, -0.1000, 190.71),
    ("002156", "通富微电", "电子", "半导体", 135.70, -0.1000, 69.00),
    ("688008", "澜起科技", "电子", "半导体", 132.10, -0.0941, 206.04),
    ("600584", "长电科技", "电子", "半导体", 108.7418, -0.0670, 76.83),
]

# 北京商报收盘统计；全部A股成交额为沪、深、北三市合计。
BREADTH = {
    "上涨家数": 2603,
    "下跌家数": 2769,
    "平盘家数": 0,
    "涨停家数": 68,
    "跌停家数": 50,
    "全部A股成交额_亿元": 9496.83 + 10760.98 + 135.25,
}


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


def fetch_stock_row(
    code: str,
    name: str,
    level1: str,
    level2: str,
    fallback_amount: float,
    fallback_return: float,
    fallback_close: float,
    target_date: str,
) -> dict[str, object]:
    source = "AKShare/东方财富历史行情"
    try:
        raw = retry(
            lambda: ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=target_date,
                end_date=target_date,
                adjust="",
                timeout=20,
            )
        )
        required = {"日期", "收盘", "成交额", "涨跌幅"}
        if raw.empty or not required.issubset(raw.columns):
            raise ValueError("无目标日行情")
        record = raw.iloc[-1]
        close = float(pd.to_numeric(record["收盘"], errors="raise"))
        daily_return = float(pd.to_numeric(record["涨跌幅"], errors="raise")) / 100
        amount = float(pd.to_numeric(record["成交额"], errors="raise")) / 1e8
    except Exception as exc:
        logging.warning("%s %s 使用已核验公开数据回退: %s", code, name, exc)
        close = fallback_close
        daily_return = fallback_return
        amount = fallback_amount
        source = "公开收盘报道回退"

    return {
        "日期": datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d"),
        "股票代码": code,
        "股票名称": name,
        "收盘价": close,
        "涨跌幅": daily_return,
        "成交额_亿元": amount,
        "申万一级行业": level1,
        "申万二级行业": level2,
        "数据来源": source,
    }


def fetch_index_row(name: str, symbol: str, target_date: str) -> dict[str, object]:
    target_dt = datetime.strptime(target_date, "%Y%m%d")
    start_date = (target_dt - timedelta(days=15)).strftime("%Y%m%d")
    raw = retry(
        lambda: ak.stock_zh_index_daily_em(
            symbol=symbol, start_date=start_date, end_date=target_date
        )
    )
    if raw.empty:
        raise ValueError(f"{name} 返回空行情")
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    target = raw[raw["date"].dt.strftime("%Y%m%d") == target_date]
    if target.empty:
        raise ValueError(f"{name} 缺少 {target_date}")
    pos = int(target.index[-1])
    close = float(raw.loc[pos, "close"])
    amount = float(raw.loc[pos, "amount"]) / 1e8
    daily_return = close / float(raw.loc[pos - 1, "close"]) - 1
    return {
        "日期": target_dt.strftime("%Y-%m-%d"),
        "指标": name,
        "数据代码": symbol,
        "收盘点位": close,
        "涨跌幅": daily_return,
        "成交额_亿元": amount,
        "数据来源": "AKShare/东方财富指数历史行情",
    }


def write_outputs(target_date: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_label = datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d")

    hot = pd.DataFrame(
        [fetch_stock_row(*item, target_date) for item in HOT_STOCKS]
    ).sort_values(["成交额_亿元", "股票代码"], ascending=[False, True])
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

    index_defs = [
        ("上证50", "sh000016"),
        ("微盘代理（国证2000）", "sz399303"),
        ("中证全指", "csi000985"),
    ]
    index_rows: list[dict[str, object]] = []
    for name, symbol in index_defs:
        try:
            index_rows.append(fetch_index_row(name, symbol, target_date))
        except Exception as exc:
            logging.error("指数获取失败 %s: %s", name, exc)
            index_rows.append(
                {
                    "日期": date_label,
                    "指标": name,
                    "数据代码": symbol,
                    "收盘点位": pd.NA,
                    "涨跌幅": pd.NA,
                    "成交额_亿元": pd.NA,
                    "数据来源": f"获取失败: {exc}",
                }
            )
    indexes = pd.DataFrame(index_rows)

    hot_amount = float(hot["成交额_亿元"].sum())
    summary = pd.DataFrame(
        [
            {
                "日期": date_label,
                **BREADTH,
                "成交额超百亿个股数": len(hot),
                "百亿个股成交额合计_亿元": hot_amount,
                "百亿个股成交集中度": hot_amount / BREADTH["全部A股成交额_亿元"],
                "市场宽度": (BREADTH["上涨家数"] - BREADTH["下跌家数"])
                / (BREADTH["上涨家数"] + BREADTH["下跌家数"]),
                "数据口径": "市场宽度与三市成交额取北京商报收盘统计；百亿个股行情优先AKShare，失败时采用交叉核验公开数据",
            }
        ]
    )

    suffix = target_date
    indexes.to_csv(DATA_DIR / f"market_indexes_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    summary.to_csv(DATA_DIR / f"market_breadth_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    hot.to_csv(DATA_DIR / f"turnover_100bn_stocks_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    industry.to_csv(DATA_DIR / f"turnover_100bn_industries_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")

    logging.info(
        "完成 %s: 上涨 %s, 下跌 %s, 涨停 %s, 跌停 %s, 百亿个股 %s",
        date_label,
        BREADTH["上涨家数"],
        BREADTH["下跌家数"],
        BREADTH["涨停家数"],
        BREADTH["跌停家数"],
        len(hot),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股每日市场监控快照（审核版）")
    parser.add_argument("--target-date", default=DEFAULT_TARGET_DATE, help="YYYYMMDD")
    parser.add_argument("--workers", type=int, default=1, help="保留兼容参数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    write_outputs(args.target_date)


if __name__ == "__main__":
    main()
