#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_monitor.canonical_validation import validate_candidate


def validate_current_canonical(root: Path, target_date: str) -> dict[str, object]:
    root = Path(root).resolve()
    return validate_candidate(root, root, target_date)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the promoted Canonical A-share histories")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    result = validate_current_canonical(root, args.target_date)
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"canonical_validation={output} status={result['status']} "
        f"failures={len(result['failures'])} warnings={len(result['warnings'])}"
    )
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
