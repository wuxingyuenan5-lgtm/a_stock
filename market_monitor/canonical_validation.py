from __future__ import annotations

from pathlib import Path

from .canonical_store import CANONICAL_TABLES, audit_table, diff_history, read_csv_rows


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_candidate(
    candidate_root: Path,
    canonical_root: Path,
    target_date: str,
) -> dict[str, object]:
    failures: list[str] = []
    warnings: list[str] = []
    tables: dict[str, dict[str, object]] = {}

    for name, spec in CANONICAL_TABLES.items():
        candidate_path = candidate_root / spec.path
        canonical_path = canonical_root / spec.path
        before = read_csv_rows(canonical_path)
        after = read_csv_rows(candidate_path)
        audit = audit_table(candidate_path, spec)
        change = diff_history(before, after, spec, target_date)
        tables[name] = {**audit, **change}

        if audit["duplicate_key_count"]:
            failures.append(f"duplicate_key:{name}")
        if before and len(after) < len(before) * 0.90:
            failures.append(f"mass_history_deletion:{name}:{len(before)}->{len(after)}")

    market_spec = CANONICAL_TABLES["market_core"]
    market_rows = sorted(
        read_csv_rows(candidate_root / market_spec.path),
        key=lambda row: str(row.get("date") or ""),
    )

    for row in market_rows:
        row_date = str(row.get("date") or "")[:10]
        advance = _num(row.get("advance"))
        decline = _num(row.get("decline"))
        flat = _num(row.get("flat"))
        effective = _num(row.get("effective_stocks"))
        if None not in (advance, decline, flat, effective):
            if int(advance + decline + flat) != int(effective):
                failures.append(f"market_effective_stock_mismatch:{row_date}")

        if advance is not None and decline is not None and advance + decline:
            expected_breadth = (advance - decline) / (advance + decline)
            actual_breadth = _num(row.get("market_breadth"))
            if actual_breadth is None or abs(expected_breadth - actual_breadth) > 1e-8:
                failures.append(f"market_breadth_mismatch:{row_date}")

        hot_amount = _num(row.get("hot_amount_100m"))
        total_amount = _num(row.get("total_amount_100m"))
        if hot_amount is not None and total_amount is not None and hot_amount > total_amount:
            failures.append(f"hot_amount_gt_market:{row_date}")

    previous_date = None
    previous_amount = None
    for row in market_rows:
        row_date = str(row.get("date") or "")[:10]
        amount = _num(row.get("total_amount_100m"))
        if amount is None or amount <= 0:
            continue
        if previous_amount is not None and previous_amount > 0:
            ratio = amount / previous_amount
            if ratio < 0.35 or ratio > 2.8:
                warnings.append(
                    f"market_turnover_jump:{previous_date}->{row_date}:{ratio:.4f}"
                )
        previous_date = row_date
        previous_amount = amount

    failures = list(dict.fromkeys(failures))
    warnings = list(dict.fromkeys(warnings))
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return {
        "schema_version": "2.0",
        "target_date": target_date,
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "tables": tables,
        "cross_checks": {
            "market_rows_checked": len(market_rows),
        },
    }
