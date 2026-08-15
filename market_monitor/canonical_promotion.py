from __future__ import annotations

import json
import shutil
from pathlib import Path

from .canonical_store import CANONICAL_TABLES, audit_table


def prepare_stage(root: Path, target_date: str) -> Path:
    root = root.resolve()
    stage = root / "output" / target_date / ".canonical_stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    source_data = root / "data"
    if source_data.exists():
        shutil.copytree(source_data, stage / "data", dirs_exist_ok=True)
    return stage


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.with_name(f"{dst.name}.canonical-tmp")
    shutil.copy2(src, temp)
    temp.replace(dst)


def promote_candidate(
    stage_root: Path,
    canonical_root: Path,
    target_date: str,
    validation: dict[str, object],
) -> dict[str, object]:
    if str(validation.get("status") or "").upper() == "FAIL":
        failures = [str(item) for item in (validation.get("failures") or [])]
        detail = "; ".join(failures[:20]) or "unspecified failure"
        if len(failures) > 20:
            detail += f"; ... +{len(failures) - 20} more"
        raise RuntimeError(
            "canonical validation failed; live history not modified: " + detail
        )

    stage_root = stage_root.resolve()
    canonical_root = canonical_root.resolve()
    table_manifest: dict[str, dict[str, object]] = {}
    normalization = validation.get("normalization") if isinstance(validation.get("normalization"), dict) else {}

    for name, spec in CANONICAL_TABLES.items():
        src = stage_root / spec.path
        dst = canonical_root / spec.path
        if not src.exists():
            continue
        before = audit_table(dst, spec) if dst.exists() else {
            "row_count": 0,
            "latest_date": None,
            "duplicate_key_count": 0,
            "sha256": None,
        }
        _atomic_copy(src, dst)
        after = audit_table(dst, spec)
        validation_table = (validation.get("tables") or {}).get(name, {}) if isinstance(validation.get("tables"), dict) else {}
        table_manifest[name] = {
            "before": before,
            "after": after,
            "modified_historical_dates": list(validation_table.get("modified_historical_dates") or []),
            "target_date_changed_keys": int(validation_table.get("target_date_changed_keys") or 0),
            "normalization": normalization.get(name, {}),
        }

    sw_latest_src = stage_root / "data/sw_industry_latest.csv"
    if sw_latest_src.exists():
        _atomic_copy(sw_latest_src, canonical_root / "data/sw_industry_latest.csv")

    manifest = {
        "schema_version": "2.0",
        "target_date": target_date,
        "validation_status": validation.get("status"),
        "failures": list(validation.get("failures") or []),
        "warnings": list(validation.get("warnings") or []),
        "normalization": normalization,
        "tables": table_manifest,
    }
    output = canonical_root / "output" / target_date / "canonical_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
