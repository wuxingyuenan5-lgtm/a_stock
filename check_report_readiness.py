#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REQUIRED_SW = ["通信设备", "计算机设备", "元件", "半导体"]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(description="Check whether all daily monitor sources are ready for final publication")
    p.add_argument("--target-date", required=True)
    p.add_argument("--output-dir", default=None)
    args = p.parse_args()

    out = Path(args.output_dir or f"output/{args.target_date}")
    payload = load(out / "daily_payload.json")
    validation = load(out / "validation.json")

    reasons: list[str] = []

    if payload.get("date") != args.target_date:
        reasons.append(f"payload_date={payload.get('date')}")

    # Core market checks must all pass. These are already FAIL-level in the pipeline.
    for check in validation.get("checks", []):
        if check.get("level") == "FAIL" and not check.get("ok"):
            reasons.append(f"core:{check.get('name')}")

    indices = payload.get("indices") or {}
    for name in ("上证50", "Choice微盘", "中证全指"):
        item = indices.get(name) or {}
        if item.get("date") != args.target_date or item.get("close") is None:
            reasons.append(f"index:{name}:{item.get('date')}:{item.get('status')}")

    sw = payload.get("sw_crowding") or {}
    if sw.get("date") != args.target_date:
        reasons.append(f"sw_date={sw.get('date')}")
    targets = sw.get("targets") or {}
    for name in REQUIRED_SW:
        item = targets.get(name) or {}
        if item.get("date") != args.target_date:
            reasons.append(f"sw:{name}:date={item.get('date')}")
        if item.get("amount_share_of_a") is None:
            reasons.append(f"sw:{name}:share_missing")
        if item.get("turnover") is None:
            reasons.append(f"sw:{name}:turnover_missing")

    innovation = payload.get("innovation_drug") or {}
    if innovation.get("date") != args.target_date:
        reasons.append(f"innovation_date={innovation.get('date')}")
    if innovation.get("amount_100m") is None:
        reasons.append("innovation_amount_missing")
    if innovation.get("amount_share_of_a") is None:
        reasons.append("innovation_share_missing")
    if innovation.get("turnover") is None:
        reasons.append("innovation_turnover_missing")

    mapping_check = next((x for x in validation.get("checks", []) if x.get("name") == "sw_mapping_cache"), None)
    if mapping_check and not mapping_check.get("ok"):
        reasons.append("sw_mapping_cache_missing")

    ready = not reasons
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    result = {
        "date": args.target_date,
        "observed_at": observed_at,
        "ready": ready,
        "reasons": reasons,
        "validation_status": validation.get("status"),
    }
    (out / "readiness.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if ready else 3)


if __name__ == "__main__":
    main()
