#!/usr/bin/env python3
"""Rebuild a unified 2026 A-share daily core history and audited sector analytics.

Outputs:
- data/daily_core_history_2026.csv
- data/hot_turnover_industry_history_long_2026.csv
- data/hot_turnover_industry_history_wide_2026.csv
- data/sw_crowding_history_2026.csv
- data/rebuild_daily_core_quality_2026.csv
- data/daily_stock_history_2026.csv (artifact only; not intended for workbook display)

Core universe by trading day:
- Shanghai / Shenzhen / Beijing A shares
- exclude daily ST where historical flag is available
- exclude current-name ST for Beijing (historical ST flag is unavailable)
- exclude suspended/no-trade rows
- exclude listing day

Historical limit-up / limit-down counts are computed from close and previous close,
using board-specific price-limit rules and excluding IPO no-limit sessions. They do
not use the Eastmoney limit pools, which omit some boards and only expose limited
historical depth for the down-limit pool.

Crowding analytics use Shenwan second-level constituents, not Eastmoney board-index
turnover fields. Aggregate turnover is calculated as total traded volume divided by
inferred aggregate free-float shares, where individual free-float shares are inferred
from volume / individual turnover rate.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
import math
from pathlib import Path
from typing import Iterable

import pandas as pd

import build_market_snapshot as base
from backfill_market_and_crowding import fetch_em_kline, infer_exchange, normalize_code, safe_float

DATA_DIR = Path("data")
PART_DIR = DATA_DIR / "daily_core_parts"
TARGET_SW2 = ["通信设备", "计算机设备", "元件", "半导体"]


def chunks(items: list[str], n: int) -> list[list[str]]:
    size = max(1, math.ceil(len(items) / n))
    return [items[i : i + size] for i in range(0, len(items), size)]


def _to_decimal_price(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def price_limit_rate(code: str, exchange: str) -> Decimal:
    if exchange == "bj":
        return Decimal("0.30")
    if code.startswith(("300", "301", "688", "689")):
        return Decimal("0.20")
    return Decimal("0.10")


def no_limit_sessions(exchange: str) -> int:
    return 1 if exchange == "bj" else 5


def baostock_worker(
    worker_id: int,
    codes: list[str],
    start_date: str,
    end_date: str,
    listing_dates: dict[str, str],
    output_dir: str,
) -> tuple[str, int, int]:
    import baostock as bs

    out_path = Path(output_dir) / f"daily_part_{worker_id:02d}.csv"
    failures = 0
    rows_written = 0
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    try:
        with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "日期", "股票代码", "收盘价", "昨收价", "成交量", "成交额",
                "换手率", "涨跌幅", "交易所", "上市日期",
            ])
            for position, code in enumerate(codes, start=1):
                exchange = infer_exchange(code)
                bs_code = f"{exchange}.{code}"
                try:
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,code,close,preclose,volume,amount,turn,tradestatus,pctChg,isST",
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
                        if len(row) != 10:
                            continue
                        date, _, close, preclose, volume, amount, turn, trade_status, pct, is_st = row
                        if trade_status != "1" or is_st == "1" or date == ipo_date:
                            continue
                        close_v = safe_float(close)
                        preclose_v = safe_float(preclose)
                        volume_v = safe_float(volume)
                        amount_v = safe_float(amount)
                        pct_v = safe_float(pct)
                        turn_v = safe_float(turn)
                        if (
                            close_v is None or preclose_v is None or volume_v is None
                            or amount_v is None or pct_v is None or close_v <= 0
                            or preclose_v <= 0 or volume_v <= 0 or amount_v <= 0
                        ):
                            continue
                        writer.writerow([
                            date, code, close_v, preclose_v, volume_v, amount_v,
                            turn_v / 100.0 if turn_v is not None else None,
                            pct_v / 100.0, exchange, ipo_date,
                        ])
                        rows_written += 1
                except Exception:
                    failures += 1
                if position % 250 == 0:
                    print(
                        f"worker={worker_id} {position}/{len(codes)} rows={rows_written} failures={failures}",
                        flush=True,
                    )
    finally:
        bs.logout()
    return str(out_path), rows_written, failures


def fetch_bj_one(row: dict[str, str], start_date: str, end_date: str) -> list[list[object]]:
    code = row["股票代码"]
    if "ST" in row["股票名称"].upper():
        return []
    frame = fetch_em_kline(f"0.{code}", start_date, end_date)
    ipo_date = row["上市日期"]
    records: list[list[object]] = []
    for _, item in frame.iterrows():
        date = item["日期"].strftime("%Y-%m-%d")
        close = safe_float(item["收盘"])
        volume = safe_float(item["成交量"])
        amount = safe_float(item["成交额"])
        pct = safe_float(item["涨跌幅"])
        turn = safe_float(item["换手率"])
        if date == ipo_date or close is None or volume is None or amount is None or pct is None:
            continue
        if close <= 0 or volume <= 0 or amount <= 0:
            continue
        preclose = close / (1.0 + pct / 100.0) if abs(1.0 + pct / 100.0) > 1e-12 else None
        if preclose is None or preclose <= 0:
            continue
        records.append([
            date, code, close, preclose, volume, amount,
            turn / 100.0 if turn is not None else None,
            pct / 100.0, "bj", ipo_date,
        ])
    return records


def prepare_universe() -> tuple[pd.DataFrame, dict[str, str]]:
    universe = base.fetch_stock_universe().copy()
    universe["股票代码"] = universe["股票代码"].map(normalize_code)
    universe["上市日期"] = pd.to_datetime(
        universe["上市日期"], format="%Y%m%d", errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    universe["上市日期"] = universe["上市日期"].fillna("")
    listing_dates = dict(zip(universe["股票代码"], universe["上市日期"]))
    return universe.drop_duplicates("股票代码"), listing_dates


def fetch_daily_stock(start_date: str, end_date: str, workers: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    DATA_DIR.mkdir(exist_ok=True)
    PART_DIR.mkdir(parents=True, exist_ok=True)
    universe, listing_dates = prepare_universe()
    shsz_codes = [code for code in universe["股票代码"] if infer_exchange(code) in {"sh", "sz"}]
    bj_rows = universe[universe["股票代码"].map(infer_exchange).eq("bj")][
        ["股票代码", "股票名称", "上市日期"]
    ].to_dict("records")

    quality: list[dict[str, object]] = []
    part_files: list[str] = []
    code_parts = chunks(shsz_codes, workers)
    with ProcessPoolExecutor(max_workers=min(workers, len(code_parts))) as executor:
        futures = {
            executor.submit(
                baostock_worker, idx, part, start_date, end_date,
                listing_dates, str(PART_DIR),
            ): idx
            for idx, part in enumerate(code_parts)
        }
        for future in as_completed(futures):
            idx = futures[future]
            path, row_count, failures = future.result()
            part_files.append(path)
            quality.append({
                "检查项": f"BaoStock分片{idx}",
                "数值": row_count,
                "状态": "通过" if failures < 20 else "提示",
                "说明": f"失败股票数={failures}",
            })

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
    bj = pd.DataFrame(
        bj_records,
        columns=[
            "日期", "股票代码", "收盘价", "昨收价", "成交量", "成交额",
            "换手率", "涨跌幅", "交易所", "上市日期",
        ],
    )
    quality.append({
        "检查项": "北交所历史行情", "数值": len(bj),
        "状态": "通过" if bj_failures <= 5 else "提示",
        "说明": f"失败股票数={bj_failures}; 历史ST按当前名称过滤",
    })

    daily = pd.concat([shsz, bj], ignore_index=True)
    daily["股票代码"] = daily["股票代码"].map(normalize_code)
    daily["日期"] = pd.to_datetime(daily["日期"], errors="coerce")
    daily["上市日期"] = pd.to_datetime(daily["上市日期"], errors="coerce")
    for column in ["收盘价", "昨收价", "成交量", "成交额", "换手率", "涨跌幅"]:
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    daily = daily.dropna(subset=["日期", "股票代码", "收盘价", "昨收价", "成交量", "成交额", "涨跌幅"])
    daily = daily.drop_duplicates(["日期", "股票代码"], keep="last")
    daily.sort_values(["日期", "股票代码"], inplace=True)
    return daily, pd.DataFrame(quality)


def mark_ipo_no_limit(daily: pd.DataFrame, start_date: str) -> pd.Series:
    no_limit = pd.Series(False, index=daily.index)
    start_dt = pd.Timestamp(start_date)
    recent = daily["上市日期"].notna() & (daily["上市日期"] >= start_dt - pd.Timedelta(days=15))
    if not recent.any():
        return no_limit
    subset = daily.loc[recent, ["股票代码", "日期", "交易所"]].copy()
    subset["交易序号"] = subset.groupby("股票代码").cumcount() + 1
    allowed = subset["交易所"].map(no_limit_sessions)
    no_limit.loc[subset.index] = subset["交易序号"] <= allowed
    return no_limit


def compute_limit_flags(daily: pd.DataFrame, start_date: str) -> pd.DataFrame:
    out = daily.copy()
    no_limit = mark_ipo_no_limit(out, start_date)
    up_flags: list[bool] = []
    down_flags: list[bool] = []
    for idx, row in out.iterrows():
        if no_limit.loc[idx]:
            up_flags.append(False)
            down_flags.append(False)
            continue
        rate = price_limit_rate(row["股票代码"], row["交易所"])
        preclose = _to_decimal_price(row["昨收价"])
        close = _to_decimal_price(row["收盘价"])
        upper = (preclose * (Decimal("1") + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lower = (preclose * (Decimal("1") - rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        up_flags.append(close == upper)
        down_flags.append(close == lower)
    out["涨停"] = up_flags
    out["跌停"] = down_flags
    return out


def build_breadth(daily: pd.DataFrame) -> pd.DataFrame:
    grouped = daily.groupby("日期", sort=True)
    breadth = grouped.agg(
        全部A股成交额_元=("成交额", "sum"),
        有效股票数=("股票代码", "nunique"),
        上涨家数=("涨跌幅", lambda s: int((s > 0).sum())),
        下跌家数=("涨跌幅", lambda s: int((s < 0).sum())),
        平盘家数=("涨跌幅", lambda s: int((s == 0).sum())),
        涨停家数=("涨停", "sum"),
        跌停家数=("跌停", "sum"),
    ).reset_index()
    breadth["全部A股成交额_亿元"] = breadth.pop("全部A股成交额_元") / 1e8
    breadth["日期"] = breadth["日期"].dt.strftime("%Y-%m-%d")
    return breadth


def merge_index_history(breadth: pd.DataFrame, start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    configs = [
        ("上证50", "1.000016", "上证50涨跌幅", "上证50成交额_亿元"),
        ("Choice微盘股指数", "47.800007", "Choice微盘股指数涨跌幅", "Choice微盘股指数成交额_亿元"),
        ("中证全指", "1.000985", "中证全指涨跌幅", "中证全指成交额_亿元"),
    ]
    out = breadth.copy()
    quality: list[dict[str, object]] = []
    for name, secid, pct_col, amount_col in configs:
        try:
            frame = fetch_em_kline(secid, start_date, end_date)[["日期", "涨跌幅", "成交额"]].copy()
            frame["日期"] = frame["日期"].dt.strftime("%Y-%m-%d")
            frame[pct_col] = frame["涨跌幅"] / 100.0
            frame[amount_col] = frame["成交额"] / 1e8
            out = out.merge(frame[["日期", pct_col, amount_col]], on="日期", how="left")
            quality.append({
                "检查项": f"{name}历史", "数值": int(frame[pct_col].notna().sum()),
                "状态": "通过", "说明": secid,
            })
        except Exception as exc:
            out[pct_col] = pd.NA
            out[amount_col] = pd.NA
            quality.append({"检查项": f"{name}历史", "数值": 0, "状态": "失败", "说明": str(exc)})
    return out, pd.DataFrame(quality)


def build_hot_history(daily: pd.DataFrame, mapping: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mapped = daily.merge(mapping, on="股票代码", how="left")
    mapped["申万一级行业"] = mapped["申万一级行业"].fillna("未匹配")
    mapped["申万二级行业"] = mapped["申万二级行业"].fillna("未匹配")
    hot = mapped[mapped["成交额"] >= 1e10].copy()
    totals = hot.groupby("日期").agg(
        百亿成交股数=("股票代码", "nunique"),
        百亿成交额合计_元=("成交额", "sum"),
    ).reset_index()
    totals["百亿成交额合计_亿元"] = totals.pop("百亿成交额合计_元") / 1e8
    totals["日期"] = totals["日期"].dt.strftime("%Y-%m-%d")

    long = hot.groupby(["日期", "申万一级行业", "申万二级行业"]).agg(
        百亿成交股数=("股票代码", "nunique"),
        合计成交额_元=("成交额", "sum"),
    ).reset_index()
    long["合计成交额_亿元"] = long.pop("合计成交额_元") / 1e8
    long["日期"] = long["日期"].dt.strftime("%Y-%m-%d")
    long.sort_values(["日期", "百亿成交股数", "合计成交额_亿元"], ascending=[True, False, False], inplace=True)

    wide = long.pivot_table(
        index=["申万一级行业", "申万二级行业"], columns="日期",
        values="百亿成交股数", aggfunc="sum", fill_value=0,
    ).reset_index()
    total_row = {"申万一级行业": "总计", "申万二级行业": "总计"}
    for date, count in totals.set_index("日期")["百亿成交股数"].items():
        total_row[date] = int(count)
    wide = pd.concat([pd.DataFrame([total_row]), wide], ignore_index=True).fillna(0)
    return totals, long, wide


def aggregate_turnover(frame: pd.DataFrame) -> float | None:
    valid = frame[(frame["换手率"].notna()) & (frame["换手率"] > 0) & (frame["成交量"] > 0)].copy()
    if valid.empty:
        return None
    valid["推算流通股数"] = valid["成交量"] / valid["换手率"]
    denominator = valid["推算流通股数"].sum()
    if denominator <= 0:
        return None
    return float(valid["成交量"].sum() / denominator)


def build_sw_crowding(daily: pd.DataFrame, mapping: pd.DataFrame, breadth: pd.DataFrame) -> pd.DataFrame:
    mapped = daily.merge(mapping, on="股票代码", how="left")
    subset = mapped[mapped["申万二级行业"].isin(TARGET_SW2)].copy()
    amount_denominator = breadth.set_index("日期")["全部A股成交额_亿元"]
    output = pd.DataFrame({"日期": sorted(daily["日期"].dt.strftime("%Y-%m-%d").unique())})

    for industry in TARGET_SW2:
        records = []
        industry_frame = subset[subset["申万二级行业"].eq(industry)]
        for date, frame in industry_frame.groupby("日期"):
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                f"{industry}成交额_亿元": float(frame["成交额"].sum() / 1e8),
                f"{industry}换手率": aggregate_turnover(frame),
                f"{industry}有效股票数": int(frame["股票代码"].nunique()),
            })
        output = output.merge(pd.DataFrame(records), on="日期", how="left")

    output["全部A股成交额_亿元"] = output["日期"].map(amount_denominator)
    output["通信设备成交额占比"] = output["通信设备成交额_亿元"] / output["全部A股成交额_亿元"]
    amount_cols = [f"{name}成交额_亿元" for name in TARGET_SW2]
    output["四行业成交额合计_亿元"] = output[amount_cols].sum(axis=1, min_count=len(amount_cols))
    output["四行业成交额占比"] = output["四行业成交额合计_亿元"] / output["全部A股成交额_亿元"]
    return output.sort_values("日期")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-08-03")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    DATA_DIR.mkdir(exist_ok=True)
    PART_DIR.mkdir(parents=True, exist_ok=True)

    daily, q_daily = fetch_daily_stock(args.start_date, args.end_date, args.workers)
    daily = compute_limit_flags(daily, args.start_date)
    breadth = build_breadth(daily)
    core, q_index = merge_index_history(breadth, args.start_date, args.end_date)

    logging.info("获取申万二级成分映射")
    mapping = base.build_sw_second_mapping()
    if mapping.empty:
        raise RuntimeError("申万二级行业成分映射为空")

    hot_totals, hot_long, hot_wide = build_hot_history(daily, mapping)
    core = core.merge(hot_totals, on="日期", how="left")
    core["百亿成交股数"] = core["百亿成交股数"].fillna(0).astype(int)
    core["百亿成交额合计_亿元"] = core["百亿成交额合计_亿元"].fillna(0.0)
    core["市场宽度"] = (core["上涨家数"] - core["下跌家数"]) / (core["上涨家数"] + core["下跌家数"])
    core.sort_values("日期", inplace=True)

    crowding = build_sw_crowding(daily, mapping, breadth)

    daily_out = daily.copy()
    daily_out["日期"] = daily_out["日期"].dt.strftime("%Y-%m-%d")
    daily_out["上市日期"] = daily_out["上市日期"].dt.strftime("%Y-%m-%d")
    daily_out.to_csv(DATA_DIR / "daily_stock_history_2026.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    core.to_csv(DATA_DIR / "daily_core_history_2026.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    hot_long.to_csv(DATA_DIR / "hot_turnover_industry_history_long_2026.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    hot_wide.to_csv(DATA_DIR / "hot_turnover_industry_history_wide_2026.csv", index=False, encoding="utf-8-sig")
    crowding.to_csv(DATA_DIR / "sw_crowding_history_2026.csv", index=False, encoding="utf-8-sig", float_format="%.8f")

    quality = pd.concat([
        q_daily,
        q_index,
        pd.DataFrame([
            {"检查项": "日频股票记录数", "数值": len(daily), "状态": "通过", "说明": f"{args.start_date}至{args.end_date}"},
            {"检查项": "核心历史交易日数", "数值": len(core), "状态": "通过", "说明": f"首日={core['日期'].min()}; 末日={core['日期'].max()}"},
            {"检查项": "涨停历史非空日数", "数值": int(core['涨停家数'].notna().sum()), "状态": "通过", "说明": "逐股价格限制规则计算"},
            {"检查项": "跌停历史非空日数", "数值": int(core['跌停家数'].notna().sum()), "状态": "通过", "说明": "逐股价格限制规则计算"},
            {"检查项": "申万二级映射股票数", "数值": int(mapping['股票代码'].nunique()), "状态": "通过", "说明": "当前申万二级成分用于历史归类"},
            {"检查项": "百亿行业历史行数", "数值": len(hot_long), "状态": "通过", "说明": "成交额>=100亿元"},
            {"检查项": "申万拥挤度历史行数", "数值": len(crowding), "状态": "通过", "说明": "成分股成交额与换手率聚合"},
        ])
    ], ignore_index=True)
    quality.to_csv(DATA_DIR / "rebuild_daily_core_quality_2026.csv", index=False, encoding="utf-8-sig")
    logging.info("完成: daily=%s core=%s hot_long=%s crowding=%s", len(daily), len(core), len(hot_long), len(crowding))


if __name__ == "__main__":
    main()
