#!/usr/bin/env python3
"""Fetch 2026 industry crowding history from public Eastmoney board indices.

The charts intentionally reproduce the user's analytical structure rather
than label these public board indices as Wind indices.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from backfill_market_and_crowding import fetch_em_kline

DATA_DIR = Path("data")

BOARDS = [
    ("通信设备", "90.BK0448"),
    ("计算机设备", "90.BK0735"),
    ("元件", "90.BK0459"),
    ("半导体", "90.BK1036"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-07-31")
    args = parser.parse_args()
    DATA_DIR.mkdir(exist_ok=True)

    market = fetch_em_kline("1.000985", args.start_date, args.end_date)
    market = market[["日期", "成交额"]].copy()
    market["日期"] = market["日期"].dt.strftime("%Y-%m-%d")
    market.rename(columns={"成交额": "中证全指成交额_元"}, inplace=True)

    result = market
    quality_rows = []
    for name, secid in BOARDS:
        try:
            frame = fetch_em_kline(secid, args.start_date, args.end_date)
            frame["日期"] = frame["日期"].dt.strftime("%Y-%m-%d")
            frame[f"{name}成交额_亿元"] = frame["成交额"] / 1e8
            frame[f"{name}换手率"] = frame["换手率"] / 100.0
            result = result.merge(
                frame[["日期", f"{name}成交额_亿元", f"{name}换手率"]],
                on="日期",
                how="left",
            )
            quality_rows.append([name, secid, int(frame["成交额"].notna().sum()), "通过", "东方财富行业板块日线"])
        except Exception as exc:
            result[f"{name}成交额_亿元"] = pd.NA
            result[f"{name}换手率"] = pd.NA
            quality_rows.append([name, secid, 0, "失败", str(exc)])

    result["中证全指成交额_亿元"] = result["中证全指成交额_元"] / 1e8
    result.drop(columns=["中证全指成交额_元"], inplace=True)
    result["通信设备成交额占比"] = result["通信设备成交额_亿元"] / result["中证全指成交额_亿元"]
    amount_cols = [f"{name}成交额_亿元" for name, _ in BOARDS]
    result["四行业成交额合计_亿元"] = result[amount_cols].sum(axis=1, min_count=len(amount_cols))
    result["四行业成交额占比"] = result["四行业成交额合计_亿元"] / result["中证全指成交额_亿元"]
    result.sort_values("日期", inplace=True)
    result.to_csv(DATA_DIR / "industry_crowding_history.csv", index=False, encoding="utf-8-sig", float_format="%.8f")

    quality = pd.DataFrame(quality_rows, columns=["板块", "数据代码", "历史行数", "状态", "说明"])
    quality.to_csv(DATA_DIR / "industry_crowding_quality.csv", index=False, encoding="utf-8-sig")
    logging.info("拥挤度历史完成: %s rows", len(result))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
