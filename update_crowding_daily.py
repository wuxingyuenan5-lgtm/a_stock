#!/usr/bin/env python3
"""Fetch one exact-date industry crowding row from public Eastmoney board data."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import time

import pandas as pd
import requests

DATA_DIR = Path("data")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

BOARDS = {
    "通信设备": "90.BK0448",
    "计算机设备": "90.BK0735",
    "元件": "90.BK0459",
    "半导体": "90.BK1036",
}
CSI_ALL_SHARE = "1.000985"


def fetch_kline_row(secid: str, target_date: str) -> dict[str, float | str]:
    target_dt = datetime.strptime(target_date, "%Y%m%d")
    begin = (target_dt - timedelta(days=20)).strftime("%Y%m%d")
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,
        "fqt": 0,
        "beg": begin,
        "end": target_date,
        "lmt": 100,
    }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or {}
            rows = data.get("klines") or []
            for line in rows:
                values = line.split(",")
                if values[0].replace("-", "") == target_date:
                    return {
                        "日期": values[0],
                        "成交额_亿元": float(values[6]) / 1e8,
                        "换手率": float(values[10]) / 100,
                    }
            raise RuntimeError(f"{secid} 缺少目标日 {target_date}")
        except Exception as exc:
            last_error = exc
            time.sleep(attempt * 1.2)
    assert last_error is not None
    raise last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", required=True, help="YYYYMMDD")
    args = parser.parse_args()

    target = args.target_date
    board_rows = {name: fetch_kline_row(secid, target) for name, secid in BOARDS.items()}
    csi = fetch_kline_row(CSI_ALL_SHARE, target)
    total_market = float(csi["成交额_亿元"])
    four_amount = sum(float(board_rows[name]["成交额_亿元"]) for name in BOARDS)

    row = {
        "日期": datetime.strptime(target, "%Y%m%d").strftime("%Y-%m-%d"),
        "通信设备成交额_亿元": board_rows["通信设备"]["成交额_亿元"],
        "通信设备换手率": board_rows["通信设备"]["换手率"],
        "通信设备成交额占比": float(board_rows["通信设备"]["成交额_亿元"]) / total_market,
        "计算机设备成交额_亿元": board_rows["计算机设备"]["成交额_亿元"],
        "计算机设备换手率": board_rows["计算机设备"]["换手率"],
        "元件成交额_亿元": board_rows["元件"]["成交额_亿元"],
        "元件换手率": board_rows["元件"]["换手率"],
        "半导体成交额_亿元": board_rows["半导体"]["成交额_亿元"],
        "半导体换手率": board_rows["半导体"]["换手率"],
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
