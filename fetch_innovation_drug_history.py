#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import pandas as pd
import akshare as ak

OUT = Path("data/innovation_drug_history_2026.csv")
START = "20260105"
END = "20260810"


def pick_board_name() -> str:
    names = ak.stock_board_concept_name_em()
    if "板块名称" not in names.columns:
        raise RuntimeError(f"unexpected concept-name columns: {list(names.columns)}")
    exact = names[names["板块名称"].astype(str).eq("创新药")]
    if not exact.empty:
        return str(exact.iloc[0]["板块名称"])
    candidates = names[names["板块名称"].astype(str).str.contains("创新药", na=False)]
    if candidates.empty:
        raise RuntimeError("Eastmoney concept board containing 创新药 was not found")
    return str(candidates.iloc[0]["板块名称"])


def main() -> None:
    board = pick_board_name()
    hist = ak.stock_board_concept_hist_em(
        symbol=board,
        period="daily",
        start_date=START,
        end_date=END,
        adjust="",
    ).copy()
    required = {"日期", "收盘", "成交额", "涨跌幅", "换手率"}
    missing = required.difference(hist.columns)
    if missing:
        raise RuntimeError(f"unexpected concept history columns; missing={sorted(missing)} got={list(hist.columns)}")
    hist["日期"] = pd.to_datetime(hist["日期"], errors="coerce")
    for c in ["收盘", "成交额", "涨跌幅", "换手率"]:
        hist[c] = pd.to_numeric(hist[c], errors="coerce")
    hist = hist.dropna(subset=["日期", "成交额"]).sort_values("日期")
    out = pd.DataFrame({
        "日期": hist["日期"].dt.strftime("%Y-%m-%d"),
        "口径名称": board,
        "收盘指数": hist["收盘"],
        "成交额_亿元": hist["成交额"] / 1e8,
        "日收益率": hist["涨跌幅"] / 100.0,
        "换手率": hist["换手率"] / 100.0,
        "来源": "东方财富概念板块/AKShare stock_board_concept_hist_em",
    })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"board={board} rows={len(out)} last={out.iloc[-1].to_dict() if len(out) else None}")


if __name__ == "__main__":
    main()
