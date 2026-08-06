#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json
import time

import akshare as ak
import pandas as pd
import requests

TARGET = "2026-08-06"
TARGET_COMPACT = "20260806"
OUT_TAG = "20260805"  # retained for the temporary workflow artifact glob
DATA = Path("data")
DATA.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def pick(frame: pd.DataFrame, *names: str) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise KeyError(f"missing columns {names}; actual={list(frame.columns)}")


def fetch_spot() -> pd.DataFrame:
    last = None
    for attempt in range(1, 4):
        try:
            frame = ak.stock_zh_a_spot()
            if frame is None or frame.empty:
                raise RuntimeError("empty Sina A-share snapshot")
            return frame
        except Exception as exc:
            last = exc
            time.sleep(attempt * 3)
    raise RuntimeError(f"Sina snapshot failed: {last}")


def normalize_spot(raw: pd.DataFrame) -> pd.DataFrame:
    code_col = pick(raw, "代码", "symbol")
    name_col = pick(raw, "名称", "name")
    close_col = pick(raw, "最新价", "最新", "trade")
    preclose_col = pick(raw, "昨收", "昨收盘", "settlement")
    amount_col = pick(raw, "成交额", "amount")
    volume_col = pick(raw, "成交量", "volume")
    pct_col = pick(raw, "涨跌幅", "changepercent")
    out = pd.DataFrame({
        "股票代码": raw[code_col].astype(str).str.extract(r"(\d{6})", expand=False),
        "股票名称": raw[name_col].astype(str),
        "收盘价": num(raw[close_col]),
        "昨收价": num(raw[preclose_col]),
        "成交额_元": num(raw[amount_col]),
        "成交量": num(raw[volume_col]),
        "涨跌幅_pct": num(raw[pct_col]),
    })
    out["涨跌幅"] = out["涨跌幅_pct"] / 100.0
    out = out.dropna(subset=["股票代码", "收盘价", "昨收价", "成交额_元", "成交量", "涨跌幅"])
    out = out[(out["收盘价"] > 0) & (out["昨收价"] > 0) & (out["成交额_元"] > 0) & (out["成交量"] > 0)]
    out = out[~out["股票名称"].str.contains("ST", case=False, na=False)]
    out = out[~out["股票名称"].str.startswith(("N", "C"), na=False)]
    out = out.drop_duplicates("股票代码", keep="last")
    out["成交额（亿元）"] = out["成交额_元"] / 1e8
    return out


def limit_rate(code: str) -> Decimal:
    if code.startswith(("4", "8", "9")):
        return Decimal("0.30")
    if code.startswith(("300", "301", "688", "689")):
        return Decimal("0.20")
    return Decimal("0.10")


def limit_counts(frame: pd.DataFrame) -> tuple[int, int]:
    up = 0
    down = 0
    for row in frame.itertuples(index=False):
        pre = Decimal(str(row.昨收价)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        close = Decimal(str(row.收盘价)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rate = limit_rate(row.股票代码)
        upper = (pre * (Decimal("1") + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lower = (pre * (Decimal("1") - rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        up += int(close == upper)
        down += int(close == lower)
    return up, down


def fetch_index(secid: str, name: str) -> dict[str, object]:
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "0", "beg": TARGET_COMPACT, "end": TARGET_COMPACT,
        "lmt": "10", "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    response = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    lines = (payload.get("data") or {}).get("klines") or []
    if not lines:
        raise RuntimeError(f"no target kline for {name}")
    parts = lines[-1].split(",")
    return {
        "日期": parts[0], "指标": name, "数据代码": secid,
        "收盘点位": float(parts[2]), "涨跌幅": float(parts[8]) / 100.0,
        "成交额（亿元）": float(parts[6]) / 1e8,
        "数据源": "东方财富历史接口",
    }


raw = fetch_spot()
spot = normalize_spot(raw)
up = int((spot["涨跌幅"] > 0).sum())
down = int((spot["涨跌幅"] < 0).sum())
flat = int((spot["涨跌幅"] == 0).sum())
limit_up, limit_down = limit_counts(spot)
total_amount = float(spot["成交额（亿元）"].sum())
hot = spot[spot["成交额（亿元）"] >= 100].sort_values("成交额（亿元）", ascending=False).copy()
hot.insert(0, "当日排名", range(1, len(hot) + 1))
hot.insert(0, "日期", TARGET)
hot_amount = float(hot["成交额（亿元）"].sum())
summary = pd.DataFrame([{
    "日期": TARGET, "上涨家数": up, "下跌家数": down, "平盘家数": flat,
    "涨停家数": limit_up, "跌停家数": limit_down, "有效股票数": len(spot),
    "全部A股成交额（亿元）": total_amount, "百亿成交股数": len(hot),
    "百亿成交额（亿元）": hot_amount,
    "百亿成交集中度": hot_amount / total_amount if total_amount else None,
    "数据源": "AKShare新浪沪深京A股收盘快照+逐股涨跌停价回推",
}])
indices = pd.DataFrame([
    fetch_index("1.000016", "上证50"),
    fetch_index("47.800007", "Choice微盘"),
    fetch_index("1.000985", "中证全指"),
])
summary.to_csv(DATA / f"market_summary_{OUT_TAG}.csv", index=False, encoding="utf-8-sig")
hot.to_csv(DATA / f"turnover_100bn_stocks_{OUT_TAG}.csv", index=False, encoding="utf-8-sig")
indices.to_csv(DATA / f"index_snapshot_{OUT_TAG}.csv", index=False, encoding="utf-8-sig")
spot.to_csv(DATA / f"all_a_snapshot_{OUT_TAG}.csv", index=False, encoding="utf-8-sig")
(DATA / f"metadata_{OUT_TAG}.json").write_text(json.dumps({
    "target_date": TARGET, "effective": len(spot), "hot": len(hot),
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(summary.to_string(index=False), flush=True)
print(indices.to_string(index=False), flush=True)
