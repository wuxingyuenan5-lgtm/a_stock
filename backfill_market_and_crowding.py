#!/usr/bin/env python3
"""Backfill 2026 market breadth and sector-crowding history.

Outputs:
- data/market_daily_history_backfilled.csv
- data/industry_crowding_history.csv
- data/backfill_quality.csv

Historical breadth universe:
- Shanghai/Shenzhen/Beijing A shares
- exclude daily ST for Shanghai/Shenzhen (BaoStock isST field)
- exclude current-name ST for Beijing (public historical ST flag unavailable)
- exclude suspended/no-trade rows
- exclude listing day

Limit-up/down counts use Eastmoney date-specific pools intersected with the
eligible daily universe. No news article is used as a numerical source.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import logging
import math
from pathlib import Path
import random
import time
from typing import Iterable

import pandas as pd
import requests

import build_market_snapshot as base

DATA_DIR = Path("data")
PART_DIR = DATA_DIR / "backfill_parts"
UA = base.UA
EM_HIST_HOSTS = [
    "https://push2his.eastmoney.com",
    "https://1.push2his.eastmoney.com",
    "https://7.push2his.eastmoney.com",
    "https://35.push2his.eastmoney.com",
]


def normalize_code(value: object) -> str:
    return str(value).strip().split(".")[-1].zfill(6)


def infer_exchange(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        return "bj"
    if code.startswith(("5", "6", "9")):
        return "sh"
    return "sz"


def safe_float(value: object) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        out = float(value)
        if math.isnan(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


def chunks(items: list[str], n: int) -> list[list[str]]:
    size = max(1, math.ceil(len(items) / n))
    return [items[i : i + size] for i in range(0, len(items), size)]


def baostock_worker(
    worker_id: int,
    codes: list[str],
    start_date: str,
    end_date: str,
    listing_dates: dict[str, str],
    output_dir: str,
) -> tuple[str, int, int]:
    import baostock as bs

    out_path = Path(output_dir) / f"bs_part_{worker_id:02d}.csv"
    failures = 0
    rows_written = 0
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    try:
        with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["日期", "股票代码", "涨跌幅", "成交额", "换手率", "交易所"])
            for position, code in enumerate(codes, start=1):
                exchange = infer_exchange(code)
                bs_code = f"{exchange}.{code}"
                try:
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,code,close,preclose,amount,turn,tradestatus,pctChg,isST",
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d",
                        adjustflag="3",
                    )
                    if rs.error_code != "0":
                        failures += 1
                        continue
                    ipo_date = listing_dates.get(code, "")
                    while rs.next():
                        row = rs.get_row_data()
                        if len(row) != 9:
                            continue
                        date, _, close, preclose, amount, turn, trade_status, pct, is_st = row
                        if trade_status != "1" or is_st == "1" or date == ipo_date:
                            continue
                        amount_v = safe_float(amount)
                        close_v = safe_float(close)
                        pct_v = safe_float(pct)
                        preclose_v = safe_float(preclose)
                        if (
                            amount_v is None
                            or close_v is None
                            or pct_v is None
                            or amount_v <= 0
                            or close_v <= 0
                            or preclose_v is None
                            or preclose_v <= 0
                        ):
                            continue
                        turn_v = safe_float(turn)
                        writer.writerow([date, code, pct_v / 100.0, amount_v, turn_v, exchange])
                        rows_written += 1
                except Exception:
                    failures += 1
                if position % 200 == 0:
                    print(f"worker={worker_id} {position}/{len(codes)} rows={rows_written} failures={failures}", flush=True)
    finally:
        bs.logout()
    return str(out_path), rows_written, failures


def em_request(url: str, params: dict, attempts: int = 7, timeout: int = 30) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1) + random.uniform(0.1, 0.5))
    assert last_error is not None
    raise last_error


def fetch_em_kline(secid: str, start_date: str, end_date: str) -> pd.DataFrame:
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,
        "fqt": 0,
        "beg": start_date.replace("-", ""),
        "end": end_date.replace("-", ""),
        "lmt": 500,
    }
    errors: list[str] = []
    for host in EM_HIST_HOSTS:
        try:
            payload = em_request(f"{host}/api/qt/stock/kline/get", params, attempts=3)
            data = payload.get("data") or {}
            klines = data.get("klines") or []
            if not klines:
                errors.append(f"{host}: empty")
                continue
            records = [item.split(",") for item in klines]
            frame = pd.DataFrame(
                records,
                columns=[
                    "日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额",
                    "振幅", "涨跌幅", "涨跌额", "换手率",
                ],
            )
            frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
            for column in ["收盘", "成交额", "涨跌幅", "换手率"]:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            return frame.dropna(subset=["日期"]).sort_values("日期")
        except Exception as exc:
            errors.append(f"{host}: {exc}")
    raise RuntimeError(f"Kline failed {secid}: {' | '.join(errors)}")


def fetch_bj_one(row: dict[str, str], start_date: str, end_date: str) -> list[list[object]]:
    code = row["股票代码"]
    if "ST" in row["股票名称"].upper():
        return []
    frame = fetch_em_kline(f"0.{code}", start_date, end_date)
    ipo_date = row["上市日期"]
    out: list[list[object]] = []
    for _, item in frame.iterrows():
        date = item["日期"].strftime("%Y-%m-%d")
        amount = safe_float(item["成交额"])
        pct = safe_float(item["涨跌幅"])
        if date == ipo_date or amount is None or amount <= 0 or pct is None:
            continue
        out.append([date, code, pct / 100.0, amount, safe_float(item["换手率"]), "bj"])
    return out


def fetch_limit_pool(endpoint: str, date: str, sort: str) -> pd.DataFrame:
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": 0,
        "pagesize": 10000,
        "sort": sort,
        "date": date.replace("-", ""),
    }
    payload = em_request(f"https://push2ex.eastmoney.com/{endpoint}", params, attempts=6)
    pool = ((payload.get("data") or {}).get("pool") or [])
    rows = []
    for item in pool:
        name = str(item.get("n") or "")
        if "ST" in name.upper():
            continue
        rows.append({"股票代码": normalize_code(item.get("c")), "股票名称": name})
    return pd.DataFrame(rows).drop_duplicates("股票代码") if rows else pd.DataFrame(columns=["股票代码", "股票名称"])


def fetch_limit_counts(date: str, eligible_codes: set[str]) -> tuple[str, int | None, int | None, str]:
    try:
        up = fetch_limit_pool("getTopicZTPool", date, "fbt:asc")
        down = fetch_limit_pool("getTopicDTPool", date, "fund:asc")
        return (
            date,
            int(up["股票代码"].isin(eligible_codes).sum()),
            int(down["股票代码"].isin(eligible_codes).sum()),
            "通过",
        )
    except Exception as exc:
        return date, None, None, f"失败: {exc}"


def prepare_universe() -> tuple[pd.DataFrame, dict[str, str]]:
    universe = base.fetch_stock_universe().copy()
    universe["股票代码"] = universe["股票代码"].map(normalize_code)
    universe["上市日期"] = pd.to_datetime(universe["上市日期"], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
    universe["上市日期"] = universe["上市日期"].fillna("")
    listing_dates = dict(zip(universe["股票代码"], universe["上市日期"]))
    return universe, listing_dates


def backfill_stock_daily(start_date: str, end_date: str, workers: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    DATA_DIR.mkdir(exist_ok=True)
    PART_DIR.mkdir(parents=True, exist_ok=True)
    universe, listing_dates = prepare_universe()
    shsz_codes = [code for code in universe["股票代码"] if infer_exchange(code) in {"sh", "sz"}]
    bj_rows = universe[universe["股票代码"].map(infer_exchange).eq("bj")][["股票代码", "股票名称", "上市日期"]].to_dict("records")

    part_files: list[str] = []
    quality_rows: list[dict[str, object]] = []
    code_parts = chunks(shsz_codes, workers)
    with ProcessPoolExecutor(max_workers=min(workers, len(code_parts))) as executor:
        futures = {
            executor.submit(
                baostock_worker,
                idx,
                code_part,
                start_date,
                end_date,
                listing_dates,
                str(PART_DIR),
            ): idx
            for idx, code_part in enumerate(code_parts)
        }
        for future in as_completed(futures):
            idx = futures[future]
            path, row_count, failures = future.result()
            part_files.append(path)
            quality_rows.append({"检查项": f"BaoStock分片{idx}", "数值": row_count, "状态": "通过" if failures < 20 else "提示", "说明": f"失败股票数={failures}"})

    frames = [pd.read_csv(path, encoding="utf-8-sig", dtype={"股票代码": str}) for path in part_files]
    shsz = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    bj_records: list[list[object]] = []
    bj_failures = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_bj_one, row, start_date, end_date): row for row in bj_rows}
        for future in as_completed(futures):
            try:
                bj_records.extend(future.result())
            except Exception:
                bj_failures += 1
    bj = pd.DataFrame(bj_records, columns=["日期", "股票代码", "涨跌幅", "成交额", "换手率", "交易所"])
    quality_rows.append({"检查项": "北交所历史行情", "数值": len(bj), "状态": "通过" if bj_failures <= 5 else "提示", "说明": f"失败股票数={bj_failures}; 历史ST按当前名称过滤"})

    daily_stock = pd.concat([shsz, bj], ignore_index=True)
    daily_stock["股票代码"] = daily_stock["股票代码"].map(normalize_code)
    daily_stock["日期"] = pd.to_datetime(daily_stock["日期"], errors="coerce")
    daily_stock["涨跌幅"] = pd.to_numeric(daily_stock["涨跌幅"], errors="coerce")
    daily_stock["成交额"] = pd.to_numeric(daily_stock["成交额"], errors="coerce")
    daily_stock = daily_stock.dropna(subset=["日期", "涨跌幅", "成交额"]).drop_duplicates(["日期", "股票代码"], keep="last")
    daily_stock.sort_values(["日期", "股票代码"], inplace=True)
    return daily_stock, pd.DataFrame(quality_rows)


def build_breadth(daily_stock: pd.DataFrame, start_date: str, end_date: str, limit_workers: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    grouped = daily_stock.groupby("日期")
    breadth = grouped.agg(
        全部A股成交额_元=("成交额", "sum"),
        有效股票数=("股票代码", "nunique"),
    ).reset_index()
    breadth["上涨家数"] = grouped["涨跌幅"].apply(lambda s: int((s > 0).sum())).values
    breadth["下跌家数"] = grouped["涨跌幅"].apply(lambda s: int((s < 0).sum())).values
    breadth["平盘家数"] = grouped["涨跌幅"].apply(lambda s: int((s == 0).sum())).values
    breadth["全部A股成交额_亿元"] = breadth.pop("全部A股成交额_元") / 1e8
    breadth["日期"] = breadth["日期"].dt.strftime("%Y-%m-%d")

    eligible_by_date = {
        date.strftime("%Y-%m-%d"): set(frame["股票代码"])
        for date, frame in daily_stock.groupby("日期")
    }
    limit_results = []
    with ThreadPoolExecutor(max_workers=limit_workers) as executor:
        futures = {
            executor.submit(fetch_limit_counts, date, codes): date
            for date, codes in eligible_by_date.items()
        }
        for future in as_completed(futures):
            limit_results.append(future.result())
    limits = pd.DataFrame(limit_results, columns=["日期", "涨停家数", "跌停家数", "涨跌停状态"])
    out = breadth.merge(limits, on="日期", how="left")
    out.sort_values("日期", inplace=True)

    quality = pd.DataFrame([
        {"检查项": "历史起始日", "数值": out["日期"].min(), "状态": "通过", "说明": start_date},
        {"检查项": "历史截止日", "数值": out["日期"].max(), "状态": "通过", "说明": end_date},
        {"检查项": "交易日数量", "数值": len(out), "状态": "通过", "说明": "由有效个股行情日期生成"},
        {"检查项": "涨跌停失败日期", "数值": int(out["涨停家数"].isna().sum()), "状态": "通过" if not out["涨停家数"].isna().any() else "提示", "说明": "失败日期保留空值，不估算"},
    ])
    return out, quality


def merge_index_history(breadth: pd.DataFrame, start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    configs = [
        ("上证50", "1.000016", "上证50涨跌幅", "上证50成交额_亿元"),
        ("Choice微盘股指数", "47.800007", "Choice微盘股指数涨跌幅", "Choice微盘股指数成交额_亿元"),
        ("中证全指", "1.000985", "中证全指涨跌幅", "中证全指成交额_亿元"),
    ]
    out = breadth.copy()
    quality_rows = []
    for name, secid, pct_col, amount_col in configs:
        try:
            frame = fetch_em_kline(secid, start_date, end_date)
            frame = frame[["日期", "涨跌幅", "成交额"]].copy()
            frame["日期"] = frame["日期"].dt.strftime("%Y-%m-%d")
            frame[pct_col] = frame["涨跌幅"] / 100.0
            frame[amount_col] = frame["成交额"] / 1e8
            out = out.merge(frame[["日期", pct_col, amount_col]], on="日期", how="left")
            quality_rows.append({"检查项": f"{name}历史", "数值": int(frame[pct_col].notna().sum()), "状态": "通过", "说明": secid})
        except Exception as exc:
            out[pct_col] = pd.NA
            out[amount_col] = pd.NA
            quality_rows.append({"检查项": f"{name}历史", "数值": 0, "状态": "提示", "说明": str(exc)})
    return out, pd.DataFrame(quality_rows)


def build_crowding(breadth: pd.DataFrame, start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    boards = [
        ("通信设备", "90.BK0448", "通信设备"),
        ("计算机设备", "90.BK0735", "计算机设备"),
        ("元件", "90.BK0459", "电子元器件"),
        ("半导体", "90.BK1036", "半导体"),
    ]
    base_frame = breadth[["日期", "全部A股成交额_亿元"]].copy()
    quality_rows = []
    for name, secid, label in boards:
        try:
            frame = fetch_em_kline(secid, start_date, end_date)
            frame["日期"] = frame["日期"].dt.strftime("%Y-%m-%d")
            frame[f"{label}成交额_亿元"] = frame["成交额"] / 1e8
            frame[f"{label}换手率"] = frame["换手率"] / 100.0
            base_frame = base_frame.merge(
                frame[["日期", f"{label}成交额_亿元", f"{label}换手率"]],
                on="日期",
                how="left",
            )
            quality_rows.append({"检查项": f"{name}板块历史", "数值": int(frame["成交额"].notna().sum()), "状态": "通过", "说明": secid})
        except Exception as exc:
            base_frame[f"{label}成交额_亿元"] = pd.NA
            base_frame[f"{label}换手率"] = pd.NA
            quality_rows.append({"检查项": f"{name}板块历史", "数值": 0, "状态": "提示", "说明": str(exc)})

    base_frame["通信设备成交额占比"] = base_frame["通信设备成交额_亿元"] / base_frame["全部A股成交额_亿元"]
    amount_cols = ["通信设备成交额_亿元", "计算机设备成交额_亿元", "电子元器件成交额_亿元", "半导体成交额_亿元"]
    base_frame["四大科技行业成交额合计_亿元"] = base_frame[amount_cols].sum(axis=1, min_count=4)
    base_frame["四大科技行业成交额占比"] = base_frame["四大科技行业成交额合计_亿元"] / base_frame["全部A股成交额_亿元"]
    base_frame.sort_values("日期", inplace=True)
    return base_frame, pd.DataFrame(quality_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-07-31")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit-workers", type=int, default=8)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stock_daily, q_stock = backfill_stock_daily(args.start_date, args.end_date, args.workers)
    breadth, q_breadth = build_breadth(stock_daily, args.start_date, args.end_date, args.limit_workers)
    history, q_index = merge_index_history(breadth, args.start_date, args.end_date)
    crowding, q_crowding = build_crowding(history, args.start_date, args.end_date)

    history_columns = [
        "日期", "上证50涨跌幅", "Choice微盘股指数涨跌幅", "中证全指涨跌幅",
        "上证50成交额_亿元", "Choice微盘股指数成交额_亿元", "中证全指成交额_亿元",
        "全部A股成交额_亿元", "上涨家数", "下跌家数", "平盘家数", "涨停家数", "跌停家数",
        "有效股票数", "涨跌停状态",
    ]
    for column in history_columns:
        if column not in history.columns:
            history[column] = pd.NA
    history[history_columns].to_csv(
        DATA_DIR / "market_daily_history_backfilled.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8f",
    )
    crowding.to_csv(
        DATA_DIR / "industry_crowding_history.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8f",
    )
    quality = pd.concat([q_stock, q_breadth, q_index, q_crowding], ignore_index=True)
    quality.to_csv(DATA_DIR / "backfill_quality.csv", index=False, encoding="utf-8-sig")
    logging.info("历史市场宽度行数=%s; 拥挤度行数=%s", len(history), len(crowding))


if __name__ == "__main__":
    main()
