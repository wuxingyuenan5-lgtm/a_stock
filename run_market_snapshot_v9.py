#!/usr/bin/env python3
"""Fast exact-date runner with parallel Shenwan constituent mapping.

The separate Shenwan workflow already produces the exact-date index snapshot,
so this runner skips the duplicate 155-index market-task fetch and focuses on
market breadth, authoritative indices, full >100bn list and SW-II mapping.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

import pandas as pd

import build_market_snapshot as base
import run_market_snapshot_v7 as v7


def build_sw_second_mapping_parallel(workers: int = 12) -> pd.DataFrame:
    info = base.retry(base.ak.sw_index_second_info)
    required = {"行业代码", "行业名称", "上级行业"}
    if info.empty or not required.issubset(info.columns):
        raise ValueError(f"申万二级行业信息异常: {list(info.columns)}")

    rows = [row.copy() for _, row in info.iterrows()]
    records: list[dict[str, str]] = []

    def fetch(row: pd.Series) -> list[dict[str, str]]:
        industry_code = base.normalize_code(row["行业代码"])
        cons = base.retry(
            lambda: base.ak.index_component_sw(symbol=industry_code),
            attempts=4,
            delay=0.8,
        )
        if cons.empty or "证券代码" not in cons.columns:
            return []
        return [
            {
                "股票代码": base.normalize_code(code),
                "申万一级行业": str(row["上级行业"]).strip(),
                "申万二级行业": str(row["行业名称"]).strip(),
            }
            for code in cons["证券代码"].dropna().astype(str)
        ]

    failures = 0
    with ThreadPoolExecutor(max_workers=min(workers, len(rows))) as executor:
        future_map = {executor.submit(fetch, row): row for row in rows}
        for future in as_completed(future_map):
            row = future_map[future]
            try:
                records.extend(future.result())
            except Exception as exc:
                failures += 1
                logging.warning(
                    "申万二级行业成分失败 %s %s: %s",
                    row.get("行业代码"), row.get("行业名称"), exc,
                )
    if not records:
        raise RuntimeError("申万二级行业成分映射全部失败")
    logging.info("申万二级映射完成: records=%s failures=%s", len(records), failures)
    return pd.DataFrame(records).drop_duplicates("股票代码", keep="first")


def skip_duplicate_sw_snapshot(target_date: str, workers: int = 6):
    del target_date, workers
    return pd.DataFrame(), pd.DataFrame()


base.build_sw_second_mapping = build_sw_second_mapping_parallel
base.fetch_sw_snapshot = skip_duplicate_sw_snapshot

if __name__ == "__main__":
    v7.v6.main()
