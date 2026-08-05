#!/usr/bin/env python3
"""Build complete 2026-08-05 A-share breadth using BaoStock universe + Tencent batch quotes."""
from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import re
import time

import baostock as bs
import pandas as pd
from curl_cffi import requests

OUT = Path("data/current_tencent_batch_20260805")
TARGET_ISO = "2026-08-05"
TARGET_COMPACT = "20260805"


def fetch_universe() -> pd.DataFrame:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(login.error_msg)
    try:
        rs = bs.query_all_stock(day=TARGET_ISO)
        rows = []
        while rs.error_code == "0" and rs.next():
            values = rs.get_row_data()
            if not values:
                continue
            code = values[0].lower()
            # query_all_stock may include indices; A-share securities use these prefixes.
            if code.startswith(("sh.", "sz.", "bj.")):
                market, numeric = code.split(".", 1)
                if len(numeric) == 6 and numeric.isdigit():
                    rows.append({"bs_code": code, "qt_code": f"{market}{numeric}"})
        if not rows:
            raise RuntimeError("BaoStock returned no stock codes")
        return pd.DataFrame(rows).drop_duplicates("qt_code")
    finally:
        bs.logout()


def fetch_batch(codes: list[str]) -> str:
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    last = None
    for attempt in range(5):
        try:
            response = requests.get(
                url,
                impersonate="chrome",
                headers={"Referer": "https://stockapp.finance.qq.com/"},
                timeout=30,
            )
            response.raise_for_status()
            return response.content.decode("gbk", errors="ignore")
        except Exception as exc:
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"batch request failed: {last}")


def parse_line(line: str) -> dict | None:
    match = re.search(r'v_([^=]+)="(.*)";', line.strip())
    if not match:
        return None
    quote_code = match.group(1)
    parts = match.group(2).split("~")
    if len(parts) < 38 or not parts[2]:
        return None
    name = parts[1].strip()
    code = parts[2].strip().zfill(6)
    try:
        price = float(parts[3] or 0)
        prev_close = float(parts[4] or 0)
        pct = float(parts[32] or 0) / 100.0
        amount_yi = float(parts[37] or 0) / 10000.0
    except ValueError:
        return None
    stamp = parts[30].strip() if len(parts) > 30 else ""
    date = stamp[:8] if len(stamp) >= 8 and stamp[:8].isdigit() else ""
    return {
        "行情代码": quote_code,
        "股票代码": code,
        "股票名称": name,
        "收盘价": price,
        "昨收": prev_close,
        "涨跌幅": pct,
        "成交额（亿元）": amount_yi,
        "行情日期": date,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    codes = universe["qt_code"].tolist()
    records: list[dict] = []
    failures: list[dict] = []
    batch_size = 40
    for start in range(0, len(codes), batch_size):
        batch = codes[start:start + batch_size]
        try:
            text = fetch_batch(batch)
            parsed_codes = set()
            for line in text.splitlines():
                row = parse_line(line)
                if row is not None:
                    records.append(row)
                    parsed_codes.add(row["行情代码"])
            for code in batch:
                if code not in parsed_codes:
                    failures.append({"行情代码": code, "错误": "未返回或无法解析"})
        except Exception as exc:
            failures.extend({"行情代码": code, "错误": str(exc)} for code in batch)
        done = min(start + batch_size, len(codes))
        if done % 400 == 0 or done == len(codes):
            logging.info("quotes %s/%s parsed=%s failures=%s", done, len(codes), len(records), len(failures))
        time.sleep(0.08)

    frame = pd.DataFrame(records).drop_duplicates("行情代码", keep="last")
    if frame.empty:
        raise RuntimeError("Tencent returned no usable quotes")
    # Keep valid target-day traded stocks. Exclude ST and listing-day N shares, matching workbook policy.
    frame = frame[
        frame["行情日期"].eq(TARGET_COMPACT)
        & frame["成交额（亿元）"].gt(0)
        & frame["收盘价"].gt(0)
        & ~frame["股票名称"].str.contains("ST", case=False, na=False)
        & ~frame["股票名称"].str.startswith("N", na=False)
    ].copy()
    if len(frame) < 4800:
        raise RuntimeError(f"effective A-share universe too small: {len(frame)}")
    frame.insert(0, "日期", TARGET_ISO)
    frame.sort_values(["成交额（亿元）", "股票代码"], ascending=[False, True], inplace=True)
    hot = frame[frame["成交额（亿元）"] >= 100].copy()
    hot.insert(1, "当日排名", range(1, len(hot) + 1))

    up = int((frame["涨跌幅"] > 0).sum())
    down = int((frame["涨跌幅"] < 0).sum())
    flat = int((frame["涨跌幅"] == 0).sum())
    total_amount = float(frame["成交额（亿元）"].sum())
    hot_amount = float(hot["成交额（亿元）"].sum())
    summary = pd.DataFrame([{
        "日期": TARGET_ISO,
        "上涨家数": up,
        "下跌家数": down,
        "平盘家数": flat,
        "有效股票数": len(frame),
        "全部A股成交额（亿元）": total_amount,
        "百亿成交股数": len(hot),
        "百亿成交额（亿元）": hot_amount,
        "百亿成交集中度": hot_amount / total_amount if total_amount else None,
        "接口未解析代码数": len(failures),
        "数据源": "BaoStock交易日股票池+腾讯批量收盘行情",
    }])

    frame.to_csv(OUT / "all_a_snapshot_20260805.csv", index=False, encoding="utf-8-sig", float_format="%.10f")
    hot.to_csv(OUT / "turnover_100bn_stocks_20260805.csv", index=False, encoding="utf-8-sig", float_format="%.10f")
    summary.to_csv(OUT / "market_summary_20260805.csv", index=False, encoding="utf-8-sig", float_format="%.10f")
    if failures:
        pd.DataFrame(failures).to_csv(OUT / "quote_failures_20260805.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "built_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "universe_codes": len(codes),
        "parsed_quotes": len(records),
        "effective_rows": len(frame),
        "hot_rows": len(hot),
        "failures": len(failures),
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("completed: %s", metadata)


if __name__ == "__main__":
    main()
