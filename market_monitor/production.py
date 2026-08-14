from __future__ import annotations

from pathlib import Path
import time

import akshare as ak
import pandas as pd

from . import pipeline
from .collectors import (
    fetch_indices as fetch_indices_direct,
    fetch_innovation_current_em as fetch_innovation_current_direct,
)
from .common import ensure_dir, retry
from .fast_market import fetch_a_share_spot_fast
from .sw_cache import load_sw_cache


INDEX_SPOT_GROUPS = ["沪深重要指数", "上证系列指数", "深证系列指数", "指数成份", "中证系列指数"]


def _number(value):
    result = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(result) else float(result)


def _index_record_from_hist(target_date: str, definition: dict[str, str]):
    """Primary path for common indices: AKShare standard index history interface.

    Unlike the former hand-written push2his request, this uses AKShare's supported
    index_zh_a_hist wrapper and returns close, daily return and turnover amount in
    one row. The function is valid for the current-day production target only.
    """
    code = str(definition["secid"]).split(".")[-1]
    compact = target_date.replace("-", "")
    frame = retry(
        lambda: ak.index_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=compact,
            end_date=compact,
        ),
        attempts=2,
        delay=0.8,
    )
    required = {"日期", "收盘", "涨跌幅", "成交额"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        raise RuntimeError(f"index_zh_a_hist missing row/columns for {definition['name']}")
    rows = frame.copy()
    rows["__date"] = pd.to_datetime(rows["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    rows = rows[rows["__date"] == target_date]
    if rows.empty:
        raise RuntimeError(f"index_zh_a_hist target date missing: {definition['name']} {target_date}")
    row = rows.iloc[-1]
    close = _number(row["收盘"])
    ret = _number(row["涨跌幅"])
    amount = _number(row["成交额"])
    if close is None or ret is None or amount is None:
        raise RuntimeError(f"index_zh_a_hist null fields: {definition['name']}")
    return {
        "date": target_date,
        "name": definition["name"],
        "code": definition["secid"],
        "close": close,
        "return": ret / 100,
        "amount_100m": amount / 1e8,
        "source": "AKShare index_zh_a_hist / 东方财富标准指数接口",
        "status": "ok_primary_standard_index",
    }


def _index_record_from_spot(target_date: str, definition: dict[str, str]):
    """Current-day bulk index quote fallback; useful for Choice proprietary indices."""
    code = str(definition["secid"]).split(".")[-1]
    name = definition["name"]
    errors = []
    for group in INDEX_SPOT_GROUPS:
        try:
            frame = retry(lambda g=group: ak.stock_zh_index_spot_em(symbol=g), attempts=2, delay=0.5)
        except Exception as exc:
            errors.append(f"{group}:{exc}")
            continue
        if frame is None or frame.empty or not {"代码", "名称", "最新价", "涨跌幅", "成交额"}.issubset(frame.columns):
            continue
        codes = frame["代码"].astype(str).str.replace(r"\.0$", "", regex=True)
        names = frame["名称"].astype(str).str.strip()
        hit = frame[(codes == code) | (names == name)]
        if hit.empty:
            continue
        row = hit.iloc[-1]
        close = _number(row["最新价"])
        ret = _number(row["涨跌幅"])
        amount = _number(row["成交额"])
        if close is None or ret is None or amount is None:
            continue
        return {
            "date": target_date,
            "name": name,
            "code": definition["secid"],
            "close": close,
            "return": ret / 100,
            "amount_100m": amount / 1e8,
            "source": f"AKShare stock_zh_index_spot_em / 东方财富批量指数行情({group})",
            "status": "ok_bulk_spot_fallback",
        }
    raise RuntimeError("bulk index spot not found; " + " | ".join(errors[-2:]))


def fetch_indices_resilient(target_date: str, definitions: list[dict[str, str]]):
    """Fetch common indices through independent supported paths before raw direct fallback.

    Order per index:
    1) AKShare standard index history wrapper;
    2) Eastmoney bulk index spot table for the current production date;
    3) legacy direct K-line collector, followed by one delayed same-source retry.

    A failure in one interface therefore no longer blanks all three indices together.
    """
    results = []
    failed = []
    for definition in definitions:
        errors = []
        record = None
        for fetcher in (_index_record_from_hist, _index_record_from_spot):
            try:
                record = fetcher(target_date, definition)
                break
            except Exception as exc:
                errors.append(f"{fetcher.__name__}: {exc}")
        if record is None:
            failed.append((definition, errors))
            results.append(None)
        else:
            results.append(record)

    if failed:
        retry_defs = [item for item, _ in failed]
        first = fetch_indices_direct(target_date, retry_defs)
        first_map = {str(item.get("name")): item for item in first}
        still_failed = [
            d for d in retry_defs
            if (first_map.get(d["name"]) or {}).get("close") is None
            or (first_map.get(d["name"]) or {}).get("return") is None
            or (first_map.get(d["name"]) or {}).get("amount_100m") is None
        ]
        second_map = {}
        if still_failed:
            time.sleep(1.5)
            second = fetch_indices_direct(target_date, still_failed)
            second_map = {str(item.get("name")): item for item in second}

        error_map = {d["name"]: errs for d, errs in failed}
        replacement = {}
        for definition in retry_defs:
            name = definition["name"]
            candidate = first_map.get(name)
            retry_candidate = second_map.get(name)
            if retry_candidate is not None and all(
                retry_candidate.get(key) is not None for key in ("close", "return", "amount_100m")
            ):
                candidate = dict(retry_candidate)
                candidate["status"] = "ok_legacy_direct_after_second_pass"
            if candidate is None:
                candidate = {
                    "date": target_date,
                    "name": name,
                    "code": definition["secid"],
                    "close": None,
                    "return": None,
                    "amount_100m": None,
                    "source": "index resilient chain",
                    "status": "error",
                }
            if candidate.get("close") is None or candidate.get("return") is None or candidate.get("amount_100m") is None:
                candidate = dict(candidate)
                candidate["status"] = (
                    f"{candidate.get('status')}; standard/bulk/direct unavailable; "
                    + " | ".join(error_map.get(name, []))
                )
            replacement[name] = candidate

        for i, definition in enumerate(definitions):
            if results[i] is None:
                results[i] = replacement[definition["name"]]

    return results


def _innovation_em_frame_supported(start_date: str, end_date: str) -> pd.DataFrame:
    frame = retry(
        lambda: ak.stock_board_concept_hist_em(
            symbol="创新药",
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        ),
        attempts=2,
        delay=0.8,
    )
    required = {"日期", "收盘", "成交量", "成交额", "涨跌幅", "换手率"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        raise RuntimeError("stock_board_concept_hist_em returned no usable 创新药 history")
    out = pd.DataFrame({
        "日期": pd.to_datetime(frame["日期"], errors="coerce"),
        "收盘价": pd.to_numeric(frame["收盘"], errors="coerce"),
        "成交量": pd.to_numeric(frame["成交量"], errors="coerce"),
        "成交额": pd.to_numeric(frame["成交额"], errors="coerce"),
        "日收益率": pd.to_numeric(frame["涨跌幅"], errors="coerce") / 100,
        "换手率": pd.to_numeric(frame["换手率"], errors="coerce") / 100,
        "数据源": "AKShare stock_board_concept_hist_em / 东方财富创新药概念板块",
    })
    return out.dropna(subset=["日期", "收盘价", "成交额"]).sort_values("日期")


def update_innovation_history_reliable(target_date: str, history_path: Path, history_start: str) -> pd.DataFrame:
    """Reliable turnover history via supported Eastmoney concept-board interface."""
    ensure_dir(history_path.parent)
    existing = pd.DataFrame()
    if history_path.exists():
        existing = pd.read_csv(history_path, encoding="utf-8-sig")
        existing["日期"] = pd.to_datetime(existing["日期"], errors="coerce")
        last_date = existing["日期"].max()
        start = (last_date - pd.Timedelta(days=7)).strftime("%Y%m%d") if pd.notna(last_date) else history_start.replace("-", "")
    else:
        start = history_start.replace("-", "")
    try:
        fresh = _innovation_em_frame_supported(start, target_date.replace("-", ""))
    except Exception:
        return existing
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False) if not existing.empty else fresh
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.dropna(subset=["日期"]).drop_duplicates("日期", keep="last").sort_values("日期")
    exported = combined.copy()
    exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(history_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return combined


def fetch_innovation_current_reliable(target_date: str):
    """Use supported concept-board spot endpoint, which exposes direct board turnover."""
    try:
        frame = retry(lambda: ak.stock_board_concept_spot_em(symbol="创新药"), attempts=2, delay=0.8)
        if frame is None or frame.empty or not {"item", "value"}.issubset(frame.columns):
            raise RuntimeError("invalid stock_board_concept_spot_em response")
        values = {str(row["item"]).strip(): row["value"] for _, row in frame.iterrows()}
        amount = _number(values.get("成交额"))
        turnover = _number(values.get("换手率"))
        ret = _number(values.get("涨跌幅"))
        if amount is None or turnover is None or ret is None:
            raise RuntimeError("concept spot missing amount/turnover/return")
        return {
            "date": target_date,
            "amount_100m": amount / 1e8,
            "turnover": turnover / 100,
            "return": ret / 100,
            "source": "AKShare stock_board_concept_spot_em / 东方财富创新药概念板块",
        }
    except Exception:
        # Keep the former direct BK1106 call only as a same-vendor fallback.
        return fetch_innovation_current_direct(target_date)


def run(
    target_date: str,
    config_path: Path = Path("config/market_monitor.json"),
    root: Path = Path("."),
    refresh_mapping: bool = False,
):
    """Production entrypoint with resilient indices and reliable innovation turnover."""
    pipeline.fetch_a_share_spot = fetch_a_share_spot_fast
    pipeline.fetch_sw_analysis = load_sw_cache
    pipeline.fetch_indices = fetch_indices_resilient
    pipeline.update_innovation_history = update_innovation_history_reliable
    pipeline.fetch_innovation_current_em = fetch_innovation_current_reliable
    return pipeline.run(
        target_date=target_date,
        config_path=config_path,
        root=root,
        refresh_mapping=refresh_mapping,
    )
