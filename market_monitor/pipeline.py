from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

import pandas as pd

from .collectors import (
    fetch_a_share_spot,
    fetch_indices,
    fetch_innovation_current_em,
    fetch_innovation_current_ths,
    fetch_sw_analysis,
    infer_limit_counts,
    update_innovation_history,
    update_innovation_history_ths,
    update_market_history,
)
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
    return PipelinePaths(
        root=root,
        data_dir=ensure_dir(root / "data"),
        history_dir=ensure_dir(root / "data" / "history"),
        cache_dir=ensure_dir(root / "data" / "cache"),
        output_dir=ensure_dir(root / "output" / target_date),
    )


def _number(value: Any) -> float | None:
    result = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(result) else float(result)


def _sw_date_column(frame: pd.DataFrame) -> str | None:
    return next((c for c in ("发布日期", "日期", "date") if c in frame.columns), None)


def _sw_latest_date(frame: pd.DataFrame) -> str | None:
    date_col = _sw_date_column(frame)
    if frame.empty or date_col is None:
        return None
    dates = pd.to_datetime(frame[date_col], errors="coerce").dropna()
    return dates.max().strftime("%Y-%m-%d") if not dates.empty else None


def _normalize_sw_targets(
    frame: pd.DataFrame,
    target_codes: dict[str, str],
    target_date: str,
    market_amount_100m: float,
) -> dict[str, dict[str, object]]:
    code_col = next((c for c in ("指数代码", "行业代码", "代码") if c in frame.columns), None)
    if frame.empty or code_col is None:
        return {}
    amount_col = next((c for c in ("成交额", "成交额（亿元）", "成交额(亿元)") if c in frame.columns), None)
    share_col = next((c for c in ("成交额占比", "成交额占比%") if c in frame.columns), None)
    turnover_col = next((c for c in ("换手率", "换手率%") if c in frame.columns), None)
    name_col = next((c for c in ("指数名称", "行业名称", "名称") if c in frame.columns), None)
    date_col = _sw_date_column(frame)
    codes = frame[code_col].astype(str).str.replace(r"\.0$", "", regex=True)
    out: dict[str, dict[str, object]] = {}
    for label, code in target_codes.items():
        selected = frame[codes.str.startswith(str(code))].copy()
        if selected.empty:
            continue
        row_date = None
        if date_col:
            selected["__date"] = pd.to_datetime(selected[date_col], errors="coerce")
            selected = selected.sort_values("__date")
        row = selected.iloc[-1]
        if date_col and pd.notna(row.get("__date")):
            row_date = pd.Timestamp(row["__date"]).strftime("%Y-%m-%d")
        amount = _number(row[amount_col]) if amount_col else None
        share_raw = _number(row[share_col]) if share_col else None
        share = share_raw / 100 if share_raw is not None else None
        turnover_raw = _number(row[turnover_col]) if turnover_col else None
        turnover = turnover_raw / 100 if turnover_raw is not None else None
        if amount is None and share is not None and row_date == target_date and market_amount_100m:
            amount = share * market_amount_100m
        if share is None and amount is not None and row_date == target_date and market_amount_100m:
            share = amount / market_amount_100m
        out[label] = {
            "date": row_date,
            "code": code,
            "name": str(row[name_col]) if name_col else label,
            "amount_100m": amount,
            "amount_share_of_a": share,
            "turnover": turnover,
            "share_source": "申万官方成交额占比" if share_raw is not None else "derived",
        }
    return out


def _combine_sw_targets(sw_targets: dict[str, dict[str, object]]) -> dict[str, object]:
    amounts = [value.get("amount_100m") for value in sw_targets.values()]
    shares = [value.get("amount_share_of_a") for value in sw_targets.values()]
    complete_amounts = len(amounts) == 4 and all(value is not None for value in amounts)
    valid_shares = [float(value) for value in shares if value is not None]
    return {
        "amount_100m": sum(float(value) for value in amounts if value is not None) if complete_amounts else None,
        "amount_share_of_a": sum(valid_shares) if valid_shares else None,
    }


def _validation(
    target_date: str,
    market: dict[str, object],
    indices: list[dict[str, object]],
    hot: list[dict[str, object]],
    sw_targets: dict[str, dict[str, object]],
    innovation_latest: dict[str, object] | None,
    mapping_available: bool,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def add(name: str, ok: bool, level: str, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "level": level, "detail": detail})

    effective = int(market["effective_stocks"])
    breadth_sum = int(market["advance"]) + int(market["decline"]) + int(market["flat"])
    add("market_breadth_sum", effective == breadth_sum, "FAIL", f"{breadth_sum} vs {effective}")
    hot_amount = sum(float(row["amount_100m"]) for row in hot)
    add("hot_count", int(market["hot_count"]) == len(hot), "FAIL", f"{len(hot)} vs {market['hot_count']}")
    add("hot_amount", abs(hot_amount - float(market["hot_amount_100m"])) < 0.05, "FAIL", f"{hot_amount:.4f} vs {market['hot_amount_100m']}")
    index_ok = all(item.get("close") is not None and item.get("date") == target_date for item in indices)
    add("indices", index_ok, "WARN", "; ".join(f"{x['name']}={x.get('status')}" for x in indices))
    add("sw_targets", len(sw_targets) >= 4, "WARN", f"{len(sw_targets)} targets")
    innovation_ok = innovation_latest is not None and innovation_latest.get("date") == target_date
    add("innovation_current", innovation_ok, "WARN", str(innovation_latest.get("date") if innovation_latest else None))
    add("innovation_turnover", innovation_latest is not None and innovation_latest.get("turnover") is not None, "WARN", str(innovation_latest.get("turnover") if innovation_latest else None))
    add("sw_mapping_cache", mapping_available, "WARN", "available" if mapping_available else "not initialized; weekly refresh required")

    failed = [c for c in checks if not c["ok"] and c["level"] == "FAIL"]
    warned = [c for c in checks if not c["ok"] and c["level"] == "WARN"]
    return {"date": target_date, "status": "FAIL" if failed else ("WARN" if warned else "PASS"), "checks": checks}


def _prepare_innovation_history(
    frame: pd.DataFrame,
    market_history: pd.DataFrame,
    target_date: str,
    output_path: Path,
) -> tuple[dict[str, object] | None, str | None]:
    if frame.empty:
        return None, None
    export = frame.copy()
    export["date"] = export["日期"].dt.strftime("%Y-%m-%d")
    export["amount_100m"] = export["成交额"] / 1e8
    denominator = market_history.rename(columns={"total_amount_100m": "market_amount_100m"})[["date", "market_amount_100m"]]
    export = export.merge(denominator, on="date", how="left")
    export["amount_share_of_a"] = export["amount_100m"] / export["market_amount_100m"]
    export.to_csv(output_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    latest = export[export["date"] <= target_date].sort_values("date").tail(1)
    if latest.empty:
        return None, None
    row = latest.iloc[0]
    source = str(row.get("数据源") or "historical topic source")
    latest_payload = {
        "date": str(row["date"]),
        "amount_100m": _number(row["amount_100m"]),
        "amount_share_of_a": _number(row["amount_share_of_a"]),
        "turnover": _number(row.get("换手率")),
        "volume_activity_20d": _number(row["20日成交量活跃度代理"]),
        "return": _number(row["日收益率"]),
        "volume": _number(row["成交量"]),
        "source": source,
    }
    return latest_payload, str(row["date"])


def run(
    target_date: str,
    config_path: Path = Path("config/market_monitor.json"),
    root: Path = Path("."),
    refresh_mapping: bool = False,
) -> dict[str, object]:
    started = time.perf_counter()
    timings: dict[str, float] = {}
    config = load_json(root / config_path)
    paths = _paths(root, target_date)

    t0 = time.perf_counter()
    spot = fetch_a_share_spot()
    timings["market_snapshot_s"] = round(time.perf_counter() - t0, 3)
    spot_source = str(spot["snapshot_source"].iloc[0]) if "snapshot_source" in spot.columns and not spot.empty else "unknown"
    limit_up, limit_down = infer_limit_counts(spot)
    advance = int((spot["return"] > 0).sum())
    decline = int((spot["return"] < 0).sum())
    flat = int((spot["return"] == 0).sum())
    total_amount = float(spot["amount_100m"].sum())

    mapping, mapping_refreshed = load_or_refresh_mapping(
        paths.cache_dir / "sw_stock_mapping.csv",
        stale_days=int(config["mapping_refresh_days"]),
        force=refresh_mapping,
    )
    mapping_available = not mapping.empty
    hot_frame = spot[spot["amount_100m"] >= float(config["hot_stock_threshold_100m"])].copy()
    hot_frame = hot_frame.sort_values(["amount_100m", "stock_code"], ascending=[False, True])
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

    t0 = time.perf_counter()
    indices = fetch_indices(target_date, config["indices"])
    timings["indices_s"] = round(time.perf_counter() - t0, 3)

    t0 = time.perf_counter()
    sw_raw = fetch_sw_analysis(target_date)
    timings["sw_analysis_s"] = round(time.perf_counter() - t0, 3)
    sw_raw.to_csv(paths.output_dir / "sw_analysis_daily_second.csv", index=False, encoding="utf-8-sig")
    sw_targets = _normalize_sw_targets(sw_raw, config["sw_crowding_codes"], target_date, total_amount)
    sw_date = _sw_latest_date(sw_raw)

    t0 = time.perf_counter()
    em_path = paths.history_dir / "innovation_drug_eastmoney.csv"
    ths_path = paths.history_dir / "innovation_drug_ths.csv"
    innovation_history = update_innovation_history(target_date, em_path, config["history_start"])
    history_mode = "eastmoney"
    if innovation_history.empty:
        innovation_history = update_innovation_history_ths(target_date, ths_path, config["history_start"])
        history_mode = "ths" if not innovation_history.empty else "none"
    innovation_latest, innovation_history_latest_date = _prepare_innovation_history(
        innovation_history,
        market_history,
        target_date,
        paths.history_dir / "innovation_drug_enriched.csv",
    )
    innovation_current = fetch_innovation_current_em(target_date)
    current_mode = "eastmoney"
    if innovation_current is None:
        innovation_current = fetch_innovation_current_ths(target_date)
        current_mode = "ths" if innovation_current is not None else "none"
    if innovation_current is not None:
        innovation_latest = {
            "date": target_date,
            "amount_100m": innovation_current.get("amount_100m"),
            "amount_share_of_a": (float(innovation_current["amount_100m"]) / total_amount) if innovation_current.get("amount_100m") is not None and total_amount else None,
            "turnover": innovation_current.get("turnover"),
            "volume_activity_20d": innovation_latest.get("volume_activity_20d") if innovation_latest and innovation_history_latest_date == target_date else None,
            "return": innovation_current.get("return"),
            "volume": innovation_latest.get("volume") if innovation_latest and innovation_history_latest_date == target_date else None,
            "topic_code": config["innovation_drug"]["code"],
            "source": innovation_current.get("source"),
            "history_latest_date": innovation_history_latest_date,
            "history_source_mode": history_mode,
            "current_source_mode": current_mode,
            "turnover_status": "供应商直接字段" if innovation_current.get("turnover") is not None else "当前备用源不提供板块总换手率",
        }
    elif innovation_latest is not None:
        innovation_latest.update({
            "topic_code": config["innovation_drug"]["code"],
            "history_latest_date": innovation_history_latest_date,
            "history_source_mode": history_mode,
            "current_source_mode": "none",
            "turnover_status": "供应商直接字段" if innovation_latest.get("turnover") is not None else "历史备用源不提供板块总换手率",
        })
    timings["innovation_drug_s"] = round(time.perf_counter() - t0, 3)

    combined = _combine_sw_targets(sw_targets)
    payload = {
        "schema_version": "1.0",
        "date": target_date,
        "market": market,
        "indices": {item["name"]: item for item in indices},
        "hot_stocks": hot_records,
        "sw_crowding": {"date": sw_date, "targets": sw_targets, "combined": combined},
        "innovation_drug": innovation_latest,
        "rendering": {"table_order": "descending", "chart_time_order": "ascending"},
    }
    validation = _validation(target_date, market, indices, hot_records, sw_targets, innovation_latest, mapping_available)
    timings["total_s"] = round(time.perf_counter() - started, 3)
    manifest = {
        "date": target_date,
        "pipeline_version": "0.1.0",
        "sources": {
            "a_share_snapshot": spot_source,
            "indices": {item["name"]: item.get("source") for item in indices},
            "sw_analysis": "AKShare index_analysis_daily_sw / 申万",
            "innovation_drug": {"history_mode": history_mode, "current_mode": current_mode},
            "sw_mapping": "AKShare sw_index_second_info + index_component_sw",
        },
        "cache": {
            "sw_mapping_refreshed": mapping_refreshed,
            "sw_mapping_available": mapping_available,
            "market_history": str(paths.history_dir / "market_core.csv"),
            "innovation_history_eastmoney": str(em_path),
            "innovation_history_ths": str(ths_path),
        },
        "timings_seconds": timings,
    }

    write_json(paths.output_dir / "daily_payload.json", payload)
    write_json(paths.output_dir / "validation.json", validation)
    write_json(paths.output_dir / "source_manifest.json", manifest)
    hot_frame.to_csv(paths.output_dir / "hot_stocks.csv", index=False, encoding="utf-8-sig", float_format="%.10f")
    spot.to_csv(paths.output_dir / "all_a_snapshot.csv", index=False, encoding="utf-8-sig", float_format="%.10f")
    if validation["status"] == "FAIL":
        raise RuntimeError(f"validation failed: {validation}")
    return {"payload": payload, "validation": validation, "manifest": manifest, "output_dir": str(paths.output_dir)}
