#!/usr/bin/env python3
"""Build a paginated, complete A-share close snapshot for 2026-08-05."""
from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import time

import pandas as pd
import requests

OUT_DIR = Path("data/current_complete_20260805")
TARGET_DATE = "20260805"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36"


def request_page(page: int, page_size: int = 100) -> dict:
    urls = [
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        "https://56.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
    ]
    params = {
        "pn": page,
        "pz": page_size,
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f2,f3,f5,f6,f8,f12,f13,f14,f18,f20,f21,f23,f100,f124",
    }
    last = None
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    for attempt in range(4):
        for url in urls:
            try:
                response = requests.get(url, params=params, headers=headers, timeout=20)
                response.raise_for_status()
                payload = response.json()
                if payload.get("data") is not None:
                    return payload
            except Exception as exc:
                last = exc
        time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"page {page} failed: {last}")


def fetch_all_pages() -> pd.DataFrame:
    first = request_page(1)
    data = first.get("data") or {}
    total = int(data.get("total") or 0)
    records = list(data.get("diff") or [])
    page_size = 100
    pages = (total + page_size - 1) // page_size
    logging.info("Eastmoney total=%s pages=%s", total, pages)
    for page in range(2, pages + 1):
        payload = request_page(page, page_size)
        records.extend(((payload.get("data") or {}).get("diff") or []))
        if page % 10 == 0 or page == pages:
            logging.info("pagination %s/%s rows=%s", page, pages, len(records))
        time.sleep(0.05)
    frame = pd.DataFrame(records).rename(columns={
        "f12":"股票代码","f14":"股票名称","f2":"收盘价","f3":"涨跌幅_pct",
        "f6":"成交额_元","f5":"成交量","f8":"换手率_pct","f18":"昨收",
        "f20":"总市值_元","f21":"流通市值_元","f23":"市净率",
        "f100":"东方财富行业","f124":"行情时间戳","f13":"市场标识",
    })
    frame["股票代码"] = frame["股票代码"].astype(str).str.zfill(6)
    frame["股票名称"] = frame["股票名称"].astype(str).str.strip()
    for col in ["收盘价","涨跌幅_pct","成交额_元","成交量","换手率_pct","昨收","总市值_元","流通市值_元"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["日期"] = pd.to_datetime(pd.to_numeric(frame["行情时间戳"], errors="coerce"), unit="s", errors="coerce").dt.strftime("%Y-%m-%d")
    expected = datetime.strptime(TARGET_DATE, "%Y%m%d").strftime("%Y-%m-%d")
    wrong_dates = frame[frame["日期"].notna() & frame["日期"].ne(expected)]
    if len(wrong_dates) > 0:
        logging.warning("rows with non-target timestamp: %s", len(wrong_dates))
    frame = frame[
        frame["成交额_元"].fillna(0).gt(0)
        & ~frame["股票名称"].str.contains("ST", case=False, na=False)
        & ~frame["股票名称"].str.startswith("N", na=False)
    ].copy()
    frame = frame.drop_duplicates("股票代码", keep="first")
    frame["涨跌幅"] = frame["涨跌幅_pct"] / 100.0
    frame["成交额（亿元）"] = frame["成交额_元"] / 1e8
    frame.sort_values(["成交额_元","股票代码"], ascending=[False,True], inplace=True)
    return frame


def fetch_limit_counts() -> tuple[int|None,int|None]:
    import akshare as ak
    up = down = None
    try:
        up = len(ak.stock_zt_pool_em(date=TARGET_DATE))
    except Exception:
        logging.exception("limit-up pool failed")
    try:
        down = len(ak.stock_zt_pool_dtgc_em(date=TARGET_DATE))
    except Exception:
        logging.exception("limit-down pool failed")
    return up, down


def fetch_tencent_indexes() -> pd.DataFrame:
    response = requests.get("https://qt.gtimg.cn/q=sh000016,sh000985", headers={"User-Agent":UA}, timeout=20)
    response.raise_for_status()
    text = response.content.decode("gbk", errors="ignore")
    rows = []
    for line in text.splitlines():
        if '="' not in line:
            continue
        p = line.split('="',1)[1].rsplit('"',1)[0].split("~")
        if len(p) < 38:
            continue
        code = p[2]
        rows.append({
            "日期":"2026-08-05",
            "指标":"上证50" if code=="000016" else "中证全指",
            "数据代码":code,
            "收盘点位":float(p[3]),
            "涨跌幅":float(p[32])/100.0,
            "成交额（亿元）":float(p[37])/10000.0,
            "数据源":"腾讯行情",
        })
    return pd.DataFrame(rows)


def write(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT_DIR/name, index=False, encoding="utf-8-sig", float_format="%.10f")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = fetch_all_pages()
    if len(snapshot) < 4500:
        raise RuntimeError(f"effective A-share universe too small: {len(snapshot)}")
    hot = snapshot[snapshot["成交额_元"] >= 10_000_000_000].copy()
    hot.insert(0,"当日排名",range(1,len(hot)+1))
    limit_up, limit_down = fetch_limit_counts()
    indexes = fetch_tencent_indexes()
    amount = float(snapshot["成交额_元"].sum()/1e8)
    summary = pd.DataFrame([{
        "日期":"2026-08-05",
        "上涨家数":int((snapshot["涨跌幅"]>0).sum()),
        "下跌家数":int((snapshot["涨跌幅"]<0).sum()),
        "平盘家数":int((snapshot["涨跌幅"]==0).sum()),
        "涨停家数":limit_up,"跌停家数":limit_down,
        "有效股票数":len(snapshot),
        "全部A股成交额（亿元）":amount,
        "百亿成交股数":len(hot),
        "百亿成交额（亿元）":float(hot["成交额（亿元）"].sum()),
        "百亿成交集中度":float(hot["成交额（亿元）"].sum())/amount,
        "数据源":"东方财富逐页全A收盘快照+腾讯指数+涨跌停池",
    }])
    write(snapshot,"all_a_snapshot_20260805.csv")
    write(hot,"turnover_100bn_stocks_20260805.csv")
    write(summary,"market_summary_20260805.csv")
    write(indexes,"index_snapshot_20260805.csv")
    metadata={"built_at_utc":datetime.utcnow().isoformat(timespec="seconds")+"Z","raw_total":len(snapshot),"hot_rows":len(hot)}
    (OUT_DIR/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    logging.info("complete snapshot built: %s",metadata)

if __name__=="__main__":
    main()
