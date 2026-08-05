#!/usr/bin/env python3
"""Build historical turnover >= RMB10bn completion data through 2026-08-05."""
from __future__ import annotations

from datetime import datetime
import json
import logging

from build_monitor_20260805 import OUT_DIR, build_historical_100bn, write_csv


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary, details, failures = build_historical_100bn("20260105", "20260805")
    write_csv(summary, "history_100bn_daily_20260105_20260805.csv")
    write_csv(details, "history_100bn_details_20260105_20260805.csv")
    if not failures.empty:
        write_csv(failures, "history_100bn_failures.csv")
    metadata = {
        "built_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "history_hot_rows": len(details),
        "history_failures": len(failures),
    }
    (OUT_DIR / "history_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logging.info("historical build completed: %s", metadata)


if __name__ == "__main__":
    main()
