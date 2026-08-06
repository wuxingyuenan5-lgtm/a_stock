#!/usr/bin/env python3
"""Build the 2026-08-05 A-share snapshot from TongdaXin official daily archive."""
from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import struct
import subprocess
import zipfile

import pandas as pd

import build_market_snapshot as base
import run_market_snapshot_v2 as patched
from backfill_market_and_crowding import fetch_em_kline

TARGET = "20260805"
TARGET_DATE = datetime.strptime(TARGET, "%Y%m%d")
DATA = Path("data")
ZIP = Path("hsjday.zip")
EXTRACT = Path("tdx_hsjday")


def norm(v: object) -> str:
    return base.normalize_code(v)


def exch_for(code: str) -> str:
    if code.startswith(("6", "68")):
        return "sh"
    if code.startswith(("4", "8", "92")):
        return "bj"
    return "sz"


def a_share(code: str, exchange: str) -> bool:
    if exchange == "sh":
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if exchange == "sz":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    return code.startswith(("4", "8", "92"))


def download() -> None:
    urls = [
        "https://data.tdx.com.cn/vipdoc/hsjday.zip",
        "http://www.tdx.com.cn/products/data/data/vipdoc/hsjday.zip",
    ]
    errors = []
    for url in urls:
        try:
            subprocess.run(["curl", "-L", "--fail", "--retry", "3", "--connect-timeout", "20", "-o", str(ZIP), url], check=True)
            if ZIP.stat().st_size < 1_000_000:
                raise RuntimeError(f"archive too small: {ZIP.stat().st_size}")
            return
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("TDX archive download failed: " + " | ".join(errors))


def parse_day(path: Path) -> tuple[dict[str, float], int] | None:
    raw = path.read_bytes()
    if len(raw) < 64 or len(raw) % 32:
        return None
    records = []
    for offset in range(0, len(raw), 32):
        date_i, open_i, high_i, low_i, close_i, amount_f, volume_i, _ = struct.unpack("<IIIIIfII", raw[offset:offset+32])
        if date_i <= int(TARGET):
            records.append((date_i, open_i, high_i, low_i, close_i, float(amount_f), volume_i))
    if len(records) < 2 or records[-1][0] != int(TARGET):
        return None
    prev = records[-2]
    cur = records[-1]
    close = cur[4] / 100.0
    preclose = prev[4] / 100.0
    if close <= 0 or preclose <= 0 or cur[5] <= 0 or cur[6] <= 0:
        return None
    return ({
        "收盘价": close,
        "昨收价": preclose,
        "成交额": cur[5],
        "成交量": cur[6],
        "涨跌幅": close / preclose - 1,
    }, len(records))


def limit_rate(code: str, exchange: str) -> Decimal:
    if exchange == "bj":
        return Decimal("0.30")
    if code.startswith(("300", "301", "688", "689")):
        return Decimal("0.20")
    return Decimal("0.10")


def round_price(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def index_row(label: str, filename: str, code: str) -> dict[str, object] | None:
    matches = list(EXTRACT.rglob(filename))
    if not matches:
        return None
    parsed = parse_day(matches[0])
    if not parsed:
        return None
    item, _ = parsed
    return {
        "日期": "2026-08-05", "指标": label, "数据代码": code,
        "收盘点位": item["收盘价"], "涨跌幅": item["涨跌幅"],
        "成交额_亿元": item["成交额"] / 1e8,
        "数据来源": "通达信官方盘后日线包", "数据口径": "指数日线成交额",
        "替代状态": "原始正式指数",
    }


def main() -> None:
    DATA.mkdir(exist_ok=True)
    download()
    EXTRACT.mkdir(exist_ok=True)
    with zipfile.ZipFile(ZIP) as zf:
        zf.extractall(EXTRACT)

    universe = patched.fetch_stock_universe_official().copy()
    universe["股票代码"] = universe["股票代码"].map(norm)
    universe = universe.drop_duplicates("股票代码")
    universe["上市日期"] = universe["上市日期"].astype(str).str.replace(".0", "", regex=False)
    universe = universe[~universe["股票名称"].astype(str).str.upper().str.contains("ST", na=False)]
    universe = universe[universe["上市日期"].ne(TARGET)]
    master = universe.set_index("股票代码").to_dict("index")

    stock_rows = []
    errors = []
    for path in EXTRACT.rglob("*.day"):
        stem = path.stem.lower()
        if len(stem) < 8:
            continue
        prefix, code = stem[:2], stem[-6:]
        exchange = "sh" if prefix == "sh" else "sz" if prefix == "sz" else "bj" if prefix == "bj" else exch_for(code)
        if not a_share(code, exchange) or code not in master:
            continue
        parsed = parse_day(path)
        if not parsed:
            continue
        item, session_count = parsed
        no_limit = session_count <= (1 if exchange == "bj" else 5)
        rate = limit_rate(code, exchange)
        close_d = round_price(item["收盘价"])
        pre_d = round_price(item["昨收价"])
        upper = (pre_d * (Decimal("1") + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lower = (pre_d * (Decimal("1") - rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        stock_rows.append({
            "日期": "2026-08-05", "股票代码": code, "股票名称": master[code]["股票名称"],
            "上市日期": master[code]["上市日期"], "收盘价": item["收盘价"],
            "涨跌幅": item["涨跌幅"], "成交额": item["成交额"], "成交量": item["成交量"],
            "交易所": exchange, "涨停": (not no_limit and close_d == upper),
            "跌停": (not no_limit and close_d == lower),
        })

    stocks = pd.DataFrame(stock_rows)
    if len(stocks) < 4900:
        raise RuntimeError(f"valid A-share rows too few: {len(stocks)}")

    mapping = base.build_sw_second_mapping()
    stocks = stocks.merge(mapping, on="股票代码", how="left")
    stocks["申万一级行业"] = stocks["申万一级行业"].fillna("未匹配")
    stocks["申万二级行业"] = stocks["申万二级行业"].fillna("未匹配")

    up = int((stocks["涨跌幅"] > 0).sum())
    down = int((stocks["涨跌幅"] < 0).sum())
    flat = int((stocks["涨跌幅"] == 0).sum())
    zt = int(stocks["涨停"].sum())
    dt = int(stocks["跌停"].sum())
    total_amount = float(stocks["成交额"].sum() / 1e8)
    hot = stocks[stocks["成交额"] >= 1e10].copy().sort_values("成交额", ascending=False)
    hot["成交额_亿元"] = hot["成交额"] / 1e8
    hot["序号"] = range(1, len(hot)+1)

    breadth = pd.DataFrame([{
        "日期": "2026-08-05", "静态过滤股票数": len(master), "最终有效股票数": len(stocks),
        "上涨家数": up, "下跌家数": down, "平盘家数": flat, "涨停家数": zt, "跌停家数": dt,
        "全部A股成交额_亿元": total_amount, "成交额超百亿个股数": len(hot),
        "百亿个股成交额合计_亿元": float(hot["成交额_亿元"].sum()), "接口错误数": len(errors),
    }])
    breadth.to_csv(DATA / "market_breadth_20260805.csv", index=False, encoding="utf-8-sig", float_format="%.8f")

    hot[["序号","日期","股票代码","股票名称","上市日期","收盘价","涨跌幅","成交额_亿元","申万一级行业","申万二级行业"]].to_csv(
        DATA / "turnover_100bn_stocks_20260805.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    industry = hot.groupby(["申万一级行业","申万二级行业"]).agg(
        百亿成交个股数=("股票代码","nunique"), 合计成交额_亿元=("成交额_亿元","sum"), 平均涨跌幅=("涨跌幅","mean")
    ).reset_index().sort_values(["百亿成交个股数","合计成交额_亿元"], ascending=[False,False])
    industry.insert(0,"排名",range(1,len(industry)+1))
    industry.to_csv(DATA / "turnover_100bn_industries_20260805.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    hot[hot["涨停"]][["股票代码","股票名称"]].to_csv(DATA / "limit_up_filtered_20260805.csv", index=False, encoding="utf-8-sig")
    hot[hot["跌停"]][["股票代码","股票名称"]].to_csv(DATA / "limit_down_filtered_20260805.csv", index=False, encoding="utf-8-sig")

    indices = [r for r in [index_row("上证50","sh000016.day","000016.SH"), index_row("中证全指","sh000985.day","000985.CSI")] if r]
    try:
        choice = fetch_em_kline("47.800007", "2026-08-01", "2026-08-05")
        choice = choice[choice["日期"].dt.strftime("%Y%m%d").eq(TARGET)].iloc[-1]
        indices.insert(1, {"日期":"2026-08-05","指标":"Choice微盘股指数","数据代码":"800007.EI","收盘点位":float(choice["收盘"]),"涨跌幅":float(choice["涨跌幅"])/100,"成交额_亿元":float(choice["成交额"])/1e8,"数据来源":"东方财富Choice指数历史行情","数据口径":"正式指数日线成交额","替代状态":"原始权威指数"})
    except Exception:
        indices.insert(1, {"日期":"2026-08-05","指标":"Choice微盘股指数","数据代码":"800007.EI","收盘点位":None,"涨跌幅":None,"成交额_亿元":None,"数据来源":"东方财富Choice指数历史行情","数据口径":"供应商暂缺","替代状态":"未使用自建替代"})
    pd.DataFrame(indices).to_csv(DATA / "market_indexes_20260805.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    pd.DataFrame([{"检查项":"通达信有效A股数","数值":len(stocks),"状态":"通过","说明":"官方盘后日线包"},{"检查项":"百亿成交股数","数值":len(hot),"状态":"通过","说明":"成交额>=100亿元"}]).to_csv(DATA / "market_quality_20260805.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(errors, columns=["股票代码","股票名称","错误"]).to_csv(DATA / "market_snapshot_errors_20260805.csv", index=False, encoding="utf-8-sig")
    print(breadth.to_string(index=False))


if __name__ == "__main__":
    main()
