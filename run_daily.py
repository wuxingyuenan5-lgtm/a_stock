#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_monitor.production import run
from market_monitor.history_preflight import append_index_history
from build_report_data import append_hot_stock_history


def default_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股每日监控一键数据生产")
    parser.add_argument("--target-date", default=default_date(), help="YYYY-MM-DD；正式日更只允许中国时区当天")
    parser.add_argument("--config", default="config/market_monitor.json")
    parser.add_argument("--refresh-mapping", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    today = default_date()
    if args.target_date != today:
        raise SystemExit(
            f"daily pipeline uses a current-day stock snapshot, so target_date must be {today}; "
            "use the historical backfill workflow for older dates"
        )
    result = run(target_date=args.target_date, config_path=Path(args.config), refresh_mapping=args.refresh_mapping)
    payload = result["payload"]
    append_index_history(
        Path("data/history/indices_history.csv"),
        list((payload.get("indices") or {}).values()),
    )
    append_hot_stock_history(
        Path("data/history/hot_stocks.csv"),
        args.target_date,
        payload.get("hot_stocks") or [],
    )
    validation = result["validation"]
    print(f"completed date={args.target_date} status={validation['status']} output={result['output_dir']}")


if __name__ == "__main__":
    main()
