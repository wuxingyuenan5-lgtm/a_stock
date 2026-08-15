from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class TableSpec:
    name: str
    path: str
    key_fields: tuple[str, ...]
    date_field: str


CANONICAL_TABLES: dict[str, TableSpec] = {
    "market_core": TableSpec("market_core", "data/history/market_core.csv", ("date",), "date"),
    "indices_history": TableSpec("indices_history", "data/history/indices_history.csv", ("date", "name"), "date"),
    "hot_stocks": TableSpec("hot_stocks", "data/history/hot_stocks.csv", ("date", "stock_code"), "date"),
    "innovation": TableSpec("innovation", "data/history/innovation_drug_eastmoney.csv", ("日期",), "日期"),
    "sw_crowding": TableSpec("sw_crowding", "data/history/sw_analysis_daily_second.csv", ("发布日期", "指数代码"), "发布日期"),
    "sw_industry_history": TableSpec("sw_industry_history", "data/sw_industry_history.csv", ("日期", "指数代码"), "日期"),
}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row_key(row: dict, spec: TableSpec) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in spec.key_fields)


def audit_table(path: Path, spec: TableSpec) -> dict[str, object]:
    rows = read_csv_rows(path)
    seen: set[tuple[str, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = row_key(row, spec)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    dates = [str(row.get(spec.date_field) or "")[:10] for row in rows if row.get(spec.date_field)]
    return {
        "row_count": len(rows),
        "latest_date": max(dates, default=None),
        "duplicate_key_count": duplicate_count,
        "sha256": file_sha256(path) if path.exists() else None,
    }


def diff_history(
    before: list[dict],
    after: list[dict],
    spec: TableSpec,
    target_date: str,
) -> dict[str, object]:
    before_map = {row_key(row, spec): row for row in before}
    after_map = {row_key(row, spec): row for row in after}
    modified_historical_dates: set[str] = set()
    target_date_changed_keys = 0

    for key in set(before_map) | set(after_map):
        if before_map.get(key) == after_map.get(key):
            continue
        row = after_map.get(key) or before_map.get(key) or {}
        row_date = str(row.get(spec.date_field) or "")[:10]
        if row_date and row_date < target_date:
            modified_historical_dates.add(row_date)
        if row_date == target_date:
            target_date_changed_keys += 1

    return {
        "modified_historical_dates": sorted(modified_historical_dates),
        "target_date_changed_keys": target_date_changed_keys,
        "deleted_keys": len(set(before_map) - set(after_map)),
        "added_keys": len(set(after_map) - set(before_map)),
    }
