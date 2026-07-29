#!/usr/bin/env python3
"""Validation runner for the date-consistent market snapshot."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import logging
import time

import pandas as pd
import requests
import urllib3

import build_market_snapshot as base

BEIJING = timezone(timedelta(hours=8))
_ORIGINAL_FETCH_ALL = base.fetch_all_stock_history
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _date_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y%m%d")


def fetch_stock_universe_official() -> pd.DataFrame:
    """Build the A-share universe from official SSE, SZSE and BSE lists."""
    frames: list[pd.DataFrame] = []

    sh_main = base.retry(lambda: base.ak.stock_info_sh_name_code(symbol="主板A股"))
    sh_star = base.retry(lambda: base.ak.stock_info_sh_name_code(symbol="科创板"))
    for raw in (sh_main, sh_star):
        frame = raw[["证券代码", "证券简称", "上市日期"]].copy()
        frame.columns = ["股票代码", "股票名称", "上市日期"]
        frame["交易所"] = "sh"
        frames.append(frame)

    sz = base.retry(lambda: base.ak.stock_info_sz_name_code(symbol="A股列表"))
    sz_frame = sz[["A股代码", "A股简称", "A股上市日期"]].copy()
    sz_frame.columns = ["股票代码", "股票名称", "上市日期"]
    sz_frame["交易所"] = "sz"
    frames.append(sz_frame)

    bj = base.retry(base.ak.stock_info_bj_name_code)
    bj_frame = bj[["证券代码", "证券简称", "上市日期"]].copy()
    bj_frame.columns = ["股票代码", "股票名称", "上市日期"]
    bj_frame["交易所"] = "bj"
    frames.append(bj_frame)

    universe = pd.concat(frames, ignore_index=True)
    universe["股票代码"] = universe["股票代码"].map(base.normalize_code)
    universe["股票名称"] = universe["股票名称"].astype(str).str.strip()
    universe["上市日期"] = universe["上市日期"].map(_date_text)
    universe["总市值"] = pd.NA
    universe["流通市值"] = pd.NA
    universe = universe.dropna(subset=["股票代码", "股票名称"]).drop_duplicates("股票代码")
    if len(universe) < 3000:
        raise RuntimeError(f"沪深京官方A股清单异常，仅取得 {len(universe)} 只")
    return universe


def _fetch_tencent_batch(prefixed_codes: list[str]) -> str:
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed_codes)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.get(url, headers={"User-Agent": base.UA}, timeout=20)
            response.raise_for_status()
            return response.content.decode("gbk", errors="ignore")
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 0.8)
    assert last_error is not None
    raise last_error


def _parse_tencent_quotes(text: str, target_date: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.split(";"):
        if "=" not in line or '"' not in line:
            continue
        full_code = line.split("=")[0].split("_")[-1]
        values = line.split('"')[1].split("~")
        if len(values) < 50:
            continue
        code = full_code[2:]

        def num(index: int) -> float | None:
            try:
                value = values[index]
                return float(value) if value not in ("", "-") else None
            except (ValueError, IndexError):
                return None

        quote_time = values[30] if len(values) > 30 else ""
        if quote_time and not quote_time.startswith(target_date):
            continue
        pct = num(32)
        amount_wan = num(37)
        mcap_yi = num(44)
        float_mcap_yi = num(45)
        rows.append(
            {
                "股票代码": base.normalize_code(code),
                "行情名称": values[1],
                "收盘价": num(3),
                "涨跌幅": pct / 100 if pct is not None else None,
                "成交额": amount_wan * 10000 if amount_wan is not None else None,
                "行情总市值": mcap_yi * 1e8 if mcap_yi is not None else None,
                "行情流通市值": float_mcap_yi * 1e8 if float_mcap_yi is not None else None,
                "行情时间": quote_time,
            }
        )
    return rows


def fetch_tencent_market_snapshot(universe: pd.DataFrame, target_date: str) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    items = [f"{row['交易所']}{row['股票代码']}" for _, row in universe.iterrows()]
    batch_size = 250
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        text = _fetch_tencent_batch(batch)
        records.extend(_parse_tencent_quotes(text, target_date))
        time.sleep(0.08)
    frame = pd.DataFrame(records)
    if frame.empty:
        raise RuntimeError("腾讯全市场收盘行情为空")
    return frame.drop_duplicates("股票代码")


def fetch_current_close_snapshot(
    universe: pd.DataFrame, target_date: str, workers: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Use Tencent batch close quotes for today; backfill missing codes by history."""
    today = datetime.now(BEIJING).strftime("%Y%m%d")
    if target_date != today:
        return _ORIGINAL_FETCH_ALL(universe, target_date, workers)

    quote = fetch_tencent_market_snapshot(universe, target_date)
    merged = universe.merge(quote, on="股票代码", how="left")
    valid_mask = (
        merged["收盘价"].notna()
        & merged["成交额"].notna()
        & merged["涨跌幅"].notna()
        & merged["收盘价"].gt(0)
        & merged["成交额"].gt(0)
    )
    valid = merged[valid_mask].copy()
    missing = merged[~valid_mask][
        ["股票代码", "股票名称", "上市日期", "交易所", "总市值", "流通市值"]
    ].copy()

    fallback_data = pd.DataFrame()
    fallback_no_trade = pd.DataFrame(columns=["股票代码", "股票名称", "原因"])
    fallback_errors = pd.DataFrame(columns=["股票代码", "股票名称", "错误"])
    if not missing.empty:
        try:
            fallback_data, fallback_no_trade, fallback_errors = _ORIGINAL_FETCH_ALL(
                missing, target_date, min(workers, 16)
            )
        except RuntimeError as exc:
            fallback_errors = missing[["股票代码", "股票名称"]].copy()
            fallback_errors["错误"] = f"腾讯快照缺失且历史接口未回补：{exc}"

    valid["日期"] = datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d")
    valid["总市值"] = valid["行情总市值"].combine_first(valid["总市值"])
    valid["流通市值"] = valid["行情流通市值"].combine_first(valid["流通市值"])
    valid = valid[
        [
            "日期", "股票代码", "股票名称", "上市日期", "收盘价",
            "涨跌幅", "成交额", "总市值", "流通市值",
        ]
    ]

    if not fallback_data.empty:
        valid = pd.concat([valid, fallback_data], ignore_index=True)
    valid = valid.drop_duplicates("股票代码").sort_values("股票代码")
    if len(valid) < 3000:
        raise RuntimeError(f"统一股票池有效行情异常，仅取得 {len(valid)} 只")
    return valid, fallback_no_trade, fallback_errors


def _fetch_one_sw_component(row: pd.Series) -> list[dict[str, str]]:
    code = base.normalize_code(row["行业代码"])
    url = "https://www.swsresearch.com/institute-sw/api/index_publish/details/component_stocks/"
    params = {"swindexcode": code, "page": "1", "page_size": "10000"}
    headers = {"User-Agent": base.UA}
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=18, verify=False)
            response.raise_for_status()
            results = ((response.json().get("data") or {}).get("results") or [])
            return [
                {
                    "股票代码": base.normalize_code(item.get("stockcode")),
                    "申万一级行业": str(row["上级行业"]).strip(),
                    "申万二级行业": str(row["行业名称"]).strip(),
                }
                for item in results
                if item.get("stockcode")
            ]
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5)
    raise RuntimeError(f"{code} 成分获取失败: {last_error}")


def build_sw_second_mapping_fast() -> pd.DataFrame:
    """Fetch SW level-2 constituents concurrently with per-request timeouts."""
    info = base.retry(base.ak.sw_index_second_info)
    required = {"行业代码", "行业名称", "上级行业"}
    if info.empty or not required.issubset(info.columns):
        raise RuntimeError(f"申万二级行业信息异常: {list(info.columns)}")

    records: list[dict[str, str]] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(_fetch_one_sw_component, row.copy()): row for _, row in info.iterrows()}
        for future in as_completed(futures):
            row = futures[future]
            try:
                records.extend(future.result())
            except Exception as exc:
                failures += 1
                logging.warning("申万二级行业成分失败 %s: %s", row["行业代码"], exc)
    if not records:
        raise RuntimeError("申万二级行业映射为空")
    logging.info("申万二级映射完成：%s 条，失败行业 %s 个", len(records), failures)
    return pd.DataFrame(records).drop_duplicates("股票代码", keep="first")


def skip_sw_in_market_snapshot(target_date: str, workers: int = 6):
    """The dedicated SW workflow supplies the exact-date industry dataset."""
    columns = [
        "日期", "行业层级", "一级行业", "指数代码", "指数名称",
        "收盘价", "成交额_亿元", "日收益率", "20日年化波动率",
    ]
    snapshot = pd.DataFrame(columns=columns)
    failures = pd.DataFrame([
        {
            "指数代码": "ALL",
            "指数名称": "申万一级/二级行业",
            "错误": "由独立申万行业流水线生成，最终报告仅合并同一目标日数据",
        }
    ])
    return snapshot, failures


base.fetch_stock_universe = fetch_stock_universe_official
base.fetch_all_stock_history = fetch_current_close_snapshot
base.build_sw_second_mapping = build_sw_second_mapping_fast
base.fetch_sw_snapshot = skip_sw_in_market_snapshot

if __name__ == "__main__":
    base.main()
