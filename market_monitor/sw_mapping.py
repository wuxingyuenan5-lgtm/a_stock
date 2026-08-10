from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import akshare as ak
import pandas as pd

from .common import ensure_dir, normalize_code, retry

DEFAULT_MAPPING_PATH = Path("data/cache/sw_stock_mapping.csv")


def _mapping_age_days(path: Path) -> float:
    if not path.exists():
        return 99999
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - modified).total_seconds() / 86400


def build_mapping() -> pd.DataFrame:
    info = retry(ak.sw_index_second_info)
    required = {"行业代码", "行业名称", "上级行业"}
    if info.empty or not required.issubset(info.columns):
        raise ValueError(f"申万二级行业字段异常: {list(info.columns)}")

    records: list[dict[str, str]] = []
    for _, row in info.iterrows():
        industry_code = normalize_code(row["行业代码"])
        try:
            cons = retry(lambda code=industry_code: ak.index_component_sw(symbol=code), attempts=3)
        except Exception:
            continue
        if cons.empty or "证券代码" not in cons.columns:
            continue
        for stock_code in cons["证券代码"].dropna():
            records.append({
                "stock_code": normalize_code(stock_code),
                "sw_level1": str(row["上级行业"]).strip(),
                "sw_level2": str(row["行业名称"]).strip(),
                "sw_level2_code": industry_code,
            })
    if not records:
        raise RuntimeError("申万二级成分映射为空")
    return pd.DataFrame(records).drop_duplicates("stock_code", keep="first")


def load_or_refresh_mapping(path: Path = DEFAULT_MAPPING_PATH, stale_days: int = 7, force: bool = False) -> tuple[pd.DataFrame, bool]:
    if not force and path.exists() and _mapping_age_days(path) <= stale_days:
        return pd.read_csv(path, dtype={"stock_code": str, "sw_level2_code": str}), False
    mapping = build_mapping()
    ensure_dir(path.parent)
    mapping.to_csv(path, index=False, encoding="utf-8-sig")
    return mapping, True
