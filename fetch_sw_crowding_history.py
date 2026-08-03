#!/usr/bin/env python3
"""Fetch authoritative Shenwan L2 crowding history from the official daily analysis table."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import akshare as ak
import pandas as pd

import update_sw_industry as base

DATA_DIR = Path("data")
TARGET_NAMES = ["通信设备", "计算机设备", "元件", "半导体"]


def normalize_code(value: object) -> str:
    return str(value).strip().replace(".0", "").split(".")[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="20260101")
    parser.add_argument("--end-date", default="20260803")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raw = base.retry(
        lambda: ak.index_analysis_daily_sw(
            symbol="二级行业", start_date=args.start_date, end_date=args.end_date
        ),
        attempts=5,
        delay=2.0,
    )
    required = {
        "指数代码", "指数名称", "发布日期", "成交量", "换手率", "均价", "成交额占比"
    }
    if raw.empty or not required.issubset(raw.columns):
        raise RuntimeError(f"申万二级行业日报字段异常: {list(raw.columns)}")

    frame = raw[list(required)].copy()
    frame["指数代码"] = frame["指数代码"].map(normalize_code)
    frame["发布日期"] = pd.to_datetime(frame["发布日期"], errors="coerce")
    for column in ["成交量", "换手率", "均价", "成交额占比"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[frame["指数名称"].isin(TARGET_NAMES)].dropna(subset=["发布日期"])
    frame["成交额_亿元"] = frame["成交量"] * frame["均价"]
    frame["换手率"] = frame["换手率"] / 100.0
    frame["成交额占比"] = frame["成交额占比"] / 100.0

    output = pd.DataFrame({"日期": sorted(frame["发布日期"].dt.strftime("%Y-%m-%d").unique())})
    for name in TARGET_NAMES:
        sub = frame[frame["指数名称"].eq(name)][
            ["发布日期", "指数代码", "成交额_亿元", "换手率", "成交额占比"]
        ].copy()
        sub["日期"] = sub["发布日期"].dt.strftime("%Y-%m-%d")
        sub = sub.sort_values("发布日期").drop_duplicates("日期", keep="last")
        sub = sub.rename(
            columns={
                "指数代码": f"{name}指数代码",
                "成交额_亿元": f"{name}成交额_亿元",
                "换手率": f"{name}换手率",
                "成交额占比": f"{name}成交额占比",
            }
        )
        output = output.merge(
            sub[[
                "日期", f"{name}指数代码", f"{name}成交额_亿元",
                f"{name}换手率", f"{name}成交额占比",
            ]],
            on="日期", how="left",
        )

    amount_cols = [f"{name}成交额_亿元" for name in TARGET_NAMES]
    share_cols = [f"{name}成交额占比" for name in TARGET_NAMES]
    output["四行业成交额合计_亿元"] = output[amount_cols].sum(axis=1, min_count=4)
    output["四行业成交额占比"] = output[share_cols].sum(axis=1, min_count=4)
    output.sort_values("日期", inplace=True)

    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "sw_crowding_official_history_2026.csv"
    output.to_csv(out, index=False, encoding="utf-8-sig", float_format="%.8f")
    quality = pd.DataFrame([
        {"检查项": "申万二级日报原始行数", "数值": len(raw), "状态": "通过", "说明": f"{args.start_date}-{args.end_date}"},
        {"检查项": "目标行业有效交易日数", "数值": len(output), "状态": "通过" if len(output) > 100 else "提示", "说明": ",".join(TARGET_NAMES)},
        {"检查项": "换手率口径", "数值": "申万官方日报", "状态": "通过", "说明": "非东方财富板块换手率"},
        {"检查项": "成交额计算", "数值": "成交量×均价", "状态": "通过", "说明": "亿股×元=亿元"},
        {"检查项": "成交额占比口径", "数值": "申万官方日报", "状态": "通过", "说明": "四行业占比为各行业占比相加"},
    ])
    quality.to_csv(DATA_DIR / "sw_crowding_official_quality_2026.csv", index=False, encoding="utf-8-sig")
    logging.info("申万拥挤度历史完成: %s 行", len(output))


if __name__ == "__main__":
    main()
