#!/usr/bin/env python3
"""Optimized audit runner with an authoritative Choice micro-cap index.

Changes from v5:
- use the published Choice Micro-cap Index (800007.EI / Eastmoney secid 47.800007);
- never substitute a self-built micro-cap portfolio;
- append one verified daily row to data/market_daily_history.csv;
- keep the full >100bn turnover stock list and clean Shenwan ranking.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

import pandas as pd
import requests

import build_market_snapshot as base
import run_market_snapshot_v4  # noqa: F401  # corrected Tencent market-cap fields
import run_market_snapshot_v2 as source
import run_market_snapshot_v3 as report
import run_market_snapshot_v5 as clean_rank

BEIJING = timezone(timedelta(hours=8))
HISTORY_FILE = Path("data/market_daily_history.csv")


def _quote_date(value: object) -> str:
    """Normalize an Eastmoney quote timestamp/date to YYYYMMDD."""
    if value is None:
        return ""
    text = str(value).strip().replace(".0", "")
    if text.isdigit() and len(text) >= 8 and text[:8].startswith("20"):
        return text[:8]
    try:
        stamp = int(float(text))
    except (TypeError, ValueError):
        return ""
    if stamp > 1_000_000_000:
        return datetime.fromtimestamp(stamp, BEIJING).strftime("%Y%m%d")
    return ""


def fetch_choice_micro_index(target_date: str) -> dict[str, object]:
    """Fetch the published Choice Micro-cap Index current close snapshot.

    Eastmoney exposes the Choice index under secid=47.800007. The routine
    deliberately has no synthetic fallback: missing vendor data is a hard
    failure so the workbook never labels a custom portfolio as an index.
    """
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": "47.800007",
        "fields": "f43,f48,f57,f58,f60,f86,f124,f170",
        "invt": 2,
        "fltt": 2,
    }
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": base.UA, "Referer": "https://quote.eastmoney.com/"},
        timeout=25,
    )
    response.raise_for_status()
    data = (response.json().get("data") or {})
    name = str(data.get("f58") or "").strip()
    close = pd.to_numeric(data.get("f43"), errors="coerce")
    previous = pd.to_numeric(data.get("f60"), errors="coerce")
    amount = pd.to_numeric(data.get("f48"), errors="coerce")
    pct = pd.to_numeric(data.get("f170"), errors="coerce")
    quote_date = _quote_date(data.get("f86")) or _quote_date(data.get("f124"))

    if "微盘" not in name:
        raise RuntimeError(f"Choice微盘指数名称校验失败: {name!r}")
    if pd.isna(close) or float(close) <= 0:
        raise RuntimeError("Choice微盘指数最新价为空")
    if quote_date and quote_date != target_date:
        raise RuntimeError(f"Choice微盘指数日期为 {quote_date}，目标日为 {target_date}")
    if not quote_date and target_date != datetime.now(BEIJING).strftime("%Y%m%d"):
        raise RuntimeError("Choice微盘指数未返回可验证日期，拒绝用于历史目标日")

    if pd.isna(pct):
        if pd.isna(previous) or float(previous) <= 0:
            raise RuntimeError("Choice微盘指数缺少涨跌幅和昨收")
        daily_return = float(close) / float(previous) - 1
    else:
        daily_return = float(pct) / 100

    return {
        "日期": datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d"),
        "指标": "Choice微盘股指数",
        "数据代码": "800007.EI",
        "收盘点位": float(close),
        "涨跌幅": daily_return,
        "成交额_亿元": float(amount) / 1e8 if not pd.isna(amount) else pd.NA,
        "数据来源": "东方财富Choice指数行情",
        "数据口径": "Choice正式发布指数行情成交额",
        "替代状态": "原始权威指数；无自建替代",
    }


def fetch_authoritative_index_snapshot(target_date: str, stocks: pd.DataFrame) -> pd.DataFrame:
    """Fetch SSE 50, Choice micro-cap and CSI All Share without substitution."""
    del stocks  # index definitions are independent of the filtered A-share universe
    parsed = source._parse_tencent_index(
        source._fetch_tencent_batch(["sh000016", "sh000985"]), target_date
    )
    rows: list[dict[str, object]] = []
    for label, full_code in (("上证50", "sh000016"), ("中证全指", "sh000985")):
        item = parsed.get(full_code)
        if not item or item["close"] is None:
            raise RuntimeError(f"腾讯指数行情缺失: {label} {full_code}")
        rows.append(
            {
                "日期": datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d"),
                "指标": label,
                "数据代码": "000016.SH" if label == "上证50" else "000985.CSI",
                "收盘点位": item["close"],
                "涨跌幅": item["pct"],
                "成交额_亿元": item["amount_yi"],
                "数据来源": "腾讯财经批量行情",
                "数据口径": "指数行情成交额",
                "替代状态": "原始权威指数",
            }
        )
    rows.insert(1, fetch_choice_micro_index(target_date))
    return pd.DataFrame(rows)


def append_daily_history(target_date: str) -> None:
    """Append the audited daily summary used by the dashboard history chart."""
    suffix = target_date
    indexes = pd.read_csv(
        base.DATA_DIR / f"market_indexes_{suffix}.csv", encoding="utf-8-sig"
    )
    breadth = pd.read_csv(
        base.DATA_DIR / f"market_breadth_{suffix}.csv", encoding="utf-8-sig"
    ).iloc[0]
    by_name = indexes.set_index("指标")

    row = pd.DataFrame(
        [
            {
                "日期": datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d"),
                "上证50涨跌幅": by_name.loc["上证50", "涨跌幅"],
                "Choice微盘股指数涨跌幅": by_name.loc["Choice微盘股指数", "涨跌幅"],
                "中证全指涨跌幅": by_name.loc["中证全指", "涨跌幅"],
                "上证50成交额_亿元": by_name.loc["上证50", "成交额_亿元"],
                "Choice微盘股指数成交额_亿元": by_name.loc["Choice微盘股指数", "成交额_亿元"],
                "中证全指成交额_亿元": by_name.loc["中证全指", "成交额_亿元"],
                "全部A股成交额_亿元": breadth["全部A股成交额_亿元"],
                "上涨家数": breadth["上涨家数"],
                "下跌家数": breadth["下跌家数"],
                "平盘家数": breadth["平盘家数"],
                "涨停家数": breadth["涨停家数"],
                "跌停家数": breadth["跌停家数"],
                "成交额超百亿个股数": breadth["成交额超百亿个股数"],
                "百亿个股成交额合计_亿元": breadth["百亿个股成交额合计_亿元"],
            }
        ]
    )
    if HISTORY_FILE.exists():
        existing = pd.read_csv(HISTORY_FILE, encoding="utf-8-sig")
        combined = pd.concat([existing, row], ignore_index=True)
    else:
        combined = row
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.dropna(subset=["日期"]).drop_duplicates("日期", keep="last")
    combined.sort_values("日期", inplace=True)
    combined["日期"] = combined["日期"].dt.strftime("%Y-%m-%d")
    combined.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig", float_format="%.8f")


def main() -> None:
    args = base.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base.fetch_index_snapshot = fetch_authoritative_index_snapshot
    report.write_outputs_safe(args.target_date, args.workers)
    clean_rank.postprocess_industry_ranking(args.target_date)
    append_daily_history(args.target_date)
    logging.info("已追加市场宽度历史: %s", HISTORY_FILE)


if __name__ == "__main__":
    main()
