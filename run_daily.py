#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Callable
from zoneinfo import ZoneInfo

from market_monitor.production import run
from market_monitor.history_preflight import append_index_history
from market_monitor.canonical_promotion import prepare_stage, promote_candidate
from market_monitor.canonical_store import normalize_candidate
from market_monitor.canonical_validation import validate_candidate
from market_monitor.sw_cache import refresh_sw_cache
from build_report_data import append_hot_stock_history
from update_sw_industry_fast import update as update_sw_industry_fast
from update_sw_industry import update as update_sw_industry_full


def default_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股每日监控一键数据生产")
    parser.add_argument("--target-date", default=default_date(), help="YYYY-MM-DD；正式日更只允许中国时区当天")
    parser.add_argument("--config", default="config/market_monitor.json")
    parser.add_argument("--refresh-mapping", action="store_true")
    parser.add_argument("--full-refresh-sw-industry", action="store_true")
    return parser.parse_args()


def refresh_stage_sources(
    stage_root: Path,
    target_date: str,
    full_refresh_sw_industry: bool = False,
    crowding_refresh_fn: Callable = refresh_sw_cache,
    fast_industry_refresh_fn: Callable = update_sw_industry_fast,
    full_industry_refresh_fn: Callable = update_sw_industry_full,
) -> dict[str, object]:
    """Refresh mutable Shenwan sources only inside the Canonical candidate root.

    Network failures preserve the staged copy of the previously validated files
    and become warnings; they never cause direct writes to the live Canonical root.
    """
    stage_root = Path(stage_root).resolve()
    data_dir = stage_root / "data"
    result: dict[str, object] = {"warnings": []}

    try:
        crowding_refresh_fn(
            target_date,
            cache_path=data_dir / "cache/sw_analysis_daily_second.csv",
            history_path=data_dir / "history/sw_analysis_daily_second.csv",
        )
        result["sw_crowding"] = "ok"
    except Exception as exc:
        result["sw_crowding"] = "fallback_previous_canonical"
        result["warnings"].append(f"sw_crowding_refresh_failed:{exc}")

    try:
        if full_refresh_sw_industry:
            full_industry_refresh_fn(
                history_rows=260,
                sleep_seconds=0.15,
                workers=4,
                data_dir=data_dir,
            )
            result["sw_industry"] = "ok_full"
        else:
            fast_industry_refresh_fn(target_date, data_dir=data_dir)
            result["sw_industry"] = "ok_fast"
    except Exception as exc:
        result["sw_industry"] = "fallback_previous_canonical"
        result["warnings"].append(f"sw_industry_refresh_failed:{exc}")

    return result


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
    source_refresh = refresh_stage_sources(
        stage_root=stage_root,
        target_date=args.target_date,
        full_refresh_sw_industry=args.full_refresh_sw_industry,
    )

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
    canonical_validation["source_refresh"] = source_refresh
    canonical_validation["warnings"] = list(dict.fromkeys(
        list(canonical_validation.get("warnings") or []) + list(source_refresh.get("warnings") or [])
    ))
    if canonical_validation["status"] != "FAIL" and canonical_validation["warnings"]:
        canonical_validation["status"] = "WARN"

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
        f"sw_crowding={source_refresh['sw_crowding']} sw_industry={source_refresh['sw_industry']} "
        f"output={output_dir}"
    )


if __name__ == "__main__":
    main()
