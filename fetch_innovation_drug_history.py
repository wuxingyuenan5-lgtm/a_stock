#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import time
import pandas as pd
import requests
import akshare as ak

OUT = Path("data/innovation_drug_history_2026.csv")
START = "20260105"
END = "20260810"
BOARD_NAME = "创新药"
THS_INDEX = "886015"
THS_DETAIL_CODE = "308014"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def parse_float_shares() -> tuple[float, int]:
    """Current THS constituent float shares; used as an explicit historical turnover proxy denominator."""
    total_shares = 0.0
    seen: set[str] = set()
    empty_pages = 0
    for page in range(1, 30):
        url = f"https://q.10jqka.com.cn/gn/detail/field/264648/order/desc/page/{page}/ajax/1/code/{THS_DETAIL_CODE}"
        response = requests.get(url, headers={"User-Agent": UA, "Referer": f"https://q.10jqka.com.cn/gn/detail/code/{THS_DETAIL_CODE}/"}, timeout=30)
        response.raise_for_status()
        tables = pd.read_html(response.text)
        stock_table = None
        for table in tables:
            cols = [str(x) for x in table.columns]
            if "代码" in cols and "流通股" in cols:
                stock_table = table
                break
        if stock_table is None or stock_table.empty:
            empty_pages += 1
            if empty_pages >= 2:
                break
            continue
        empty_pages = 0
        for _, row in stock_table.iterrows():
            code = str(row["代码"]).split(".")[0].zfill(6)
            if code in seen:
                continue
            raw = str(row["流通股"]).strip()
            match = re.search(r"([0-9.]+)\s*亿", raw)
            if match:
                shares = float(match.group(1)) * 1e8
            else:
                match = re.search(r"([0-9.]+)\s*万", raw)
                shares = float(match.group(1)) * 1e4 if match else None
            if shares and shares > 0:
                total_shares += shares
                seen.add(code)
        if len(stock_table) < 20:
            break
        time.sleep(0.15)
    if total_shares <= 0 or not seen:
        raise RuntimeError("failed to parse THS innovation-drug constituent float shares")
    return total_shares, len(seen)


def main() -> None:
    hist = ak.stock_board_concept_index_ths(symbol=BOARD_NAME, start_date=START, end_date=END).copy()
    required = {"日期", "收盘价", "成交量", "成交额"}
    missing = required.difference(hist.columns)
    if hist.empty or missing:
        raise RuntimeError(f"unexpected THS concept history; missing={sorted(missing)} columns={list(hist.columns)}")
    hist["日期"] = pd.to_datetime(hist["日期"], errors="coerce")
    for c in ["收盘价", "成交量", "成交额"]:
        hist[c] = pd.to_numeric(hist[c], errors="coerce")
    hist = hist.dropna(subset=["日期", "收盘价", "成交量", "成交额"]).sort_values("日期")
    hist["日收益率"] = hist["收盘价"].pct_change(fill_method=None)

    total_float_shares, constituents = parse_float_shares()
    hist["换手率"] = hist["成交量"] / total_float_shares

    out = pd.DataFrame({
        "日期": hist["日期"].dt.strftime("%Y-%m-%d"),
        "口径名称": BOARD_NAME,
        "板块代码": THS_INDEX,
        "收盘指数": hist["收盘价"],
        "成交额_亿元": hist["成交额"] / 1e8,
        "日收益率": hist["日收益率"],
        "换手率": hist["换手率"],
        "当前成份股数": constituents,
        "当前流通股合计": total_float_shares,
        "来源": "同花顺创新药886015历史指数；换手率=历史成交量/2026-08-10当前成份股流通股合计（回溯代理）",
    })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig", float_format="%.8f")
    print(f"rows={len(out)} constituents={constituents} float_shares={total_float_shares:.0f} last={out.iloc[-1].to_dict()}")


if __name__ == "__main__":
    main()
