from __future__ import annotations

import pandas as pd
import requests

from .collectors import fetch_a_share_spot as fetch_sina_spot
from .common import retry

EM_ALL_A_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def _fetch_eastmoney_all_a() -> pd.DataFrame:
    params = {
        "pn": "1",
        "pz": "20000",
        "po": "1",
        "np": "2",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f2,f3,f5,f6,f12,f14,f18",
    }

    def request() -> dict:
        response = requests.get(
            EM_ALL_A_URL,
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/center/gridlist.html#hs_a_board"},
            timeout=(4, 8),
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            raise RuntimeError("empty Eastmoney all-A snapshot")
        return data

    data = retry(request, attempts=2, delay=0.8)
    raw = pd.DataFrame(data["diff"])
    required = {"f2", "f3", "f5", "f6", "f12", "f14", "f18"}
    if not required.issubset(raw.columns):
        raise RuntimeError(f"Eastmoney all-A fields changed: {list(raw.columns)}")
    out = pd.DataFrame({
        "stock_code": raw["f12"].astype(str).str.extract(r"(\d{6})", expand=False),
        "stock_name": raw["f14"].astype(str),
        "close": pd.to_numeric(raw["f2"], errors="coerce"),
        "prev_close": pd.to_numeric(raw["f18"], errors="coerce"),
        "amount_yuan": pd.to_numeric(raw["f6"], errors="coerce"),
        "volume": pd.to_numeric(raw["f5"], errors="coerce"),
        "return": pd.to_numeric(raw["f3"], errors="coerce") / 100,
    }).dropna()
    out = out[(out["close"] > 0) & (out["prev_close"] > 0) & (out["amount_yuan"] > 0) & (out["volume"] > 0)]
    out = out[~out["stock_name"].str.contains("ST", case=False, na=False)]
    out = out[~out["stock_name"].str.startswith(("N", "C"), na=False)]
    out = out.drop_duplicates("stock_code", keep="last")
    if len(out) < 4500:
        raise RuntimeError(f"Eastmoney all-A snapshot too small: {len(out)}")
    out["amount_100m"] = out["amount_yuan"] / 1e8
    out["snapshot_source"] = "东方财富沪深京A股直连"
    return out


def fetch_a_share_spot_fast() -> pd.DataFrame:
    try:
        return _fetch_eastmoney_all_a()
    except Exception:
        return fetch_sina_spot()
