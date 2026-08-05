#!/usr/bin/env python3
"""Fast current-day build for the 2026-08-05 workbook."""
from __future__ import annotations

from datetime import datetime
import json
import logging

import pandas as pd
import requests

from build_monitor_20260805 import OUT_DIR, fetch_a_share_snapshot, fetch_limit_counts, write_csv

TARGET_DATE = "20260805"


def fetch_tencent_indexes() -> pd.DataFrame:
    url = "https://qt.gtimg.cn/q=sh000016,sh000985"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    text = response.content.decode("gbk", errors="ignore")
    rows = []
    for line in text.splitlines():
        if '="' not in line:
            continue
        payload = line.split('="', 1)[1].rsplit('"', 1)[0]
        parts = payload.split("~")
        if len(parts) < 38:
            continue
        code = parts[2]
        name = "上证50" if code == "000016" else "中证全指"
        stamp = parts[30] if len(parts) > 30 else ""
        date = stamp[:8] if len(stamp) >= 8 else TARGET_DATE
        rows.append({
            "日期": datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d"),
            "指标": name,
            "数据代码": code,
            "收盘点位": float(parts[3]),
            "涨跌幅": float(parts[32]) / 100.0,
            "成交额（亿元）": float(parts[37]) / 10000.0,
            "数据源": "腾讯行情",
        })
    return pd.DataFrame(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = fetch_a_share_snapshot(TARGET_DATE)
    hot = snapshot[snapshot["成交额_元"] >= 10_000_000_000].copy()
    hot.insert(0, "当日排名", range(1, len(hot) + 1))
    limit_today = fetch_limit_counts([TARGET_DATE])
    indexes = fetch_tencent_indexes()

    market_amount = float(snapshot["成交额_元"].sum() / 1e8)
    limit_up = limit_today.iloc[0].get("涨停家数") if not limit_today.empty else None
    limit_down = limit_today.iloc[0].get("跌停家数") if not limit_today.empty else None
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
        "数据源": "东方财富全A收盘快照+腾讯指数+涨跌停池",
    }])
    write_csv(summary, "market_summary_20260805.csv")
    write_csv(snapshot, "all_a_snapshot_20260805.csv")
    write_csv(hot, "turnover_100bn_stocks_20260805.csv")
    write_csv(limit_today, "limit_counts_20260805.csv")
    write_csv(indexes, "index_snapshot_20260805.csv")
    metadata = {
        "built_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "snapshot_rows": len(snapshot),
        "hot_rows": len(hot),
        "index_rows": len(indexes),
    }
    (OUT_DIR / "current_fast_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logging.info("fast current build completed: %s", metadata)


if __name__ == "__main__":
    main()
