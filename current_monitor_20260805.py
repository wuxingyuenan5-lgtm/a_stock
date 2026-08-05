#!/usr/bin/env python3
"""Build current-day and small historical-gap data for 2026-08-05."""
from __future__ import annotations

from datetime import datetime
import json
import logging
import traceback

import pandas as pd

from build_monitor_20260805 import (
    OUT_DIR,
    fetch_a_share_snapshot,
    fetch_kline,
    fetch_limit_counts,
    write_csv,
)

TARGET_DATE = "20260805"
HISTORY_START = "20260105"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, str]] = []

    snapshot = fetch_a_share_snapshot(TARGET_DATE)
    hot = snapshot[snapshot["成交额_元"] >= 10_000_000_000].copy()
    hot.insert(0, "当日排名", range(1, len(hot) + 1))
    limit_today = fetch_limit_counts([TARGET_DATE])
    limit_up = limit_today.iloc[0].get("涨停家数") if not limit_today.empty else None
    limit_down = limit_today.iloc[0].get("跌停家数") if not limit_today.empty else None
    market_amount = float(snapshot["成交额_元"].sum() / 1e8)
    summary = pd.DataFrame([{
        "日期": "2026-08-05",
        "上涨家数": int((snapshot["涨跌幅"] > 0).sum()),
        "下跌家数": int((snapshot["涨跌幅"] < 0).sum()),
        "平盘家数": int((snapshot["涨跌幅"] == 0).sum()),
        "涨停家数": limit_up,
        "跌停家数": limit_down,
        "有效股票数": len(snapshot),
        "全部A股成交额（亿元）": market_amount,
        "百亿成交股数": len(hot),
        "百亿成交额（亿元）": float(hot["成交额（亿元）"].sum()),
        "百亿成交集中度": float(hot["成交额（亿元）"].sum()) / market_amount if market_amount else None,
        "数据源": "东方财富全A收盘快照+涨跌停池",
    }])
    write_csv(summary, "market_summary_20260805.csv")
    write_csv(snapshot, "all_a_snapshot_20260805.csv")
    write_csv(hot, "turnover_100bn_stocks_20260805.csv")
    write_csv(limit_today, "limit_counts_20260805.csv")

    index_frames: list[pd.DataFrame] = []
    for secid, name, start in [
        ("1.000016", "上证50", "20260801"),
        ("1.000985", "中证全指", "20260801"),
        ("47.800007", "Choice微盘", HISTORY_START),
    ]:
        try:
            frame = fetch_kline(secid, name, start, TARGET_DATE)
            if not frame.empty:
                index_frames.append(frame)
        except Exception as exc:
            logging.exception("index history failed: %s", name)
            errors.append({"模块": f"指数历史-{name}", "错误": str(exc)})
    if index_frames:
        write_csv(pd.concat(index_frames, ignore_index=True), "index_history_to_20260805.csv")

    try:
        early_dates = [
            "20260105", "20260106", "20260107", "20260108", "20260109", "20260112",
            "20260113", "20260114", "20260115", "20260116", "20260119", "20260120",
        ]
        write_csv(fetch_limit_counts(early_dates), "early_limit_counts_20260105_20260120.csv")
    except Exception as exc:
        logging.exception("early limit counts failed")
        errors.append({"模块": "早期涨跌停", "错误": str(exc)})

    if errors:
        write_csv(pd.DataFrame(errors), "current_module_errors.csv")
    metadata = {
        "built_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "target_date": TARGET_DATE,
        "snapshot_rows": len(snapshot),
        "hot_rows": len(hot),
        "module_errors": len(errors),
    }
    (OUT_DIR / "current_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logging.info("current build completed: %s", metadata)


if __name__ == "__main__":
    main()
