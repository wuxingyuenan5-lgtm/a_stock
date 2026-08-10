#!/usr/bin/env python3
from market_monitor.sw_mapping import refresh_mapping


def main() -> None:
    mapping = refresh_mapping()
    print(f"refreshed Shenwan mapping rows={len(mapping)}")


if __name__ == "__main__":
    main()
