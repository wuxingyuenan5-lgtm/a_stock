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


def _latest_hot_date(report: dict) -> str | None:
    rows = report.get("hot_stocks_history") or report.get("hot_stocks_latest") or []
    dates = [str(row.get("date") or "") for row in rows if row.get("date")]
    return max(dates, default=None)


def _validate_v11_interactions(report: dict, html: str, failures: list[str]) -> dict[str, object]:
    market = report.get("market_history") or []
    crowding = report.get("sw_crowding_history") or []
    innovation = report.get("innovation_history") or []
    expected_time_charts = (2 if market else 0) + (2 if crowding else 0) + (2 if innovation else 0)
    chart_count = html.count('<div class="time-chart" data-time-chart="1"')
    start_count = html.count('class="time-range-start"')
    end_count = html.count('class="time-range-end"')
    all_count = html.count('class="time-range-all"')
    label_count = html.count('class="time-range-label"')
    if (
        chart_count < expected_time_charts
        or start_count != chart_count
        or end_count != chart_count
        or all_count != chart_count
        or label_count != chart_count
    ):
        failures.append("time_slider_contract_missing")
    if expected_time_charts and (
        'start.value="0"' not in html
        or 'end.value=String(Math.max(0,dates.length-1))' not in html
    ):
        failures.append("time_slider_not_default_full_history")

    matrix = report.get("hot_stock_matrix") or {}
    matrix_dates = [str(value) for value in (matrix.get("dates") or [])]
    if len(matrix_dates) > 10:
        failures.append("hot_matrix_more_than_ten_dates")
    if matrix_dates != sorted(matrix_dates, reverse=True):
        failures.append("hot_matrix_not_newest_first")
    latest_hot = _latest_hot_date(report)
    if latest_hot and matrix_dates and matrix_dates[0] != latest_hot:
        failures.append("hot_matrix_latest_date_not_leftmost")

    if report.get("sw_industry_latest"):
        for key in ("amount", "return", "volatility"):
            if f'data-sort-field="{key}"' not in html:
                failures.append(f"sw_sort_control_missing:{key}")
        if "['original','desc','asc']" not in html:
            failures.append("sw_sort_cycle_missing")

    if crowding:
        if 'data-area-chart="crowding-share"' not in html:
            failures.append("crowding_share_area_chart_missing")
        if 'data-line-chart="crowding-turnover"' not in html:
            failures.append("crowding_turnover_line_chart_missing")
    if innovation:
        if 'data-area-chart="innovation-share"' not in html:
            failures.append("innovation_share_area_chart_missing")
        if 'data-direct-turnover="innovation"' not in html:
            failures.append("innovation_turnover_line_chart_missing")

    if "四行业成交额合计" in html:
        failures.append("combined_amount_presentation_present")

    return {
        "time_chart_count": chart_count,
        "expected_time_charts": expected_time_charts,
        "hot_matrix_dates": matrix_dates,
        "hot_matrix_latest_date": latest_hot,
    }


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
        row_date = str(row.get("date") or "")
        amount = _num(row.get("amount_100m"))
        share = _num(row.get("amount_share_of_a"))
        denominator = market_amounts.get(row_date)
        if amount is not None and denominator not in (None, 0) and share is None:
            failures.append(f"recoverable_innovation_share_blank:{row_date}")
        turnover = _num(row.get("turnover"))
        if turnover is not None and turnover < 0:
            failures.append(f"innovation_turnover_invalid:{row_date}")

    v11_checks = _validate_v11_interactions(report, html, failures)

    quality = report.get("quality") or {}
    for item in quality.get("unresolved") or []:
        level = str(item.get("level") or "WARN").upper()
        name = str(item.get("module") or "unknown")
        if level == "FAIL":
            failures.append(f"quality_failure:{name}")
        else:
            warnings.append(f"quality_warning:{name}")

    gaps = quality.get("history_gaps") or {}
    if gaps.get("indices"):
        warnings.append("unresolved_index_history_gaps")
    if gaps.get("market_denominator_dates"):
        warnings.append("unresolved_market_denominator_gaps")

    failures = list(dict.fromkeys(failures))
    warnings = list(dict.fromkeys(warnings))
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return {
        "schema_version": "1.1",
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
            **v11_checks,
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
    print(
        f"html_validation status={result['status']} "
        f"failures={len(result['failures'])} warnings={len(result['warnings'])}"
    )
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
