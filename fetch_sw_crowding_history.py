#!/usr/bin/env python3
"""Fetch four authoritative Shenwan L2 crowding histories from the official daily table."""
from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
import time

import pandas as pd
import requests

DATA_DIR = Path("data")
TARGETS = {
    "通信设备": "801102",
    "计算机设备": "801101",
    "元件": "801083",
    "半导体": "801081",
}
URL = "https://www.swsresearch.com/institute-sw/api/index_analysis/index_analysis_report/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
}


def get_page(code: str, start_date: str, end_date: str, page: int, page_size: int = 500) -> dict:
    params = {
        "page": str(page),
        "page_size": str(page_size),
        "index_type": "二级行业",
        "start_date": start_date,
        "end_date": end_date,
        "type": "DAY",
        "swindexcode": code,
    }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = requests.get(URL, params=params, headers=HEADERS, verify=False, timeout=45)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("data"):
                raise RuntimeError(f"empty data: {payload}")
            return payload
        except Exception as exc:
            last_error = exc
            time.sleep(attempt * 1.5)
    assert last_error is not None
    raise last_error


def fetch_one(name: str, code: str, start_date: str, end_date: str) -> pd.DataFrame:
    first = get_page(code, start_date, end_date, 1)
    data = first["data"]
    count = int(data.get("count") or 0)
    page_size = 500
    pages = max(1, math.ceil(count / page_size))
    records = list(data.get("results") or [])
    for page in range(2, pages + 1):
        records.extend((get_page(code, start_date, end_date, page, page_size)["data"].get("results") or []))
    frame = pd.DataFrame(records)
    if frame.empty:
        raise RuntimeError(f"{name}({code})无日报数据")
    frame = frame.rename(columns={
        "swindexcode": "指数代码",
        "swindexname": "指数名称",
        "bargaindate": "发布日期",
        "bargainamount": "成交量",
        "turnoverrate": "换手率",
        "meanprice": "均价",
        "bargainsumrate": "成交额占比",
    })
    required = {"指数代码", "指数名称", "发布日期", "成交量", "换手率", "均价", "成交额占比"}
    if not required.issubset(frame.columns):
        raise RuntimeError(f"{name}日报字段异常: {list(frame.columns)}")
    frame = frame[list(required)].copy()
    frame["发布日期"] = pd.to_datetime(frame["发布日期"], errors="coerce")
    for column in ["成交量", "换手率", "均价", "成交额占比"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["发布日期"]).sort_values("发布日期").drop_duplicates("发布日期", keep="last")
    frame["日期"] = frame["发布日期"].dt.strftime("%Y-%m-%d")
    frame[f"{name}指数代码"] = code
    frame[f"{name}成交额_亿元"] = frame["成交量"] * frame["均价"]
    frame[f"{name}换手率"] = frame["换手率"] / 100.0
    frame[f"{name}成交额占比"] = frame["成交额占比"] / 100.0
    return frame[["日期", f"{name}指数代码", f"{name}成交额_亿元", f"{name}换手率", f"{name}成交额占比"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="20260101")
    parser.add_argument("--end-date", default="20260803")
    args = parser.parse_args()
    start = f"{args.start_date[:4]}-{args.start_date[4:6]}-{args.start_date[6:]}"
    end = f"{args.end_date[:4]}-{args.end_date[4:6]}-{args.end_date[6:]}"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    output: pd.DataFrame | None = None
    raw_count = 0
    for name, code in TARGETS.items():
        frame = fetch_one(name, code, start, end)
        raw_count += len(frame)
        output = frame if output is None else output.merge(frame, on="日期", how="outer")
        logging.info("%s %s: %s rows", name, code, len(frame))
    assert output is not None
    output.sort_values("日期", inplace=True)
    amount_cols = [f"{name}成交额_亿元" for name in TARGETS]
    share_cols = [f"{name}成交额占比" for name in TARGETS]
    output["四行业成交额合计_亿元"] = output[amount_cols].sum(axis=1, min_count=4)
    output["四行业成交额占比"] = output[share_cols].sum(axis=1, min_count=4)

    DATA_DIR.mkdir(exist_ok=True)
    output.to_csv(DATA_DIR / "sw_crowding_official_history_2026.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    quality = pd.DataFrame([
        {"检查项": "四个申万二级日报原始行数", "数值": raw_count, "状态": "通过", "说明": f"{start}至{end}"},
        {"检查项": "目标行业有效交易日数", "数值": len(output), "状态": "通过" if len(output) > 100 else "提示", "说明": ",".join(TARGETS)},
        {"检查项": "换手率口径", "数值": "申万官方日报", "状态": "通过", "说明": "非东方财富板块换手率"},
        {"检查项": "成交额计算", "数值": "成交量×均价", "状态": "通过", "说明": "亿股×元=亿元"},
        {"检查项": "成交额占比口径", "数值": "申万官方日报", "状态": "通过", "说明": "四行业占比为各行业占比相加"},
    ])
    quality.to_csv(DATA_DIR / "sw_crowding_official_quality_2026.csv", index=False, encoding="utf-8-sig")
    logging.info("申万拥挤度历史完成: %s 行", len(output))


if __name__ == "__main__":
    main()
