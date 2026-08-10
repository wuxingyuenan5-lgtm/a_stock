#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import time
import pandas as pd
from curl_cffi import requests

OUT = Path("data/innovation_drug_history_2026.csv")
START = "20260105"
END = "20260810"
BOARD_CODE = "BK1106"
BOARD_NAME = "创新药"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
HOSTS = [
    "https://push2his.eastmoney.com",
    "https://33.push2his.eastmoney.com",
    "https://54.push2his.eastmoney.com",
    "https://push2delay.eastmoney.com",
]


def fetch_history() -> pd.DataFrame:
    params = {
        "secid": f"90.{BOARD_CODE}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "beg": START,
        "end": END,
        "lmt": "100000",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    errors: list[str] = []
    for host in HOSTS:
        for attempt in range(1, 4):
            try:
                response = requests.get(
                    f"{host}/api/qt/stock/kline/get",
                    params=params,
                    headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
                    impersonate="chrome",
                    timeout=30,
                    verify=False,
                )
                response.raise_for_status()
                payload = response.json()
                lines = (payload.get("data") or {}).get("klines") or []
                if not lines:
                    raise RuntimeError("empty klines")
                parsed = [line.split(",") for line in lines]
                columns = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
                frame = pd.DataFrame(parsed, columns=columns)
                frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
                for c in columns[1:]:
                    frame[c] = pd.to_numeric(frame[c], errors="coerce")
                return frame.dropna(subset=["日期", "成交额"]).sort_values("日期").reset_index(drop=True)
            except Exception as exc:
                errors.append(f"{host}#{attempt}:{exc}")
                time.sleep(attempt * 0.8)
    raise RuntimeError("innovation drug kline failed: " + " | ".join(errors))


def main() -> None:
    hist = fetch_history()
    out = pd.DataFrame({
        "日期": hist["日期"].dt.strftime("%Y-%m-%d"),
        "口径名称": BOARD_NAME,
        "板块代码": BOARD_CODE,
        "收盘指数": hist["收盘"],
        "成交额_亿元": hist["成交额"] / 1e8,
        "日收益率": hist["涨跌幅"] / 100.0,
        "换手率": hist["换手率"] / 100.0,
        "来源": "东方财富概念板块 BK1106 / 历史K线接口",
    })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig", float_format="%.8f")
    print(f"board={BOARD_CODE} rows={len(out)} last={out.iloc[-1].to_dict() if len(out) else None}")


if __name__ == "__main__":
    main()
