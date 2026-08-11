#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


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
        date = str(row.get("date") or "").strip()
        amount = _float(row.get("total_amount_100m"))
        if date and amount is not None:
            out[date] = amount
    return out


def _normalize_history(rows: list[dict[str, str]], mode: str, market_amounts: dict[str, float]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        date = str(row.get("日期") or row.get("date") or "").strip()[:10]
        if not date:
            continue
        raw_amount = _float(row.get("成交额"))
        # Both Eastmoney BK1106 and THS concept-index history expose turnover amount in yuan.
        amount_100m = raw_amount / 1e8 if raw_amount is not None and mode in {"eastmoney", "ths"} else None
        market_amount = market_amounts.get(date)
        share = amount_100m / market_amount if amount_100m is not None and market_amount else None
        if share is not None and not (0 <= share <= 1.0):
            raise RuntimeError(
                f"innovation amount share out of range; check source unit: date={date} mode={mode} share={share}"
            )
        normalized.append({
            "date": date,
            "amount_100m": amount_100m,
            "amount_share_of_a": share,
            "turnover": _float(row.get("换手率")),
            "volume_activity_20d": _float(row.get("20日成交量活跃度代理")),
            "return": _float(row.get("日收益率")),
            "volume": _float(row.get("成交量")),
            "source": str(row.get("数据源") or "").strip(),
            "history_source_mode": mode,
        })
    normalized.sort(key=lambda item: str(item["date"]))
    return normalized


def build_bundle(target_date: str, root: Path = Path(".")) -> Path:
    output_dir = root / "output" / target_date
    manifest = _read_json(output_dir / "source_manifest.json")
    mode = str(((manifest.get("sources") or {}).get("innovation_drug") or {}).get("history_mode") or "none")
    if mode == "eastmoney":
        history_path = root / "data" / "history" / "innovation_drug_eastmoney.csv"
    elif mode == "ths":
        history_path = root / "data" / "history" / "innovation_drug_ths.csv"
    else:
        history_path = Path("__missing__")

    market_amounts = _market_amount_map(root / "data" / "history" / "market_core.csv")
    normalized = _normalize_history(_read_csv(history_path), mode, market_amounts)
    share_rows = sum(1 for row in normalized if row["amount_share_of_a"] is not None)
    target_row = next((row for row in normalized if row["date"] == target_date), None)
    if target_row is not None and target_row["amount_100m"] is not None and target_row["amount_share_of_a"] is None:
        raise RuntimeError(f"market_core missing target-date denominator for innovation history: {target_date}")

    destination = output_dir / "innovation_history_selected.csv"
    fieldnames = [
        "date", "amount_100m", "amount_share_of_a", "turnover",
        "volume_activity_20d", "return", "volume", "source", "history_source_mode",
    ]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(normalized)

    render_manifest = {
        "date": target_date,
        "renderer_bundle_version": "1.0",
        "innovation_history_source_mode": mode,
        "innovation_history_rows": len(normalized),
        "innovation_history_share_rows": share_rows,
        "market_core_rows": len(market_amounts),
        "files": {
            "payload": "daily_payload.json",
            "validation": "validation.json",
            "source_manifest": "source_manifest.json",
            "hot_stocks": "hot_stocks.csv",
            "innovation_history": "innovation_history_selected.csv",
        },
    }
    (output_dir / "render_bundle_manifest.json").write_text(
        json.dumps(render_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"render bundle ready date={target_date} innovation_mode={mode} "
        f"rows={len(normalized)} share_rows={share_rows} market_core_rows={len(market_amounts)}"
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare renderer-ready market monitor bundle")
    parser.add_argument("--target-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    build_bundle(args.target_date)


if __name__ == "__main__":
    main()
