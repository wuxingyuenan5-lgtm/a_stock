#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


RENDERER_VERSION = "1.5"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _market_amount_map(history_path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in _read_csv(history_path):
        d = str(row.get("date") or "").strip()
        amount = _float(row.get("total_amount_100m"))
        if d and amount is not None:
            out[d] = amount
    return out


def _normalize_history(rows: list[dict[str, str]], mode: str, market_amounts: dict[str, float]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        d = str(row.get("日期") or row.get("date") or "").strip()[:10]
        if not d:
            continue
        raw_amount = _float(row.get("成交额"))
        amount_100m = raw_amount / 1e8 if raw_amount is not None and mode in {"eastmoney", "ths"} else None
        market_amount = market_amounts.get(d)
        share = amount_100m / market_amount if amount_100m is not None and market_amount else None
        if share is not None and not (0 <= share <= 1.0):
            raise RuntimeError(f"innovation amount share out of range: date={d} mode={mode} share={share}")
        normalized.append({
            "date": d,
            "amount_100m": amount_100m,
            "amount_share_of_a": share,
            "turnover": _float(row.get("换手率")),
            "return": _float(row.get("日收益率")),
            "volume": _float(row.get("成交量")),
            "source": str(row.get("数据源") or "").strip(),
            "history_source_mode": mode,
        })
    normalized.sort(key=lambda item: str(item["date"]))
    return normalized


def _copy_required(source: Path, destination: Path) -> None:
    if not source.exists():
        raise RuntimeError(f"required renderer input missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _validated_mother(root: Path) -> tuple[str | None, str | None]:
    registry_path = root / "data" / "latest_validated_workbook.json"
    if not registry_path.exists():
        return None, None
    registry = _read_json(registry_path)
    return registry.get("date"), registry.get("filename")


def build_bundle(target_date: str, root: Path = Path(".")) -> Path:
    output_dir = root / "output" / target_date
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_json(output_dir / "source_manifest.json")
    mode = str(((manifest.get("sources") or {}).get("innovation_drug") or {}).get("history_mode") or "none")

    if mode == "eastmoney":
        history_path = root / "data" / "history" / "innovation_drug_eastmoney.csv"
    elif mode == "ths":
        history_path = root / "data" / "history" / "innovation_drug_ths.csv"
    else:
        history_path = Path("__missing__")

    market_history = root / "data" / "history" / "market_core.csv"
    market_amounts = _market_amount_map(market_history)
    normalized = _normalize_history(_read_csv(history_path), mode, market_amounts)
    share_rows = sum(1 for row in normalized if row["amount_share_of_a"] is not None)
    target_row = next((row for row in normalized if row["date"] == target_date), None)
    if target_row is not None and target_row["amount_100m"] is not None and target_row["amount_share_of_a"] is None:
        raise RuntimeError(f"market_core missing target-date denominator for innovation history: {target_date}")

    destination = output_dir / "innovation_history_selected.csv"
    fieldnames = [
        "date", "amount_100m", "amount_share_of_a", "turnover",
        "return", "volume", "source", "history_source_mode",
    ]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(normalized)

    # Self-contained web renderer inputs: one artifact download is enough.
    _copy_required(root / "data" / "sw_industry_latest.csv", output_dir / "sw_industry_latest.csv")
    runtime_dir = output_dir / "renderer_runtime"
    _copy_required(root / "run_excel_renderer_v15.py", runtime_dir / "run_excel_renderer_v15.py")
    _copy_required(root / "run_excel_renderer_v14.py", runtime_dir / "run_excel_renderer_v14.py")
    _copy_required(root / "excel_renderer_artifact.py", runtime_dir / "excel_renderer_artifact.py")
    _copy_required(root / "config" / "excel_renderer.json", runtime_dir / "excel_renderer.json")

    mother_date, expected_mother = _validated_mother(root)

    render_manifest = {
        "date": target_date,
        "renderer_bundle_version": "2.1",
        "renderer_version": RENDERER_VERSION,
        "innovation_history_source_mode": mode,
        "innovation_history_rows": len(normalized),
        "innovation_history_share_rows": share_rows,
        "innovation_activity_proxy": "retired",
        "market_core_rows": len(market_amounts),
        "mother_policy": {
            "mode": "rolling_previous_validated",
            "registry": "data/latest_validated_workbook.json",
            "expected_mother_date": mother_date,
            "expected_mother_filename": expected_mother,
            "fallback": "bootstrap template only when no validated registry exists"
        },
        "web_execution": {
            "goal": "single artifact download + one validated rolling mother + one renderer command",
            "command": (
                f"python renderer_runtime/run_excel_renderer_v15.py "
                f"--template <mother.xlsx> --bundle-dir . "
                f"--config renderer_runtime/excel_renderer.json "
                f"--output A股每日市场监控_{target_date.replace('-', '')}.xlsx"
            ),
            "forbid_free_rebuild": True,
            "forbid_chart_recreation": True,
            "innovation_turnover_proxy_forbidden": True
        },
        "files": {
            "payload": "daily_payload.json",
            "validation": "validation.json",
            "source_manifest": "source_manifest.json",
            "hot_stocks": "hot_stocks.csv",
            "innovation_history": "innovation_history_selected.csv",
            "sw_industry_latest": "sw_industry_latest.csv",
            "renderer": "renderer_runtime/run_excel_renderer_v15.py",
            "renderer_base": "renderer_runtime/run_excel_renderer_v14.py",
            "renderer_core": "renderer_runtime/excel_renderer_artifact.py",
            "renderer_config": "renderer_runtime/excel_renderer.json"
        }
    }
    (output_dir / "render_bundle_manifest.json").write_text(
        json.dumps(render_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "web_production_manifest.json").write_text(
        json.dumps({
            "date": target_date,
            "artifact_name": f"a-share-monitor-{target_date}",
            "expected_mother_date": mother_date,
            "expected_mother_filename": expected_mother,
            "renderer_version": RENDERER_VERSION,
            "renderer_command": render_manifest["web_execution"]["command"]
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(
        f"render bundle ready date={target_date} renderer={RENDERER_VERSION} "
        f"mother={expected_mother} innovation_mode={mode} rows={len(normalized)} "
        f"share_rows={share_rows} market_core_rows={len(market_amounts)}"
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare self-contained renderer-ready market monitor bundle")
    parser.add_argument("--target-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    build_bundle(args.target_date)


if __name__ == "__main__":
    main()
