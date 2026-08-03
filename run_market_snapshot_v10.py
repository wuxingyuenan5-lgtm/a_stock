#!/usr/bin/env python3
"""Non-blocking exact-date runner.

All market data is updated even when the Choice micro-cap vendor endpoint is
temporarily unavailable. The Choice row is left explicitly blank; no custom
portfolio or alternate index is substituted.
"""
from __future__ import annotations

from datetime import datetime
import logging

import pandas as pd

import build_market_snapshot as base
import run_market_snapshot_v2 as patched  # applies official universe/current quotes/fast SW map/vendor limits
import run_market_snapshot_v3 as report
import run_market_snapshot_v5 as clean_rank
import run_market_snapshot_v6 as v6


def fetch_indices_nonblocking(target_date: str, stocks: pd.DataFrame) -> pd.DataFrame:
    del stocks
    parsed = patched._parse_tencent_index(
        patched._fetch_tencent_batch(["sh000016", "sh000985"]), target_date
    )
    rows: list[dict[str, object]] = []
    for label, full_code in (("上证50", "sh000016"), ("中证全指", "sh000985")):
        item = parsed.get(full_code)
        if not item or item["close"] is None:
            raise RuntimeError(f"腾讯指数行情缺失: {label} {full_code}")
        rows.append({
            "日期": datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d"),
            "指标": label,
            "数据代码": "000016.SH" if label == "上证50" else "000985.CSI",
            "收盘点位": item["close"],
            "涨跌幅": item["pct"],
            "成交额_亿元": item["amount_yi"],
            "数据来源": "腾讯财经批量行情",
            "数据口径": "指数行情成交额",
            "替代状态": "原始权威指数",
        })

    try:
        choice = v6.fetch_choice_micro_index(target_date)
    except Exception as exc:
        logging.warning("Choice微盘股指数供应商暂缺，不阻塞日报: %s", exc)
        choice = {
            "日期": datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d"),
            "指标": "Choice微盘股指数",
            "数据代码": "800007.EI",
            "收盘点位": pd.NA,
            "涨跌幅": pd.NA,
            "成交额_亿元": pd.NA,
            "数据来源": "东方财富Choice指数行情",
            "数据口径": "Choice正式发布指数行情；当日供应商接口暂缺",
            "替代状态": "供应商暂缺；未使用自建替代",
        }
    rows.insert(1, choice)
    return pd.DataFrame(rows)


def main() -> None:
    args = base.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base.fetch_index_snapshot = fetch_indices_nonblocking
    report.write_outputs_safe(args.target_date, args.workers)
    clean_rank.postprocess_industry_ranking(args.target_date)
    v6.append_daily_history(args.target_date)
    logging.info("完成非阻塞市场更新: %s", args.target_date)


if __name__ == "__main__":
    main()
