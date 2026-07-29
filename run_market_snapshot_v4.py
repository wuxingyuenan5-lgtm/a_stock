#!/usr/bin/env python3
"""Run v3 report with corrected Tencent market-cap field semantics.

Tencent quote protocol:
- field 44: float market capitalization (亿元)
- field 45: total market capitalization (亿元)
"""
from __future__ import annotations

import build_market_snapshot as base
import run_market_snapshot_v2 as source
import run_market_snapshot_v3 as report


def _parse_tencent_quotes_corrected(text: str, target_date: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.split(";"):
        if "=" not in line or '"' not in line:
            continue
        full_code = line.split("=")[0].split("_")[-1]
        values = line.split('"')[1].split("~")
        if len(values) < 50:
            continue
        quote_time = values[30] if len(values) > 30 else ""
        if quote_time and not quote_time.startswith(target_date):
            continue
        pct = source._num(values, 32)
        amount_wan = source._num(values, 37)
        float_mcap_yi = source._num(values, 44)
        total_mcap_yi = source._num(values, 45)
        rows.append(
            {
                "股票代码": base.normalize_code(full_code[2:]),
                "行情名称": values[1],
                "收盘价": source._num(values, 3),
                "涨跌幅": pct / 100 if pct is not None else None,
                "成交额": amount_wan * 10000 if amount_wan is not None else None,
                "行情总市值": total_mcap_yi * 1e8 if total_mcap_yi is not None else None,
                "行情流通市值": float_mcap_yi * 1e8 if float_mcap_yi is not None else None,
                "涨停价": source._num(values, 47),
                "跌停价": source._num(values, 48),
                "行情时间": quote_time,
            }
        )
    return rows


source._parse_tencent_quotes = _parse_tencent_quotes_corrected


if __name__ == "__main__":
    report.main()
