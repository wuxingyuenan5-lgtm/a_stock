#!/usr/bin/env python3
"""Validation runner that patches complete Eastmoney universe pagination."""
from __future__ import annotations

import pandas as pd

import build_market_snapshot as base


def fetch_stock_universe_complete() -> pd.DataFrame:
    url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    page_size = 100
    expected_total: int | None = None

    for page in range(1, 100):
        params = {
            "pn": page,
            "pz": page_size,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "fields": "f12,f14,f20,f21,f26",
        }
        data = base.retry(lambda params=params: base.em_get(url, params).json()).get("data") or {}
        if expected_total is None:
            raw_total = data.get("total") or data.get("count")
            try:
                expected_total = int(raw_total)
            except (TypeError, ValueError):
                expected_total = None
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        if not diff:
            break

        new_count = 0
        for item in diff:
            code = base.normalize_code(item.get("f12"))
            if not code or code in seen:
                continue
            seen.add(code)
            new_count += 1
            rows.append(
                {
                    "股票代码": code,
                    "股票名称": str(item.get("f14") or "").strip(),
                    "总市值": pd.to_numeric(item.get("f20"), errors="coerce"),
                    "流通市值": pd.to_numeric(item.get("f21"), errors="coerce"),
                    "上市日期": base.parse_listing_date(item.get("f26")),
                }
            )

        if new_count == 0:
            break
        if expected_total is not None and len(seen) >= expected_total:
            break

    frame = pd.DataFrame(rows).drop_duplicates("股票代码")
    if len(frame) < 3000:
        raise RuntimeError(f"A股代码清单异常，仅取得 {len(frame)} 只")
    return frame


def skip_unavailable_official_sw(target_date: str, workers: int = 6):
    columns = [
        "日期", "行业层级", "一级行业", "指数代码", "指数名称",
        "收盘价", "成交额_亿元", "日收益率", "20日年化波动率",
    ]
    snapshot = pd.DataFrame(columns=columns)
    failures = pd.DataFrame([
        {
            "指数代码": "ALL",
            "指数名称": "申万一级/二级行业",
            "错误": f"官方免费源尚未发布 {target_date}；审核版不混用前一交易日数据",
        }
    ])
    return snapshot, failures


base.fetch_stock_universe = fetch_stock_universe_complete
base.fetch_sw_snapshot = skip_unavailable_official_sw

if __name__ == "__main__":
    base.main()
