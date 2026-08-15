#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _num(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _matrix_target_sum(matrix: dict, target_date: str):
    dates = matrix.get("dates") or []
    if target_date not in dates:
        return None
    idx = dates.index(target_date)
    total = 0
    for row in matrix.get("rows") or []:
        counts = row.get("counts") or []
        if idx >= len(counts):
            return None
        total += int(counts[idx] or 0)
    return total


def _has_activity_proxy(report: dict) -> bool:
    forbidden = {"activity", "volume_activity_20d", "20日成交量活跃度代理"}
    for row in report.get("innovation_history") or []:
        if any(key in forbidden for key in row):
            return True
    return False


def validate_report(report: dict, html: str) -> dict[str, object]:
    failures: list[str] = []
    warnings: list[str] = []
    meta = report.get("meta") or {}
    target = str(meta.get("report_date") or "")
    market = report.get("market_history") or []
    latest_market = market[-1] if market else None

    if not latest_market or str(latest_market.get("date") or "") != target:
        failures.append("report_date_not_latest_market")
    else:
        for field in ("advance", "decline", "limit_up", "limit_down"):
            if latest_market.get(field) is None:
                failures.append(f"market_structure_latest_missing:{field}")

    expected_hot = int((latest_market or {}).get("hot_count") or 0)
    actual_hot = len(report.get("hot_stocks_latest") or [])
    if actual_hot != expected_hot:
        failures.append("hot_detail_count_mismatch")
    if html.count('data-hot-row="1"') != actual_hot:
        failures.append("hot_html_row_count_mismatch")

    matrix_sum = _matrix_target_sum(report.get("hot_stock_matrix") or {}, target)
    if matrix_sum != expected_hot:
        failures.append("hot_matrix_count_mismatch")

    marker = f'data-chart-date="{target}"'
    if marker not in html:
        failures.append("market_chart_latest_date_missing")

    lower = html.lower()
    if any(token in lower for token in ("http://", "https://", "<script src=", "<link href=")):
        failures.append("external_dependency")

    if _has_activity_proxy(report):
        failures.append("innovation_activity_proxy_present")

    market_amounts = {
        str(row.get("date")): _num(row.get("total_amount_100m"))
        for row in market
        if row.get("date")
    }
    for row in report.get("innovation_history") or []:
        d = str(row.get("date") or "")
        amount = _num(row.get("amount_100m"))
        share = _num(row.get("amount_share_of_a"))
        denominator = market_amounts.get(d)
        if amount is not None and denominator not in (None, 0) and share is None:
            failures.append(f"recoverable_innovation_share_blank:{d}")
        turnover = _num(row.get("turnover"))
        if turnover is not None and turnover < 0:
            failures.append(f"innovation_turnover_invalid:{d}")

    quality = report.get("quality") or {}
    for item in quality.get("unresolved") or []:
        level = str(item.get("level") or "WARN").upper()
        name = str(item.get("module") or "unknown")
        if level == "FAIL":
            failures.append(f"quality_failure:{name}")
        else:
            warnings.append(f"quality_warning:{name}")

    # Non-recoverable source gaps remain visible as warnings. They do not make a
    # structurally consistent report unusable.
    gaps = quality.get("history_gaps") or {}
    if gaps.get("indices"):
        warnings.append("unresolved_index_history_gaps")
    if gaps.get("market_denominator_dates"):
        warnings.append("unresolved_market_denominator_gaps")

    # Preserve order but deduplicate messages for deterministic validation JSON.
    failures = list(dict.fromkeys(failures))
    warnings = list(dict.fromkeys(warnings))
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return {
        "schema_version": "1.0",
        "report_date": target,
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "checks": {
            "latest_market_date": str((latest_market or {}).get("date") or ""),
            "hot_detail_rows": actual_hot,
            "hot_expected": expected_hot,
            "hot_matrix_sum": matrix_sum,
            "market_chart_latest_marker": marker in html,
            "offline_single_file": "external_dependency" not in failures,
            "innovation_activity_proxy_absent": "innovation_activity_proxy_present" not in failures,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the self-contained A-share HTML report")
    parser.add_argument("--data", required=True, help="report_data.json")
    parser.add_argument("--html", required=True, help="rendered HTML file")
    parser.add_argument("--output", required=True, help="html_validation.json")
    args = parser.parse_args()
    report = json.loads(Path(args.data).read_text(encoding="utf-8"))
    html = Path(args.html).read_text(encoding="utf-8")
    result = validate_report(report, html)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"html_validation status={result['status']} failures={len(result['failures'])} warnings={len(result['warnings'])}")
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
