from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .collectors import fetch_eastmoney_index, _fetch_em_klines


INDEX_NAMES = ("上证50", "Choice微盘", "中证全指")
INDEX_FIELDS = ("date", "name", "code", "close", "return", "amount_100m", "source", "status")
INDEX_REQUIRED_FIELDS = ("return", "amount_100m")
INDEX_HISTORY_WINDOW = 5
MAX_SPARSE_FALLBACK_DATES = 5
MARKET_CORE_FILE = "market_core.csv"
MARKET_VERIFIED_BACKFILL_FILE = "market_core_verified_backfill.csv"


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


def read_market_core_rows(root: Path) -> list[dict[str, str]]:
    """Return canonical market-core history with explicit verified migration rows overlaid."""
    history_dir = root / "data" / "history"
    merged: dict[str, dict[str, str]] = {}
    for filename in (MARKET_CORE_FILE, MARKET_VERIFIED_BACKFILL_FILE):
        for row in _read_csv(history_dir / filename):
            d = str(row.get("date") or "")[:10]
            if d:
                merged[d] = dict(row)
    return [merged[d] for d in sorted(merged)]


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
    """Upsert by (date,name); null reruns may never erase verified non-null history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {(str(r["date"]), str(r["name"])): dict(r) for r in read_index_history(path)}
    for incoming in records:
        d = str(incoming.get("date") or "")
        name = str(incoming.get("name") or "")
        if not d or not name:
            continue
        key = (d, name)
        current = merged.get(key, {
            "date": d, "name": name, "code": str(incoming.get("code") or ""),
            "close": None, "return": None, "amount_100m": None, "source": "", "status": "",
        })
        updated = False
        for field in ("close", "return", "amount_100m"):
            value = _float(incoming.get(field))
            if value is not None:
                current[field] = value
                updated = True
        if incoming.get("code") not in (None, ""):
            current["code"] = str(incoming.get("code"))
        if updated:
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
    """Sparse historical repair. Uses the historical K-line fetcher only."""
    rows = []
    for item in definitions:
        try:
            rows.append(fetch_eastmoney_index(target_date, item["secid"], item["name"]))
        except Exception as exc:
            rows.append({
                "date": target_date, "name": item["name"], "code": item["secid"],
                "close": None, "return": None, "amount_100m": None,
                "source": "东方财富历史K线直连", "status": f"error: {exc}",
            })
    return rows


def backfill_index_range(start_date: str, end_date: str, definitions: list[dict[str, str]]) -> list[dict[str, object]]:
    """Bulk historical bootstrap: exactly one bounded K-line range request per index."""
    beg, end = start_date.replace("-", ""), end_date.replace("-", "")
    rows: list[dict[str, object]] = []
    for item in definitions:
        try:
            raw_rows = _fetch_em_klines(item["secid"], beg, end, lmt=1000)
            for values in raw_rows:
                rows.append({
                    "date": values[0],
                    "name": item["name"],
                    "code": item["secid"],
                    "close": float(values[2]),
                    "return": float(values[8]) / 100,
                    "amount_100m": float(values[6]) / 1e8,
                    "source": "东方财富历史K线批量直连",
                    "status": "ok_bulk_history",
                })
        except Exception as exc:
            rows.append({
                "date": end_date, "name": item["name"], "code": item["secid"],
                "close": None, "return": None, "amount_100m": None,
                "source": "东方财富历史K线批量直连", "status": f"error: {exc}",
            })
    return rows


def _market_amount_dates(rows: list[dict[str, str]]) -> set[str]:
    out = set()
    for row in rows:
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


def scan_history_gaps(root: Path, report_date: str, required_index_dates: list[str] | None = None) -> dict[str, object]:
    """Scan display-relevant history.

    The daily HTML only displays the latest five index sessions and uses return +
    turnover amount. Historical close remains an optional reference field, so the
    preflight does not create hundreds of irrelevant warnings or network calls for it.
    Explicit callers may still pass required_index_dates for a targeted historical audit.
    """
    history_dir = root / "data" / "history"
    market_rows = read_market_core_rows(root)
    market_dates = [str(r.get("date") or "")[:10] for r in market_rows if r.get("date") and str(r.get("date"))[:10] <= report_date]
    dates_to_scan = required_index_dates if required_index_dates is not None else market_dates[-INDEX_HISTORY_WINDOW:]
    index_rows = read_index_history(history_dir / "indices_history.csv")
    by_key = {(str(r["date"]), str(r["name"])): r for r in index_rows}
    index_gaps = []
    for d in dates_to_scan:
        for name in INDEX_NAMES:
            row = by_key.get((d, name))
            missing = [field for field in INDEX_REQUIRED_FIELDS if not row or row.get(field) is None]
            if missing:
                index_gaps.append({"date": d, "name": name, "fields": missing})
    denominator_gaps = sorted(
        _innovation_amount_dates(history_dir / "innovation_drug_eastmoney.csv", report_date)
        - _market_amount_dates(market_rows)
    )
    return {"report_date": report_date, "indices": index_gaps, "market_denominator_dates": denominator_gaps}


def preflight_history(root: Path, report_date: str, definitions: list[dict[str, str]], repair_indices: bool = True) -> dict[str, object]:
    """Scan display-relevant history, bulk-bootstrap gaps, then bounded sparse repairs."""
    before = scan_history_gaps(root, report_date)
    path = root / "data" / "history" / "indices_history.csv"
    had_large_gap = False
    if repair_indices and before["indices"]:
        missing_dates = sorted({item["date"] for item in before["indices"]})
        if len(missing_dates) >= 4:
            had_large_gap = True
            append_index_history(path, backfill_index_range(missing_dates[0], missing_dates[-1], definitions))
        middle = scan_history_gaps(root, report_date)
        sparse_dates = sorted({item["date"] for item in middle["indices"]})
        if had_large_gap:
            sparse_dates = sparse_dates[-MAX_SPARSE_FALLBACK_DATES:]
        for d in sparse_dates:
            missing_names = {item["name"] for item in middle["indices"] if item["date"] == d}
            defs = [item for item in definitions if item["name"] in missing_names]
            if defs:
                append_index_history(path, backfill_index_date(d, defs))
    after = scan_history_gaps(root, report_date)
    return {"before": before, "after": after}
