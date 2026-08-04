#!/usr/bin/env python3
"""Fetch one exact-date crowding row using resilient multi-host K-line access."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from backfill_market_and_crowding import fetch_em_kline

DATA_DIR = Path("data")
BOARDS = {
    "通信设备": "90.BK0448",
    "计算机设备": "90.BK0735",
    "元件": "90.BK0459",
    "半导体": "90.BK1036",
}
CSI_ALL_SHARE = "1.000985"


def exact_row(secid: str, target_date: str) -> dict[str, float]:
    target_dt = datetime.strptime(target_date, "%Y%m%d")
    start = (target_dt - timedelta(days=20)).strftime("%Y-%m-%d")
    end = target_dt.strftime("%Y-%m-%d")
    frame = fetch_em_kline(secid, start, end).copy()
    frame["日期文本"] = frame["日期"].dt.strftime("%Y%m%d")
    row = frame[frame["日期文本"].eq(target_date)]
    if row.empty:
        raise RuntimeError(f"{secid} 缺少目标日 {target_date}")
    item = row.iloc[-1]
    amount = pd.to_numeric(item["成交额"], errors="coerce")
    turnover = pd.to_numeric(item["换手率"], errors="coerce")
    if pd.isna(amount) or pd.isna(turnover):
        raise RuntimeError(f"{secid} 目标日成交额或换手率为空")
    return {"成交额_亿元": float(amount) / 1e8, "换手率": float(turnover) / 100}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", required=True, help="YYYYMMDD")
    args = parser.parse_args()
    target = args.target_date

    boards = {name: exact_row(secid, target) for name, secid in BOARDS.items()}
    market = exact_row(CSI_ALL_SHARE, target)
    total_market = market["成交额_亿元"]
    four_amount = sum(item["成交额_亿元"] for item in boards.values())

    row = {
        "日期": datetime.strptime(target, "%Y%m%d").strftime("%Y-%m-%d"),
        "通信设备成交额_亿元": boards["通信设备"]["成交额_亿元"],
        "通信设备换手率": boards["通信设备"]["换手率"],
        "通信设备成交额占比": boards["通信设备"]["成交额_亿元"] / total_market,
        "计算机设备成交额_亿元": boards["计算机设备"]["成交额_亿元"],
        "计算机设备换手率": boards["计算机设备"]["换手率"],
        "元件成交额_亿元": boards["元件"]["成交额_亿元"],
        "元件换手率": boards["元件"]["换手率"],
        "半导体成交额_亿元": boards["半导体"]["成交额_亿元"],
        "半导体换手率": boards["半导体"]["换手率"],
        "中证全指成交额_亿元": total_market,
        "四行业成交额合计_亿元": four_amount,
        "四行业成交额占比": four_amount / total_market,
    }

    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / f"industry_crowding_daily_{target}.csv"
    pd.DataFrame([row]).to_csv(out, index=False, encoding="utf-8-sig", float_format="%.8f")
    print(pd.DataFrame([row]).to_string(index=False))
    print(out)


if __name__ == "__main__":
    main()
