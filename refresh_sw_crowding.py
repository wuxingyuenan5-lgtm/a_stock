#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from market_monitor.sw_cache import refresh_sw_cache


def main() -> None:
    target = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    frame = refresh_sw_cache(target)
    print(f"refreshed Shenwan crowding cache target={target} rows={len(frame)}")


if __name__ == "__main__":
    main()
