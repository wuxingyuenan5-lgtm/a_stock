from __future__ import annotations

from pathlib import Path
import time

from . import pipeline
from .collectors import fetch_indices as fetch_indices_primary
from .fast_market import fetch_a_share_spot_fast
from .sw_cache import load_sw_cache


def fetch_indices_with_second_pass(target_date: str, definitions: list[dict[str, str]]):
    """Retry only failed index definitions once, using the same Eastmoney source."""
    first = fetch_indices_primary(target_date, definitions)
    failed_names = {
        str(item.get("name"))
        for item in first
        if item.get("close") is None or item.get("return") is None or item.get("amount_100m") is None
    }
    if not failed_names:
        return first

    retry_defs = [item for item in definitions if item["name"] in failed_names]
    time.sleep(1.5)
    second = fetch_indices_primary(target_date, retry_defs)
    retry_map = {str(item.get("name")): item for item in second}

    merged = []
    for item in first:
        name = str(item.get("name"))
        retry = retry_map.get(name)
        if (
            retry is not None
            and retry.get("close") is not None
            and retry.get("return") is not None
            and retry.get("amount_100m") is not None
        ):
            retry = dict(retry)
            retry["status"] = "ok_after_same_source_second_pass"
            merged.append(retry)
        else:
            old = dict(item)
            if name in failed_names:
                old["status"] = f"{old.get('status')}; same-source second pass also unavailable"
            merged.append(old)
    return merged


def run(
    target_date: str,
    config_path: Path = Path("config/market_monitor.json"),
    root: Path = Path("."),
    refresh_mapping: bool = False,
):
    """Production entrypoint: bounded market collector + cached Shenwan module."""
    pipeline.fetch_a_share_spot = fetch_a_share_spot_fast
    pipeline.fetch_sw_analysis = load_sw_cache
    pipeline.fetch_indices = fetch_indices_with_second_pass
    return pipeline.run(
        target_date=target_date,
        config_path=config_path,
        root=root,
        refresh_mapping=refresh_mapping,
    )
