#!/usr/bin/env python3
"""Fill the first 12 missing limit-up/down sessions in January 2026."""
from __future__ import annotations

from datetime import datetime
import json
import logging

from build_monitor_20260805 import OUT_DIR, fetch_limit_counts, write_csv


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dates = [
        "20260105", "20260106", "20260107", "20260108", "20260109", "20260112",
        "20260113", "20260114", "20260115", "20260116", "20260119", "20260120",
    ]
    data = fetch_limit_counts(dates)
    write_csv(data, "early_limit_counts_20260105_20260120.csv")
    (OUT_DIR / "early_limits_metadata.json").write_text(
        json.dumps({"built_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "rows": len(data)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logging.info("early limit build completed: %s rows", len(data))


if __name__ == "__main__":
    main()
