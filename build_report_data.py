#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

from market_monitor.history_preflight import read_index_history, scan_history_gaps


TARGET_SW = {"通信设备": "801102", "计算机设备": "801101", "元件": "801083", "半导体": "801081"}
HOT_FIELDS = ("date", "rank", "stock_code", "stock_name", "close", "return", "amount_100m", "sw_level1", "sw_level2")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    number = _num(value)
    return None if number is None else int(round(number))


def append_hot_stock_history(path: Path, target_date: str, rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for row in _read_csv(path):
        d, code = str(row.get("date") or ""), str(row.get("stock_code") or "").zfill(6)
        if d and code:
            merged[(d, code)] = {
                "date": d, "rank": _int(row.get("rank")), "stock_code": code,
                "stock_name": str(row.get("stock_name") or ""), "close": _num(row.get("close")),
                "return": _num(row.get("return")), "amount_100m": _num(row.get("amount_100m")),
                "sw_level1": str(row.get("sw_level1") or "未匹配"),
                "sw_level2": str(row.get("sw_level2") or "未匹配"),
            }
    merged = {key: value for key, value in merged.items() if key[0] != target_date}
    for row in rows:
        code = str(row.get("stock_code") or "").zfill(6)
        if not code.strip("0"):
            continue
        merged[(target_date, code)] = {
            "date": target_date,
            "rank": _int(row.get("rank")),
            "stock_code": code,
            "stock_name": str(row.get("stock_name") or ""),
            "close": _num(row.get("close")),
            "return": _num(row.get("return")),
            "amount_100m": _num(row.get("amount_100m")),
            "sw_level1": str(row.get("sw_level1") or "未匹配"),
            "sw_level2": str(row.get("sw_level2") or "未匹配"),
        }
    values = sorted(
        merged.values(),
        key=lambda row: (row["date"], row["rank"] if row["rank"] is not None else 9999, row["stock_code"]),
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HOT_FIELDS)
        writer.writeheader()
        writer.writerows(values)
    return values


def _market_history(path: Path, target_date: str) -> list[dict[str, object]]:
    integer_fields = ("advance", "decline", "flat", "limit_up", "limit_down", "effective_stocks", "hot_count")
    numeric_fields = ("total_amount_100m", "hot_amount_100m", "hot_concentration", "market_breadth")
    rows = []
    for raw in _read_csv(path):
        row_date = str(raw.get("date") or "")[:10]
        if not row_date or row_date > target_date:
            continue
        row = {"date": row_date}
        for field in integer_fields:
            row[field] = _int(raw.get(field))
        for field in numeric_fields:
            row[field] = _num(raw.get(field))
        rows.append(row)
    return sorted(rows, key=lambda row: row["date"])


def _indices_history(path: Path, target_date: str) -> list[dict[str, object]]:
    return [row for row in read_index_history(path) if str(row["date"]) <= target_date]


def _sw_industry(path: Path) -> list[dict[str, object]]:
    numeric = {"收盘价", "成交额", "日收益率", "20日年化波动率"}
    rows = []
    for raw in _read_csv(path):
        row = {}
        for key, value in raw.items():
            row[key] = _num(value) if key in numeric else value
        rows.append(row)
    return rows


def _hot_rows(path: Path, target_date: str) -> list[dict[str, object]]:
    rows = []
    for raw in _read_csv(path):
        row_date = str(raw.get("date") or "")[:10]
        if not row_date or row_date > target_date:
            continue
        rows.append({
            "date": row_date,
            "rank": _int(raw.get("rank")),
            "stock_code": str(raw.get("stock_code") or "").zfill(6),
            "stock_name": str(raw.get("stock_name") or ""),
            "close": _num(raw.get("close")),
            "return": _num(raw.get("return")),
            "amount_100m": _num(raw.get("amount_100m")),
            "sw_level1": str(raw.get("sw_level1") or "未匹配"),
            "sw_level2": str(raw.get("sw_level2") or "未匹配"),
        })
    return sorted(rows, key=lambda row: (row["date"], row["rank"] if row["rank"] is not None else 9999))


def build_hot_stock_matrix(rows: list[dict[str, object]], recent_dates: int = 6, named_max: int = 13) -> dict[str, object]:
    dates = sorted({str(row["date"]) for row in rows})[-recent_dates:]
    cumulative: dict[str, int] = {}
    counts = {row_date: {} for row_date in dates}
    for row in rows:
        industry = str(row.get("sw_level2") or "待申万映射")
        if industry in ("", "未匹配"):
            industry = "待申万映射"
        cumulative[industry] = cumulative.get(industry, 0) + 1
        if row["date"] in counts:
            counts[row["date"]][industry] = counts[row["date"]].get(industry, 0) + 1
    named = sorted(cumulative, key=lambda value: (-cumulative[value], value))[:named_max]
    overflow = set(cumulative) - set(named)
    matrix_rows = []
    for industry in named:
        matrix_rows.append({
            "industry": industry,
            "counts": [counts[row_date].get(industry, 0) for row_date in dates],
            "history_total": cumulative[industry],
        })
    if overflow:
        matrix_rows.append({
            "industry": "其他行业汇总",
            "counts": [sum(counts[row_date].get(industry, 0) for industry in overflow) for row_date in dates],
            "history_total": sum(cumulative[industry] for industry in overflow),
        })
    return {"dates": dates, "rows": matrix_rows}


def _sw_crowding(path: Path, market_history: list[dict[str, object]], target_date: str) -> list[dict[str, object]]:
    denominator = {row["date"]: row.get("total_amount_100m") for row in market_history}
    rows_by_date: dict[str, dict[str, object]] = {}
    for raw in _read_csv(path):
        row_date = str(raw.get("发布日期") or raw.get("日期") or "")[:10]
        code = str(raw.get("指数代码") or "").replace(".0", "")
        if not row_date or row_date > target_date or code not in TARGET_SW.values():
            continue
        label = next(name for name, target_code in TARGET_SW.items() if target_code == code)
        share_raw = _num(raw.get("成交额占比"))
        turnover_raw = _num(raw.get("换手率"))
        share = share_raw / 100 if share_raw is not None else None
        turnover = turnover_raw / 100 if turnover_raw is not None else None
        row = rows_by_date.setdefault(row_date, {"date": row_date, "targets": {}})
        amount = denominator.get(row_date) * share if denominator.get(row_date) is not None and share is not None else None
        row["targets"][label] = {
            "code": code,
            "amount_100m": amount,
            "amount_share_of_a": share,
            "turnover": turnover,
        }
    out = []
    for row_date, row in sorted(rows_by_date.items()):
        targets = row["targets"]
        shares = [targets[name].get("amount_share_of_a") for name in TARGET_SW if name in targets]
        amounts = [targets[name].get("amount_100m") for name in TARGET_SW if name in targets]
        row["combined"] = {
            "amount_100m": sum(value for value in amounts if value is not None)
            if len(amounts) == 4 and all(value is not None for value in amounts) else None,
            "amount_share_of_a": sum(value for value in shares if value is not None)
            if len(shares) == 4 and all(value is not None for value in shares) else None,
        }
        out.append(row)
    return out


def _innovation(path: Path, market_history: list[dict[str, object]], target_date: str) -> list[dict[str, object]]:
    denominator = {row["date"]: row.get("total_amount_100m") for row in market_history}
    rows = []
    for raw in _read_csv(path):
        row_date = str(raw.get("日期") or raw.get("date") or "")[:10]
        if not row_date or row_date > target_date:
            continue
        raw_amount = _num(raw.get("成交额"))
        amount = raw_amount / 1e8 if raw_amount is not None else _num(raw.get("amount_100m"))
        denominator_value = denominator.get(row_date)
        share = amount / denominator_value if amount is not None and denominator_value not in (None, 0) else None
        rows.append({
            "date": row_date,
            "amount_100m": amount,
            "amount_share_of_a": share,
            "turnover": _num(raw.get("换手率")) if "换手率" in raw else _num(raw.get("turnover")),
            "return": _num(raw.get("日收益率")) if "日收益率" in raw else _num(raw.get("return")),
            "volume": _num(raw.get("成交量")) if "成交量" in raw else _num(raw.get("volume")),
            "source": str(raw.get("数据源") or raw.get("source") or ""),
        })
    return sorted(rows, key=lambda row: row["date"])


def build_report_data(target_date: str, root: Path = Path(".")) -> dict[str, object]:
    output_dir = root / "output" / target_date
    canonical_validation_path = output_dir / "canonical_validation.json"
    canonical_validation = (
        _read_json(canonical_validation_path)
        if canonical_validation_path.exists()
        else {"status": "UNKNOWN", "failures": [], "warnings": [], "tables": {}}
    )

    market_history = _market_history(root / "data/history/market_core.csv", target_date)
    indices_history = _indices_history(root / "data/history/indices_history.csv", target_date)
    sw_industry = _sw_industry(root / "data/sw_industry_latest.csv")
    hot_all = _hot_rows(root / "data/history/hot_stocks.csv", target_date)
    latest_hot = [row for row in hot_all if row["date"] == target_date]
    matrix = build_hot_stock_matrix(hot_all)
    sw_crowding = _sw_crowding(root / "data/history/sw_analysis_daily_second.csv", market_history, target_date)
    innovation = _innovation(root / "data/history/innovation_drug_eastmoney.csv", market_history, target_date)
    gaps = scan_history_gaps(root, target_date)

    latest_market = market_history[-1]["date"] if market_history else None
    latest_market_row = market_history[-1] if market_history and latest_market == target_date else {}
    unresolved: list[dict[str, object]] = []
    if gaps["indices"]:
        unresolved.append({"module": "indices_history", "level": "WARN", "detail": gaps["indices"]})
    if gaps["market_denominator_dates"]:
        unresolved.append({"module": "market_denominator", "level": "WARN", "detail": gaps["market_denominator_dates"]})
    expected_hot = int(latest_market_row.get("hot_count") or 0)
    if len(latest_hot) != expected_hot:
        unresolved.append({
            "module": "hot_stocks_latest",
            "level": "FAIL",
            "detail": {"expected": expected_hot, "actual": len(latest_hot)},
        })
    if canonical_validation.get("status") == "FAIL":
        unresolved.append({
            "module": "canonical_validation",
            "level": "FAIL",
            "detail": canonical_validation.get("failures") or [],
        })
    elif canonical_validation.get("status") in ("WARN", "UNKNOWN"):
        unresolved.append({
            "module": "canonical_validation",
            "level": "WARN",
            "detail": canonical_validation.get("warnings") or ["canonical validation status unknown"],
        })

    sw_latest = max((str(row.get("日期") or "")[:10] for row in sw_industry if row.get("日期")), default=None)
    crowd_latest = sw_crowding[-1]["date"] if sw_crowding else None
    innovation_latest = innovation[-1]["date"] if innovation else None
    status = "FAIL" if any(item["level"] == "FAIL" for item in unresolved) else ("WARN" if unresolved else "PASS")

    return {
        "meta": {
            "report_name": "A股每日市场监控",
            "report_date": target_date,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "latest_market_date": latest_market,
            "status": status,
            "canonical_validation_status": canonical_validation.get("status"),
        },
        "market_history": market_history,
        "indices_history": indices_history,
        "sw_industry_latest": sw_industry,
        "hot_stock_matrix": matrix,
        "hot_stocks_latest": latest_hot,
        "sw_crowding_history": sw_crowding,
        "innovation_history": innovation,
        "quality": {
            "status": status,
            "unresolved": unresolved,
            "module_latest_dates": {
                "market": latest_market,
                "indices": max((row["date"] for row in indices_history), default=None),
                "sw_industry": sw_latest,
                "sw_crowding": crowd_latest,
                "innovation": innovation_latest,
            },
            "history_gaps": gaps,
            "canonical_validation": {
                "status": canonical_validation.get("status"),
                "failures": canonical_validation.get("failures") or [],
                "warnings": canonical_validation.get("warnings") or [],
                "tables": canonical_validation.get("tables") or {},
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build normalized report_data.json for the HTML market monitor")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root)
    report = build_report_data(args.target_date, root)
    output = root / "output" / args.target_date / "report_data.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report_data={output} status={report['meta']['status']}")


if __name__ == "__main__":
    main()
