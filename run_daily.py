#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

from market_monitor.production import run
from market_monitor.history_preflight import append_index_history
from market_monitor.canonical_promotion import prepare_stage, promote_candidate
from market_monitor.canonical_store import normalize_candidate
from market_monitor.canonical_validation import validate_candidate
from build_report_data import append_hot_stock_history


def default_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股每日监控一键数据生产")
    parser.add_argument("--target-date", default=default_date(), help="YYYY-MM-DD；正式日更只允许中国时区当天")
    parser.add_argument("--config", default="config/market_monitor.json")
    parser.add_argument("--refresh-mapping", action="store_true")
    return parser.parse_args()


def _copy_raw_outputs(stage_output: Path, output_dir: Path) -> None:
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for path in stage_output.iterdir():
        if not path.is_file():
            continue
        shutil.copy2(path, raw_dir / path.name)
        # Keep acquisition evidence available for audit/source manifests. Business
        # display data is built only from promoted Canonical histories.
        shutil.copy2(path, output_dir / path.name)


def main() -> None:
    args = parse_args()
    today = default_date()
    if args.target_date != today:
        raise SystemExit(
            f"daily pipeline uses a current-day stock snapshot, so target_date must be {today}; "
            "use the historical backfill workflow for older dates"
        )

    repo_root = Path(".").resolve()
    config_path = (repo_root / args.config).resolve()
    stage_root = prepare_stage(repo_root, args.target_date)

    result = run(
        target_date=args.target_date,
        config_path=config_path,
        root=stage_root,
        refresh_mapping=args.refresh_mapping,
    )
    payload = result["payload"]
    append_index_history(
        stage_root / "data/history/indices_history.csv",
        list((payload.get("indices") or {}).values()),
    )
    append_hot_stock_history(
        stage_root / "data/history/hot_stocks.csv",
        args.target_date,
        payload.get("hot_stocks") or [],
    )

    output_dir = repo_root / "output" / args.target_date
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_raw_outputs(Path(result["output_dir"]), output_dir)

    normalization = normalize_candidate(stage_root)
    canonical_validation = validate_candidate(stage_root, repo_root, args.target_date)
    canonical_validation["normalization"] = normalization
    validation_path = output_dir / "canonical_validation.json"
    validation_path.write_text(
        json.dumps(canonical_validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    promote_candidate(stage_root, repo_root, args.target_date, canonical_validation)

    payload_validation = result["validation"]
    removed = sum(int(item.get("removed_identical_rows") or 0) for item in normalization.values())
    print(
        f"completed date={args.target_date} payload_status={payload_validation['status']} "
        f"canonical_status={canonical_validation['status']} identical_duplicates_removed={removed} "
        f"output={output_dir}"
    )


if __name__ == "__main__":
    main()
