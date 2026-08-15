#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from market_monitor.history_preflight import preflight_history
from market_monitor.canonical_promotion import prepare_stage, promote_candidate
from market_monitor.canonical_store import normalize_candidate
from market_monitor.canonical_validation import validate_candidate


def execute_preflight_with_gate(
    root: Path,
    target_date: str,
    definitions: list[dict[str, str]],
    repair_indices: bool = True,
    repair_fn: Callable = preflight_history,
) -> dict[str, object]:
    repo_root = root.resolve()
    stage_root = prepare_stage(repo_root, target_date)
    result = repair_fn(
        stage_root,
        target_date,
        definitions,
        repair_indices=repair_indices,
    )
    normalization = normalize_candidate(stage_root)
    canonical_validation = validate_candidate(stage_root, repo_root, target_date)
    canonical_validation["normalization"] = normalization

    output = repo_root / "output" / target_date / "history_preflight.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    combined: dict[str, object] = {
        "preflight": result,
        "normalization": normalization,
        "canonical_validation": canonical_validation,
    }
    output.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = promote_candidate(stage_root, repo_root, target_date, canonical_validation)
    combined["canonical_promotion"] = manifest
    output.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan and repair recoverable history gaps before HTML production")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--config", default="config/market_monitor.json")
    parser.add_argument("--root", default=".")
    parser.add_argument("--no-repair-indices", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    config = json.loads(config_path.read_text(encoding="utf-8"))
    combined = execute_preflight_with_gate(
        root=root,
        target_date=args.target_date,
        definitions=config["indices"],
        repair_indices=not args.no_repair_indices,
    )
    after = combined["preflight"]["after"]
    output = root / "output" / args.target_date / "history_preflight.json"
    removed = sum(
        int(item.get("removed_identical_rows") or 0)
        for item in combined["normalization"].values()
    )
    print(
        f"history_preflight={output} "
        f"index_gaps={len(after['indices'])} denominator_gaps={len(after['market_denominator_dates'])} "
        f"canonical={combined['canonical_validation']['status']} identical_duplicates_removed={removed}"
    )


if __name__ == "__main__":
    main()
