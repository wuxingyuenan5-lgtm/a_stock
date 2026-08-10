from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .collectors import fetch_a_share_spot, fetch_indices, fetch_sw_analysis, infer_limit_counts, update_innovation_history, update_market_history
from .common import ensure_dir, load_json, write_json
from .sw_mapping import load_or_refresh_mapping


@dataclass(frozen=True)
class PipelinePaths:
    root: Path
    data_dir: Path
    history_dir: Path
    cache_dir: Path
    output_dir: Path


def _paths(root: Path, target_date: str) -> PipelinePaths:
    return PipelinePaths(root=root, data_dir=ensure_dir(root / "data"), history_dir=ensure_dir(root / "data" / "history"), cache_dir=ensure_dir(root / "data" / "cache"), output_dir=ensure_dir(root / "output" / target_date))


def _number(value: Any) -> float | None:
    result = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(result) else float(result)


def _normalize_sw_targets(frame: pd.DataFrame, target_codes: dict[str, str], market_amount_100m: float) -> dict[str, dict[str, object]]:
    code_col = next((c for c in ("指数代码", "行业代码", "代码") if c in frame.columns), None)
    if frame.empty or code_col is None:
        return {}
    amount_col = next((c for c in ("成交额", "成交额（亿元）", "成交额(亿元)") if c in frame.columns), None)
    turnover_col = next((c for c in ("换手率", "换手率%") if c in frame.columns), None)
    name_col = next((c for c in ("指数名称", "行业名称", "名称") if c in frame.columns), None)
    codes = frame[code_col].astype(str).str.replace(r"\.0$", "", regex=True)
    out: dict[str, dict[str, object]] = {}
    for label, code in target_codes.items():
        selected = frame[codes.str.startswith(str(code))]
        if selected.empty:
            continue
        row = selected.iloc[-1]
        amount = _number(row[amount_col]) if amount_col else None
        turnover_raw = _number(row[turnover_col]) if turnover_col else None
        turnover = turnover_raw / 100 if turnover_raw is not None else None
        out[label] = {
            "code": code,
            "name": str(row[name_col]) if name_col else label,
            "amount_100m": amount,
            "amount_share_of_a": amount / market_amount_100m if amount is not None and market_amount_100m else None,
            "turnover": turnover,
        }
    return out


def _validation(target_date: str, market: dict[str, object], indices: list[dict[str, object]], hot: list[dict[str, object]], sw_targets: dict[str, dict[str, object]], innovation_latest: dict[str, object] | None) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    def add(name: str, ok: bool, level: str, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "level": level, "detail": detail})

    effective = int(market["effective_stocks"])
    breadth_sum = int(market["advance"]) + int(market["decline"]) + int(market["flat"])
    add("market_breadth_sum", effective == breadth_sum, "FAIL", f"{breadth_sum} vs {effective}")
    hot_amount = sum(float(row["amount_100m"]) for row in hot)
    add("hot_count", int(market["hot_count"]) == len(hot), "FAIL", f"{len(hot)} vs {market['hot_count']}")
    add("hot_amount", abs(hot_amount - float(market["hot_amount_100m"])) < 0.05, "FAIL", f"{hot_amount:.4f} vs {market['hot_amount_100m']}")
    index_dates = {str(item["date"]) for item in indices}
    add("index_dates", index_dates == {target_date}, "FAIL", str(sorted(index_dates)))
    add("sw_targets", len(sw_targets) >= 4, "WARN", f"{len(sw_targets)} targets")
    add("innovation_latest", innovation_latest is not None, "WARN", str(innovation_latest.get("date") if innovation_latest else None))

    failed = [c for c in checks if not c["ok"] and c["level"] == "FAIL"]
    warned = [c for c in checks if not c["ok"] and c["level"] == "WARN"]
    return {"date": target_date, "status": "FAIL" if failed else ("WARN" if warned else "PASS"), "checks": checks}


def run(target_date: str, config_path: Path = Path("config/market_monitor.json"), root: Path = Path("."), refresh_mapping: bool = False) -> dict[str, object]:
    config = load_json(root / config_path)
    paths = _paths(root, target_date)

    spot = fetch_a_share_spot()
    limit_up, limit_down = infer_limit_counts(spot)
    advance = int((spot["return"] > 0).sum())
    decline = int((spot["return"] < 0).sum())
    flat = int((spot["return"] == 0).sum())
    total_amount = float(spot["amount_100m"].sum())

    mapping, mapping_refreshed = load_or_refresh_mapping(paths.cache_dir / "sw_stock_mapping.csv", stale_days=int(config["mapping_refresh_days"]), force=refresh_mapping)
    hot_frame = spot[spot["amount_100m"] >= float(config["hot_stock_threshold_100m"])].copy().sort_values(["amount_100m", "stock_code"], ascending=[False, True])
    hot_frame = hot_frame.merge(mapping, on="stock_code", how="left")
    hot_frame[["sw_level1", "sw_level2"]] = hot_frame[["sw_level1", "sw_level2"]].fillna("未匹配")
    hot_frame.insert(0, "rank", range(1, len(hot_frame) + 1))
    hot_records = hot_frame[["rank", "stock_code", "stock_name", "close", "return", "amount_100m", "sw_level1", "sw_level2"]].to_dict(orient="records")
    hot_amount = float(hot_frame["amount_100m"].sum())

    market = {
        "date": target_date,
        "advance": advance,
        "decline": decline,
        "flat": flat,
        "limit_up": int(limit_up),
        "limit_down": int(limit_down),
        "effective_stocks": int(len(spot)),
        "total_amount_100m": total_amount,
        "hot_count": int(len(hot_frame)),
        "hot_amount_100m": hot_amount,
        "hot_concentration": hot_amount / total_amount if total_amount else None,
        "market_breadth": (advance - decline) / (advance + decline) if advance + decline else None,
    }
    market_history = update_market_history(paths.history_dir / "market_core.csv", market)
    indices = fetch_indices(target_date, config["indices"])

    sw_raw = fetch_sw_analysis(target_date)
    sw_raw.to_csv(paths.output_dir / "sw_analysis_daily_second.csv", index=False, encoding="utf-8-sig")
    sw_targets = _normalize_sw_targets(sw_raw, config["sw_crowding_codes"], total_amount)

    innovation = update_innovation_history(target_date, paths.history_dir / "innovation_drug_886015.csv", config["history_start"])
    innovation_export = innovation.copy()
    innovation_export["date"] = innovation_export["日期"].dt.strftime("%Y-%m-%d")
    denominator = market_history.rename(columns={"total_amount_100m": "market_amount_100m"})[["date", "market_amount_100m"]]
    innovation_export = innovation_export.merge(denominator, on="date", how="left")
    innovation_export["amount_share_of_a"] = innovation_export["成交额"] / innovation_export["market_amount_100m"]
    innovation_export.to_csv(paths.history_dir / "innovation_drug_enriched.csv", index=False, encoding="utf-8-sig", float_format="%.10f")

    latest = innovation_export[innovation_export["date"] <= target_date].sort_values("date").tail(1)
    innovation_latest = None
    if not latest.empty:
        row = latest.iloc[0]
        innovation_latest = {
            "date": str(row["date"]),
            "amount_100m": _number(row["成交额"]),
            "amount_share_of_a": _number(row["amount_share_of_a"]),
            "turnover": None,
            "volume_activity_20d": _number(row["20日成交量活跃度代理"]),
            "return": _number(row["日收益率"]),
            "volume": _number(row["成交量"]),
            "topic_code": config["innovation_drug"]["code"],
            "source": config["innovation_drug"]["source"],
            "turnover_status": "板块历史总流通股本缺少可靠可比序列，正式换手率保持空白",
        }

    payload = {
        "schema_version": "1.0",
        "date": target_date,
        "market": market,
        "indices": {item["name"]: item for item in indices},
        "hot_stocks": hot_records,
        "sw_crowding": {"date": target_date, "targets": sw_targets, "combined": {"amount_100m": sum(value["amount_100m"] or 0 for value in sw_targets.values())}},
        "innovation_drug": innovation_latest,
        "rendering": {"table_order": "descending", "chart_time_order": "ascending"},
    }
    combined_amount = payload["sw_crowding"]["combined"]["amount_100m"]
    payload["sw_crowding"]["combined"]["amount_share_of_a"] = combined_amount / total_amount if total_amount else None

    validation = _validation(target_date, market, indices, hot_records, sw_targets, innovation_latest)
    manifest = {
        "date": target_date,
        "pipeline_version": "0.1.0",
        "sources": {
            "a_share_snapshot": "AKShare stock_zh_a_spot / 新浪",
            "indices": "东方财富历史K线",
            "sw_analysis": "AKShare index_analysis_daily_sw / 申万",
            "innovation_drug": "同花顺创新药概念指数 886015",
            "sw_mapping": "AKShare sw_index_second_info + index_component_sw",
        },
        "cache": {"sw_mapping_refreshed": mapping_refreshed, "market_history": str(paths.history_dir / "market_core.csv"), "innovation_history": str(paths.history_dir / "innovation_drug_886015.csv")},
    }

    write_json(paths.output_dir / "daily_payload.json", payload)
    write_json(paths.output_dir / "validation.json", validation)
    write_json(paths.output_dir / "source_manifest.json", manifest)
    hot_frame.to_csv(paths.output_dir / "hot_stocks.csv", index=False, encoding="utf-8-sig", float_format="%.10f")
    spot.to_csv(paths.output_dir / "all_a_snapshot.csv", index=False, encoding="utf-8-sig", float_format="%.10f")
    if validation["status"] == "FAIL":
        raise RuntimeError(f"validation failed: {validation}")
    return {"payload": payload, "validation": validation, "manifest": manifest, "output_dir": str(paths.output_dir)}
