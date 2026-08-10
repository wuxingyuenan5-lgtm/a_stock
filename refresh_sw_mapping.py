#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone

from market_monitor.sw_mapping import DEFAULT_MAPPING_PATH, refresh_mapping


def cache_age_days() -> float | None:
    if not DEFAULT_MAPPING_PATH.exists():
        return None
    modified = datetime.fromtimestamp(DEFAULT_MAPPING_PATH.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - modified).total_seconds() / 86400


def main() -> None:
    age = cache_age_days()
    if age is not None and age < 7:
        print(f"Shenwan mapping cache is fresh: age={age:.2f} days; skip refresh")
        return
    mapping = refresh_mapping()
    print(f"refreshed Shenwan mapping rows={len(mapping)} previous_age_days={age}")


if __name__ == "__main__":
    main()
