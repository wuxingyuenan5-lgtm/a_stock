from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .collectors import fetch_eastmoney_index


INDEX_NAMES = ("上证50", "Choice微盘", "中证全指")
INDEX_FIELDS = ("date", "name", "code", "close", "return", "amount_100m", "source", "status")


def _float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_index_history(path: Path) -> list[dict[str, object]]:
    out = []
    for row in _read_csv(path):
        out.append({
            "date": str(row.get("date") or ""),
            "name": str(row.get("name") or ""),
            "code": str(row.get("code") or ""),
            "close": _float(row.get("close")),
            "return": _float(row.get("return")),
            "amount_100m": _float(row.get("amount_100m")),
            "source": str(row.get("source") or ""),
            "status": str(row.get("status") or ""),
        })
    out.sort(key=lambda r: (str(r["date"]), str(r["name"])))
    return out


def append_index_history(path: Path, records: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Upsert index history by (date, name) without letting null reruns erase verified values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {(str(r["date"]), str(r["name"])): dict(r) for r in read_index_history(path)}
    for incoming in records:
        date = str(incoming.get("date") or "")
        name = str(incoming.get("name") or "")
        if not date or not name:
            continue
        key = (date, name)
        current = merged.get(key, {
            "date": date, "name": name, "code": str(incoming.get("code") or ""),
            "close": None, "return": None, "amount_100m": None, "source": "", "status": "",
        })
        any_numeric_update = False
        for field in ("close", "return", "amount_100m"):
            value = _float(incoming.get(field))
            if value is not None:
                current[field] = value
                any_numeric_update = True
        if incoming.get("code") not in (None, ""):
            current["code"] = str(incoming.get("code"))
        if any_numeric_update:
            current["source"] = str(incoming.get("source") or current.get("source") or "")
            current["status"] = str(incoming.get("status") or current.get("status") or "ok")
        elif key not in merged:
            current["source"] = str(incoming.get("source") or "")
            current["status"] = str(incoming.get("status") or "")
        merged[key] = current

    rows = sorted(merged.values(), key=lambda r: (str(r["date"]), INDEX_NAMES.index(r["name"]) if r["name"] in INDEX_NAMES else 99, str(r["name"])))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def backfill_index_date(target_date: str, definitions: list[dict[str, str]]) -> list[dict[str, object]]:
    """Historical repair path. Intentionally calls only the historical K-line fetcher."""
    rows = []
    for item in definitions:
        try:
            rows.append(fetch_eastmoney_index(target_date, item["secid"], item["name"]))
        except Exception as exc:
            rows.append({
                "date": target_date,
                "name": item["name"],
                "code": item["secid"],
                "close": None,
                "return": None,
                "amount_100m": None,
                "source": "东方财富历史K线直连",
                "status": f"error: {exc}",
            })
    return rows


def _market_amount_dates(path: Path) -> set[str]:
    out = set()
    for row in _read_csv(path):
        d = str(row.get("date") or "")[:10]
        if d and _float(row.get("total_amount_100m")) is not None:
            out.add(d)
    return out


def _innovation_amount_dates(path: Path, report_date: str) -> set[str]:
    out = set()
    for row in _read_csv(path):
        d = str(row.get("日期") or row.get("date") or "")[:10]
        raw = row.get("成交额") if "成交额" in row else row.get("amount_100m")
        if d and d <= report_date and _float(raw) is not None:
            out.add(d)
    return out


def scan_history_gaps(
    root: Path,
    report_date: str,
    required_index_dates: list[str] | None = None,
) -> dict[str, object]:
    history_dir = root / "data" / "history"
    market_rows = _read_csv(history_dir / "market_core.csv")
    market_dates = [str(r.get("date") or "")[:10] for r in market_rows if r.get("date") and str(r.get("date"))[:10] <= report_date]
    dates_to_scan = required_index_dates if required_index_dates is not None else market_dates

    index_rows = read_index_history(history_dir / "indices_history.csv")
    by_key = {(str(r["date"]), str(r["name"])): r for r in index_rows}
    index_gaps = []
    for d in dates_to_scan:
        for name in INDEX_NAMES:
            row = by_key.get((d, name))
            missing_fields = [field for field in ("close", "return", "amount_100m") if not row or row.get(field) is None]
            if missing_fields:
                index_gaps.append({"date": d, "name": name, "fields": missing_fields})

    market_amount_dates = _market_amount_dates(history_dir / "market_core.csv")
    innovation_dates = _innovation_amount_dates(history_dir / "innovation_drug_eastmoney.csv", report_date)
    denominator_gaps = sorted(innovation_dates - market_amount_dates)
    return {
        "report_date": report_date,
        "indices": index_gaps,
        "market_denominator_dates": denominator_gaps,
    }


def preflight_history(
    root: Path,
    report_date: str,
    definitions: list[dict[str, str]],
    repair_indices: bool = True,
) -> dict[str, object]:
    """Scan local history and repair recoverable historical index gaps only."""
    before = scan_history_gaps(root, report_date)
    if repair_indices:
        missing_dates = sorted({item["date"] for item in before["indices"]})
        path = root / "data" / "history" / "indices_history.csv"
        for d in missing_dates:
            missing_names = {item["name"] for item in before["indices"] if item["date"] == d}
            defs = [item for item in definitions if item["name"] in missing_names]
            if defs:
                append_index_history(path, backfill_index_date(d, defs))
    after = scan_history_gaps(root, report_date)
    return {"before": before, "after": after}
