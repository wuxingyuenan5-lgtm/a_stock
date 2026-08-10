from __future__ import annotations

from pathlib import Path

from . import pipeline
from .fast_market import fetch_a_share_spot_fast
from .sw_cache import load_sw_cache


def run(target_date: str, config_path: Path = Path("config/market_monitor.json"), root: Path = Path("."), refresh_mapping: bool = False):
    """Production entrypoint: bounded market collector + cached Shenwan module."""
    pipeline.fetch_a_share_spot = fetch_a_share_spot_fast
    pipeline.fetch_sw_analysis = load_sw_cache
    return pipeline.run(
        target_date=target_date,
        config_path=config_path,
        root=root,
        refresh_mapping=refresh_mapping,
    )
