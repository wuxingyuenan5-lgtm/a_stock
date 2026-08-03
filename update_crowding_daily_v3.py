#!/usr/bin/env python3
"""Fetch one exact-date crowding row from current close snapshots."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
import random
import time

import pandas as pd
import requests

import build_market_snapshot as base
import run_market_snapshot_v2 as market_source
import run_market_snapshot_v6 as v6

DATA_DIR = Path("data")
BEIJING = timezone(timedelta(hours=8))
BOARDS = {
    "通信设备": "90.BK0448",
    "计算机设备": "90.BK0735",
    "元件": "90.BK0459",
    "半导体": "90.BK1036",
}
HOSTS = [
    "https://push2.eastmoney.com",
    "https://22.push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
]


def fetch_board_current(name: str, secid: str, target_date: str) -> dict[str, float]:
    params = {
        "secid": secid,
        "fields": "f43,f48,f57,f58,f60,f86,f124,f168,f170",
        "invt": 2,
        "fltt": 2,
    }
    errors: list[str] = []
    for host in HOSTS:
        for attempt in range(1, 4):
            try:
                response = requests.get(
                    f"{host}/api/qt/stock/get",
                    params=params,
                    headers={"User-Agent": base.UA, "Referer": "https://quote.eastmoney.com/"},
                    timeout=25,
                )
                response.raise_for_status()
                data = response.json().get("data") or {}
                actual_name = str(data.get("f58") or "").strip()
                amount = pd.to_numeric(data.get("f48"), errors="coerce")
                turnover = pd.to_numeric(data.get("f168"), errors="coerce")
                quote_date = v6._quote_date(data.get("f86")) or v6._quote_date(data.get("f124"))
                if not actual_name or name not in actual_name:
                    raise RuntimeError(f"name={actual_name!r}")
                if quote_date and quote_date != target_date:
                    raise RuntimeError(f"date={quote_date}")
                if not quote_date and target_date != datetime.now(BEIJING).strftime("%Y%m%d"):
                    raise RuntimeError("missing verifiable date")
                if pd.isna(amount) or float(amount) <= 0:
                    raise RuntimeError("amount missing")
                if pd.isna(turnover) or float(turnover) < 0:
                    raise RuntimeError("turnover missing")
                return {
                    "成交额_亿元": float(amount) / 1e8,
                    "换手率": float(turnover) / 100,
                }
            except Exception as exc:
                errors.append(f"{host}#{attempt}: {exc}")
                time.sleep(0.7 * attempt + random.uniform(0.1, 0.4))
    raise RuntimeError(f"{name} current quote failed: {' | '.join(errors)}")


def fetch_csi_amount(target_date: str) -> float:
    parsed = market_source._parse_tencent_index(
        market_source._fetch_tencent_batch(["sh000985"]), target_date
    )
    item = parsed.get("sh000985")
    if not item or item.get("amount_yi") is None:
        raise RuntimeError("中证全指目标日成交额缺失")
    return float(item["amount_yi"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", required=True, help="YYYYMMDD")
    args = parser.parse_args()
    target = args.target_date

    boards = {name: fetch_board_current(name, secid, target) for name, secid in BOARDS.items()}
    total_market = fetch_csi_amount(target)
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
