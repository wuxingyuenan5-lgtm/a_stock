from __future__ import annotations

from pathlib import Path

import pandas as pd

from .collectors import fetch_sw_analysis
from .common import ensure_dir

CACHE_PATH = Path("data/cache/sw_analysis_daily_second.csv")
HISTORY_PATH = Path("data/history/sw_analysis_daily_second.csv")


def load_sw_cache(target_date: str, path: Path = CACHE_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, encoding="utf-8-sig")
    date_col = next((c for c in ("发布日期", "日期", "date") if c in frame.columns), None)
    if date_col is not None:
        dates = pd.to_datetime(frame[date_col], errors="coerce")
        target = pd.Timestamp(target_date)
        frame = frame[(dates.isna()) | (dates <= target)].copy()
    return frame


def refresh_sw_cache(target_date: str, cache_path: Path = CACHE_PATH, history_path: Path = HISTORY_PATH) -> pd.DataFrame:
    frame = fetch_sw_analysis(target_date)
    if frame.empty:
        raise RuntimeError("申万日度分析接口未返回有效数据；保留旧缓存")
    ensure_dir(cache_path.parent)
    ensure_dir(history_path.parent)
    frame.to_csv(cache_path, index=False, encoding="utf-8-sig")

    if history_path.exists():
        old = pd.read_csv(history_path, encoding="utf-8-sig")
        combined = pd.concat([old, frame], ignore_index=True, sort=False).drop_duplicates(keep="last")
    else:
        combined = frame.copy()
    date_col = next((c for c in ("发布日期", "日期", "date") if c in combined.columns), None)
    if date_col is not None:
        combined["__date"] = pd.to_datetime(combined[date_col], errors="coerce")
        combined = combined.sort_values("__date").drop(columns="__date")
    combined.to_csv(history_path, index=False, encoding="utf-8-sig")
    return frame
