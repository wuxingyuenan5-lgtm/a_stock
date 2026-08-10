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
EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"
INNOVATION_EM_SECID = "90.BK1106"


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
    """Use the already-validated Sina all-A snapshot on GitHub runners."""
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


def _fetch_em_klines(secid: str, beg: str, end: str, lmt: int = 1000) -> list[list[str]]:
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "beg": beg,
        "end": end,
        "lmt": str(lmt),
        "ut": EM_UT,
    }

    def request() -> list[list[str]]:
        response = requests.get(
            EM_KLINE_URL,
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=(4, 8),
        )
        response.raise_for_status()
        payload = response.json()
        raw_rows = (payload.get("data") or {}).get("klines") or []
        if not raw_rows:
            raise RuntimeError(f"empty Eastmoney kline: {secid}")
        parsed = [row.split(",") for row in raw_rows]
        return [row for row in parsed if len(row) >= 11]

    return retry(request, attempts=2, delay=0.8)


def fetch_eastmoney_index(target_date: str, secid: str, name: str) -> dict[str, object]:
    compact = target_date.replace("-", "")
    values = _fetch_em_klines(secid, compact, compact, lmt=10)[-1]
    return {
        "date": values[0],
        "name": name,
        "code": secid,
        "close": float(values[2]),
        "return": float(values[8]) / 100,
        "amount_100m": float(values[6]) / 1e8,
        "source": "东方财富历史K线直连",
        "status": "ok",
    }


def fetch_indices(target_date: str, definitions: list[dict[str, str]]) -> list[dict[str, object]]:
    """Fetch the three daily indices concurrently; each request has a hard timeout."""
    results: dict[str, dict[str, object]] = {}

    def task(item: dict[str, str]) -> dict[str, object]:
        try:
            return fetch_eastmoney_index(target_date, item["secid"], item["name"])
        except Exception as exc:
            return {
                "date": target_date,
                "name": item["name"],
                "code": item["secid"],
                "close": None,
                "return": None,
                "amount_100m": None,
                "source": "东方财富历史K线直连",
                "status": f"error: {exc}",
            }

    with ThreadPoolExecutor(max_workers=max(1, len(definitions))) as executor:
        futures = {executor.submit(task, item): item["name"] for item in definitions}
        for future in as_completed(futures):
            record = future.result()
            results[str(record["name"])] = record
    return [results[item["name"]] for item in definitions]


def fetch_sw_analysis(target_date: str) -> pd.DataFrame:
    """Optional Shenwan module. Its failure never blocks the core market payload."""
    target = datetime.strptime(target_date, "%Y-%m-%d")
    start = (target - timedelta(days=10)).strftime("%Y%m%d")
    end = target.strftime("%Y%m%d")
    try:
        frame = retry(
            lambda: ak.index_analysis_daily_sw(symbol="二级行业", start_date=start, end_date=end),
            attempts=2,
            delay=2.0,
        ).copy()
        return pd.DataFrame() if frame is None else frame
    except Exception:
        return pd.DataFrame()


def _innovation_em_frame(beg: str, end: str) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for values in _fetch_em_klines(INNOVATION_EM_SECID, beg, end, lmt=1000):
        records.append({
            "日期": pd.to_datetime(values[0]),
            "收盘价": float(values[2]),
            "成交量": float(values[5]),
            "成交额": float(values[6]),
            "日收益率": float(values[8]) / 100,
            "换手率": float(values[10]) / 100,
            "数据源": "东方财富创新药BK1106历史K线直连",
        })
    return pd.DataFrame(records)


def fetch_innovation_current_em(target_date: str) -> dict[str, object] | None:
    compact = target_date.replace("-", "")
    try:
        frame = _innovation_em_frame(compact, compact)
    except Exception:
        return None
    if frame.empty:
        return None
    row = frame.iloc[-1]
    return {
        "date": target_date,
        "close": _as_number(row["收盘价"]),
        "amount_100m": _as_number(row["成交额"]) / 1e8 if _as_number(row["成交额"]) is not None else None,
        "turnover": _as_number(row["换手率"]),
        "return": _as_number(row["日收益率"]),
        "source": "东方财富创新药BK1106历史K线直连",
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
    if amount is None and ret is None:
        return None
    return {
        "date": target_date,
        "amount_100m": amount,
        "turnover": None,
        "return": ret / 100 if ret is not None else None,
        "source": "同花顺 stock_board_concept_info_ths",
    }


def update_innovation_history(target_date: str, history_path: Path, history_start: str) -> pd.DataFrame:
    """Eastmoney BK1106 history with hard HTTP timeouts and direct turnover."""
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
        fresh = _innovation_em_frame(start, target_date.replace("-", ""))
    except Exception:
        return existing
    if fresh.empty:
        return existing
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False) if not existing.empty else fresh
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.dropna(subset=["日期"]).drop_duplicates("日期", keep="last").sort_values("日期")
    combined["20日成交量活跃度代理"] = combined["成交量"] / combined["成交量"].rolling(20, min_periods=1).mean()
    exported = combined.copy()
    exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(history_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return combined


def update_innovation_history_ths(target_date: str, history_path: Path, history_start: str) -> pd.DataFrame:
    """Separate THS fallback history; never mixed into the Eastmoney cache."""
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
        fresh = retry(
            lambda: ak.stock_board_concept_index_ths(
                symbol="创新药",
                start_date=start,
                end_date=target_date.replace("-", ""),
            ),
            attempts=2,
            delay=1.0,
        ).copy()
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
    exported = combined.copy()
    exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(history_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return combined


def update_market_history(path: Path, market: dict[str, object]) -> pd.DataFrame:
    return append_history(path, market, key="date")
