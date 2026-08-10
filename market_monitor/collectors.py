from __future__ import annotations

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


def fetch_a_share_spot() -> pd.DataFrame:
    raw = retry(ak.stock_zh_a_spot, attempts=5, delay=2.0)
    if raw is None or raw.empty:
        raise RuntimeError("A股实时快照为空")
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
    return out


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
        response = requests.get(EM_KLINE_URL, params=params, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=20)
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
    return retry(request, attempts=4, delay=1.2)


def _fetch_index_spot_pool() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for group in INDEX_SPOT_GROUPS:
        try:
            frame = retry(lambda group=group: ak.stock_zh_index_spot_em(symbol=group), attempts=2, delay=1.0)
        except Exception:
            continue
        if frame is not None and not frame.empty:
            frames.append(frame.copy())
    if not frames:
        return pd.DataFrame()
    pool = pd.concat(frames, ignore_index=True)
    if "代码" in pool.columns:
        pool["代码"] = pool["代码"].astype(str).str.extract(r"(\d{6})", expand=False)
        pool = pool.drop_duplicates("代码", keep="first")
    return pool


def fetch_indices(target_date: str, definitions: list[dict[str, str]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    failed: list[tuple[int, dict[str, str], str]] = []
    for item in definitions:
        try:
            records.append(fetch_eastmoney_index(target_date, item["secid"], item["name"]))
        except Exception as exc:
            failed.append((len(records), item, str(exc)))
            records.append({"date": target_date, "name": item["name"], "code": item["secid"], "close": None, "return": None, "amount_100m": None, "source": "东方财富历史接口", "status": f"error: {exc}"})
    if failed:
        pool = _fetch_index_spot_pool()
        if not pool.empty and "代码" in pool.columns:
            for position, item, original_error in failed:
                code = item["secid"].split(".")[-1]
                selected = pool[pool["代码"] == code]
                if selected.empty:
                    continue
                row = selected.iloc[-1]
                close = _as_number(row.get("最新价"))
                pct = _as_number(row.get("涨跌幅"))
                amount = _as_number(row.get("成交额"))
                if close is None:
                    continue
                records[position] = {
                    "date": target_date, "name": item["name"], "code": item["secid"],
                    "close": close, "return": pct / 100 if pct is not None else None,
                    "amount_100m": amount / 1e8 if amount is not None else None,
                    "source": "AKShare stock_zh_index_spot_em / 东方财富实时指数",
                    "status": f"fallback_ok; primary_error={original_error}",
                }
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


def fetch_innovation_current_ths(target_date: str) -> dict[str, object] | None:
    """Current-day THS topic snapshot. It has amount/return but no board turnover."""
    try:
        frame = retry(lambda: ak.stock_board_concept_info_ths(symbol="创新药"), attempts=3, delay=1.5)
    except Exception:
        return None
    if frame is None or frame.empty or not {"项目", "值"}.issubset(frame.columns):
        return None
    values = {str(row["项目"]).strip(): row["值"] for _, row in frame.iterrows()}
    amount_raw = values.get("成交额(亿)")
    return_raw = values.get("板块涨幅")
    amount = _as_number(str(amount_raw).replace("亿", "")) if amount_raw is not None else None
    if return_raw is None:
        ret = None
    else:
        ret = _as_number(str(return_raw).replace("%", ""))
        ret = ret / 100 if ret is not None else None
    if amount is None and ret is None:
        return None
    return {
        "date": target_date,
        "amount_100m": amount,
        "return": ret,
        "source": "同花顺 stock_board_concept_info_ths",
    }


def update_innovation_history(target_date: str, history_path: Path, history_start: str) -> pd.DataFrame:
    ensure_dir(history_path.parent)
    if history_path.exists():
        existing = pd.read_csv(history_path, encoding="utf-8-sig")
        existing["日期"] = pd.to_datetime(existing["日期"], errors="coerce")
        last_date = existing["日期"].max()
        start = (last_date - pd.Timedelta(days=7)).strftime("%Y%m%d")
    else:
        existing = pd.DataFrame()
        start = history_start.replace("-", "")
    try:
        fresh = retry(lambda: ak.stock_board_concept_index_ths(symbol="创新药", start_date=start, end_date=target_date.replace("-", "")), attempts=3, delay=2.0).copy()
    except Exception:
        if existing.empty:
            return pd.DataFrame()
        fresh = pd.DataFrame()
    if not fresh.empty:
        for column in ("收盘价", "成交量", "成交额"):
            fresh[column] = pd.to_numeric(fresh[column], errors="coerce")
        fresh["日期"] = pd.to_datetime(fresh["日期"], errors="coerce")
        fresh = fresh.dropna(subset=["日期", "收盘价", "成交量", "成交额"])
    combined = pd.concat([existing, fresh], ignore_index=True) if not existing.empty else fresh
    if combined.empty:
        return combined
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.dropna(subset=["日期"]).drop_duplicates("日期", keep="last").sort_values("日期")
    combined["日收益率"] = combined["收盘价"].pct_change(fill_method=None)
    combined["20日成交量活跃度代理"] = combined["成交量"] / combined["成交量"].rolling(20, min_periods=1).mean()
    exported = combined.copy()
    exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(history_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return combined


def update_market_history(path: Path, market: dict[str, object]) -> pd.DataFrame:
    return append_history(path, market, key="date")
