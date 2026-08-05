#!/usr/bin/env python3
"""Fetch Choice Micro-cap Index (800007.EI) history through 2026-08-05."""
from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import time

import pandas as pd
from curl_cffi import requests

OUT_DIR = Path("data/monitor_20260805")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    hosts = [
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "https://33.push2his.eastmoney.com/api/qt/stock/kline/get",
        "https://28.push2his.eastmoney.com/api/qt/stock/kline/get",
        "https://7.push2his.eastmoney.com/api/qt/stock/kline/get",
    ]
    params = {
        "secid": "47.800007",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "klt": 101,
        "fqt": 0,
        "lmt": 10000,
        "beg": "20260101",
        "end": "20260805",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    last_error = None
    payload = None
    used_host = None
    for attempt in range(5):
        for host in hosts:
            try:
                response = requests.get(
                    host,
                    params=params,
                    impersonate="chrome",
                    headers={"Referer":"https://quote.eastmoney.com/","User-Agent":"Mozilla/5.0"},
                    timeout=25,
                )
                response.raise_for_status()
                candidate = response.json()
                if ((candidate.get("data") or {}).get("klines") or []):
                    payload = candidate
                    used_host = host
                    break
            except Exception as exc:
                last_error = exc
        if payload is not None:
            break
        time.sleep(1.5 * (attempt + 1))
    if payload is None:
        error = {"错误": str(last_error), "状态": "供应商历史接口未返回数据"}
        (OUT_DIR / "choice_history_error.json").write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(str(error))

    rows = []
    for line in (payload["data"]["klines"] or []):
        p = str(line).split(",")
        if len(p) < 11:
            continue
        rows.append({
            "日期": p[0],
            "Choice微盘收盘": float(p[2]),
            "Choice微盘成交额（亿元）": float(p[6]) / 1e8,
            "Choice微盘涨跌幅": float(p[8]) / 100.0,
            "数据代码": "800007.EI",
            "数据来源": "东方财富历史接口",
        })
    frame = pd.DataFrame(rows).sort_values("日期", ascending=False)
    frame.to_csv(OUT_DIR / "choice_microcap_history_2026.csv", index=False, encoding="utf-8-sig", float_format="%.10f")
    metadata = {
        "built_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "rows": len(frame),
        "latest_date": frame.iloc[0]["日期"] if not frame.empty else None,
        "host": used_host,
    }
    (OUT_DIR / "choice_history_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Choice history completed: %s", metadata)


if __name__ == "__main__":
    main()
