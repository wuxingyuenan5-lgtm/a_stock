from __future__ import annotations

from pathlib import Path

from .fast_market import fetch_a_share_spot_fast
from . import pipeline


def run(target_date: str, config_path: Path = Path("config/market_monitor.json"), root: Path = Path("."), refresh_mapping: bool = False):
    """Production entrypoint with the bounded fast all-A collector injected."""
    pipeline.fetch_a_share_spot = fetch_a_share_spot_fast
    return pipeline.run(
        target_date=target_date,
        config_path=config_path,
        root=root,
        refresh_mapping=refresh_mapping,
    )
