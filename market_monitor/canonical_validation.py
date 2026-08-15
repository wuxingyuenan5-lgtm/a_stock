from __future__ import annotations

from pathlib import Path

from .canonical_store import CANONICAL_TABLES, audit_table, diff_history, read_csv_rows, row_key


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _blank(value) -> bool:
    return value is None or str(value).strip() == ""


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
        before_map = {row_key(row, spec): row for row in before}
        after_map = {row_key(row, spec): row for row in after}
        audit = audit_table(candidate_path, spec)
        change = diff_history(before, after, spec, target_date)
        tables[name] = {
            **audit,
            **change,
            "previous_row_count": len(before),
            "previous_unique_key_count": len(before_map),
        }

        if audit["duplicate_key_count"]:
            failures.append(f"duplicate_key:{name}")
        if before_map and len(after_map) < len(before_map) * 0.90:
            failures.append(
                f"mass_history_deletion:{name}:keys:{len(before_map)}->{len(after_map)}"
            )

        for key, previous in before_map.items():
            row_date = str(previous.get(spec.date_field) or "")[:10]
            if not row_date or row_date > target_date:
                continue
            label = ":".join(key)
            current = after_map.get(key)
            if current is None:
                prefix = "historical_key_deleted" if row_date < target_date else "target_key_deleted"
                failures.append(f"{prefix}:{name}:{label}")
                continue
            for field, old_value in previous.items():
                if field in spec.key_fields or _blank(old_value):
                    continue
                new_value = current.get(field)
                if _blank(new_value):
                    prefix = "historical_non_null_erased" if row_date < target_date else "target_non_null_erased"
                    failures.append(f"{prefix}:{name}:{label}:{field}")
                elif str(new_value) != str(old_value) and row_date < target_date:
                    warnings.append(f"historical_value_changed:{name}:{label}:{field}")

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
                warnings.append(f"market_turnover_jump:{previous_date}->{row_date}:{ratio:.4f}")
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
        "cross_checks": {"market_rows_checked": len(market_rows)},
    }
