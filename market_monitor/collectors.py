from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
import requests

from .common import append_history, ensure_dir, retry

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
INDEX_SPOT_GROUPS = ["沪深重要指数", "上证系列指数", "深证系列指数", "指数成份", "中证系列指数"]


def _pick(frame: pd.DataFrame, *names: str) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise KeyError(f"missing {names}; actual={list(frame.columns)}")


def _as_number(value: Any) -> float | None:
    result = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(result) else float(result)


def _normalize_a_share_spot(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"A股实时快照为空: {source}")
    code = _pick(raw, "代码", "symbol")
    name = _pick(raw, "名称", "name")
    close = _pick(raw, "最新价", "最新", "trade")
    prev = _pick(raw, "昨收", "昨收盘", "settlement")
    amount = _pick(raw, "成交额", "amount")
    volume = _pick(raw, "成交量", "volume")
    pct = _pick(raw, "涨跌幅", "changepercent")
    out = pd.DataFrame({
        "stock_code": raw[code].astype(str).str.extract(r"(\d{6})", expand=False),
        "stock_name": raw[name].astype(str),
        "close": pd.to_numeric(raw[close], errors="coerce"),
        "prev_close": pd.to_numeric(raw[prev], errors="coerce"),
        "amount_yuan": pd.to_numeric(raw[amount], errors="coerce"),
        "volume": pd.to_numeric(raw[volume], errors="coerce"),
        "return": pd.to_numeric(raw[pct], errors="coerce") / 100,
    }).dropna()
    out = out[(out["close"] > 0) & (out["prev_close"] > 0) & (out["amount_yuan"] > 0) & (out["volume"] > 0)]
    out = out[~out["stock_name"].str.contains("ST", case=False, na=False)]
    out = out[~out["stock_name"].str.startswith(("N", "C"), na=False)]
    out = out.drop_duplicates("stock_code", keep="last")
    out["amount_100m"] = out["amount_yuan"] / 1e8
    out["snapshot_source"] = source
    return out


def fetch_a_share_spot() -> pd.DataFrame:
    try:
        raw = retry(ak.stock_zh_a_spot_em, attempts=2, delay=1.0)
        result = _normalize_a_share_spot(raw, "AKShare stock_zh_a_spot_em / 东方财富")
        if len(result) >= 4500:
            return result
    except Exception:
        pass
    raw = retry(ak.stock_zh_a_spot, attempts=3, delay=2.0)
    return _normalize_a_share_spot(raw, "AKShare stock_zh_a_spot / 新浪")


def _limit_rate(code: str) -> Decimal:
    if code.startswith(("4", "8", "9")):
        return Decimal("0.30")
    if code.startswith(("300", "301", "688", "689")):
        return Decimal("0.20")
    return Decimal("0.10")


def infer_limit_counts(frame: pd.DataFrame) -> tuple[int, int]:
    up = down = 0
    for row in frame.itertuples(index=False):
        prev = Decimal(str(row.prev_close)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        close = Decimal(str(row.close)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rate = _limit_rate(str(row.stock_code))
        upper = (prev * (1 + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lower = (prev * (1 - rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        up += int(close == upper)
        down += int(close == lower)
    return up, down


def fetch_eastmoney_index(target_date: str, secid: str, name: str) -> dict[str, object]:
    compact = target_date.replace("-", "")
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "0", "beg": compact, "end": compact, "lmt": "10",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    def request() -> dict[str, object]:
        response = requests.get(EM_KLINE_URL, params=params, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=8)
        response.raise_for_status()
        payload = response.json()
        rows = (payload.get("data") or {}).get("klines") or []
        if not rows:
            raise RuntimeError("empty kline")
        values = rows[-1].split(",")
        return {
            "date": values[0], "name": name, "code": secid, "close": float(values[2]),
            "return": float(values[8]) / 100, "amount_100m": float(values[6]) / 1e8,
            "source": "东方财富历史接口", "status": "ok",
        }
    return retry(request, attempts=2, delay=0.8)


def _fetch_index_group(group: str) -> pd.DataFrame:
    try:
        frame = retry(lambda: ak.stock_zh_index_spot_em(symbol=group), attempts=2, delay=0.8)
        return frame.copy() if frame is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _fetch_index_spot_pool() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=len(INDEX_SPOT_GROUPS)) as executor:
        futures = {executor.submit(_fetch_index_group, group): group for group in INDEX_SPOT_GROUPS}
        for future in as_completed(futures):
            frame = future.result()
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame()
    pool = pd.concat(frames, ignore_index=True)
    if "代码" in pool.columns:
        pool["代码"] = pool["代码"].astype(str).str.extract(r"(\d{6})", expand=False)
        pool = pool.drop_duplicates("代码", keep="first")
    return pool


def fetch_indices(target_date: str, definitions: list[dict[str, str]]) -> list[dict[str, object]]:
    pool = _fetch_index_spot_pool()
    records: list[dict[str, object]] = []
    for item in definitions:
        code = item["secid"].split(".")[-1]
        selected = pool[pool["代码"] == code] if not pool.empty and "代码" in pool.columns else pd.DataFrame()
        if not selected.empty:
            row = selected.iloc[-1]
            close = _as_number(row.get("最新价"))
            pct = _as_number(row.get("涨跌幅"))
            amount = _as_number(row.get("成交额"))
            if close is not None:
                records.append({
                    "date": target_date, "name": item["name"], "code": item["secid"],
                    "close": close, "return": pct / 100 if pct is not None else None,
                    "amount_100m": amount / 1e8 if amount is not None else None,
                    "source": "AKShare stock_zh_index_spot_em / 东方财富实时指数", "status": "ok",
                })
                continue
        try:
            records.append(fetch_eastmoney_index(target_date, item["secid"], item["name"]))
        except Exception as exc:
            records.append({
                "date": target_date, "name": item["name"], "code": item["secid"],
                "close": None, "return": None, "amount_100m": None,
                "source": "东方财富指数接口", "status": f"error: {exc}",
            })
    return records


def fetch_sw_analysis(target_date: str) -> pd.DataFrame:
    target = datetime.strptime(target_date, "%Y-%m-%d")
    start = (target - timedelta(days=10)).strftime("%Y%m%d")
    end = target.strftime("%Y%m%d")
    try:
        frame = retry(lambda: ak.index_analysis_daily_sw(symbol="二级行业", start_date=start, end_date=end), attempts=2, delay=2.0).copy()
        return pd.DataFrame() if frame is None else frame
    except Exception:
        return pd.DataFrame()


def fetch_innovation_current_em(target_date: str) -> dict[str, object] | None:
    try:
        frame = retry(lambda: ak.stock_board_concept_spot_em(symbol="创新药"), attempts=2, delay=1.0)
    except Exception:
        return None
    if frame is None or frame.empty or not {"item", "value"}.issubset(frame.columns):
        return None
    values = {str(row["item"]).strip(): row["value"] for _, row in frame.iterrows()}
    amount_yuan = _as_number(values.get("成交额"))
    turnover_pct = _as_number(values.get("换手率"))
    return_pct = _as_number(values.get("涨跌幅"))
    close = _as_number(values.get("最新"))
    if amount_yuan is None and turnover_pct is None and return_pct is None:
        return None
    return {
        "date": target_date, "close": close,
        "amount_100m": amount_yuan / 1e8 if amount_yuan is not None else None,
        "turnover": turnover_pct / 100 if turnover_pct is not None else None,
        "return": return_pct / 100 if return_pct is not None else None,
        "source": "东方财富 stock_board_concept_spot_em",
    }


def fetch_innovation_current_ths(target_date: str) -> dict[str, object] | None:
    try:
        frame = retry(lambda: ak.stock_board_concept_info_ths(symbol="创新药"), attempts=2, delay=1.0)
    except Exception:
        return None
    if frame is None or frame.empty or not {"项目", "值"}.issubset(frame.columns):
        return None
    values = {str(row["项目"]).strip(): row["值"] for _, row in frame.iterrows()}
    amount_raw = values.get("成交额(亿)")
    return_raw = values.get("板块涨幅")
    amount = _as_number(str(amount_raw).replace("亿", "")) if amount_raw is not None else None
    ret = _as_number(str(return_raw).replace("%", "")) if return_raw is not None else None
    return {
        "date": target_date, "amount_100m": amount, "turnover": None,
        "return": ret / 100 if ret is not None else None,
        "source": "同花顺 stock_board_concept_info_ths",
    } if amount is not None or ret is not None else None


def update_innovation_history(target_date: str, history_path: Path, history_start: str) -> pd.DataFrame:
    """Eastmoney one-source history with direct turnover."""
    ensure_dir(history_path.parent)
    existing = pd.DataFrame()
    if history_path.exists():
        existing = pd.read_csv(history_path, encoding="utf-8-sig")
        existing["日期"] = pd.to_datetime(existing["日期"], errors="coerce")
        last_date = existing["日期"].max()
        start = (last_date - pd.Timedelta(days=7)).strftime("%Y%m%d")
    else:
        start = history_start.replace("-", "")
    try:
        fresh = retry(lambda: ak.stock_board_concept_hist_em(symbol="创新药", period="daily", start_date=start, end_date=target_date.replace("-", ""), adjust=""), attempts=2, delay=1.0).copy()
    except Exception:
        return existing
    if fresh.empty or not {"日期", "收盘", "成交量", "成交额", "换手率"}.issubset(fresh.columns):
        return existing
    fresh = fresh.rename(columns={"收盘": "收盘价"})
    fresh["日期"] = pd.to_datetime(fresh["日期"], errors="coerce")
    for column in ("收盘价", "成交量", "成交额", "换手率"):
        fresh[column] = pd.to_numeric(fresh[column], errors="coerce")
    fresh["换手率"] = fresh["换手率"] / 100
    fresh["日收益率"] = pd.to_numeric(fresh["涨跌幅"], errors="coerce") / 100 if "涨跌幅" in fresh.columns else fresh["收盘价"].pct_change(fill_method=None)
    fresh = fresh.dropna(subset=["日期", "收盘价", "成交量", "成交额"]).sort_values("日期")
    fresh["数据源"] = "东方财富概念板块历史"
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False) if not existing.empty else fresh
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.dropna(subset=["日期"]).drop_duplicates("日期", keep="last").sort_values("日期")
    combined["20日成交量活跃度代理"] = combined["成交量"] / combined["成交量"].rolling(20, min_periods=1).mean()
    exported = combined.copy(); exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(history_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return combined


def update_innovation_history_ths(target_date: str, history_path: Path, history_start: str) -> pd.DataFrame:
    """Separate fallback history; never mixed into the Eastmoney cache."""
    ensure_dir(history_path.parent)
    existing = pd.DataFrame()
    if history_path.exists():
        existing = pd.read_csv(history_path, encoding="utf-8-sig")
        existing["日期"] = pd.to_datetime(existing["日期"], errors="coerce")
        last_date = existing["日期"].max(); start = (last_date - pd.Timedelta(days=7)).strftime("%Y%m%d")
    else:
        start = history_start.replace("-", "")
    try:
        fresh = retry(lambda: ak.stock_board_concept_index_ths(symbol="创新药", start_date=start, end_date=target_date.replace("-", "")), attempts=2, delay=1.0).copy()
    except Exception:
        return existing
    if fresh.empty or not {"日期", "收盘价", "成交量", "成交额"}.issubset(fresh.columns):
        return existing
    fresh["日期"] = pd.to_datetime(fresh["日期"], errors="coerce")
    for column in ("收盘价", "成交量", "成交额"):
        fresh[column] = pd.to_numeric(fresh[column], errors="coerce")
    fresh["日收益率"] = fresh["收盘价"].pct_change(fill_method=None)
    fresh["换手率"] = None
    fresh["数据源"] = "同花顺概念指数历史"
    fresh = fresh.dropna(subset=["日期", "收盘价", "成交量", "成交额"]).sort_values("日期")
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False) if not existing.empty else fresh
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.dropna(subset=["日期"]).drop_duplicates("日期", keep="last").sort_values("日期")
    combined["20日成交量活跃度代理"] = combined["成交量"] / combined["成交量"].rolling(20, min_periods=1).mean()
    exported = combined.copy(); exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(history_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return combined


def update_market_history(path: Path, market: dict[str, object]) -> pd.DataFrame:
    return append_history(path, market, key="date")
