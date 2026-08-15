#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_monitor.history_preflight import preflight_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan and repair recoverable history gaps before HTML production")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--config", default="config/market_monitor.json")
    parser.add_argument("--root", default=".")
    parser.add_argument("--no-repair-indices", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    config = json.loads((root / args.config).read_text(encoding="utf-8"))
    result = preflight_history(
        root=root,
        report_date=args.target_date,
        definitions=config["indices"],
        repair_indices=not args.no_repair_indices,
    )
    output = root / "output" / args.target_date / "history_preflight.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    after = result["after"]
    print(
        f"history_preflight={output} "
        f"index_gaps={len(after['indices'])} denominator_gaps={len(after['market_denominator_dates'])}"
    )


if __name__ == "__main__":
    main()
