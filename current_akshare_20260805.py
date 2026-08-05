#!/usr/bin/env python3
"""Build complete 2026-08-05 A-share snapshot using AKShare's full spot endpoint."""
from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path

import akshare as ak
import pandas as pd
import requests

OUT_DIR = Path("data/current_akshare_20260805")
TARGET_DATE = "20260805"


def fetch_indexes() -> pd.DataFrame:
    response = requests.get("https://qt.gtimg.cn/q=sh000016,sh000985", headers={"User-Agent":"Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    rows=[]
    for line in response.content.decode("gbk",errors="ignore").splitlines():
        if '="' not in line: continue
        p=line.split('="',1)[1].rsplit('"',1)[0].split("~")
        if len(p)<38: continue
        code=p[2]
        rows.append({"日期":"2026-08-05","指标":"上证50" if code=="000016" else "中证全指","数据代码":code,"收盘点位":float(p[3]),"涨跌幅":float(p[32])/100.0,"成交额（亿元）":float(p[37])/10000.0,"数据源":"腾讯行情"})
    return pd.DataFrame(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw=ak.stock_zh_a_spot_em()
    required={"代码","名称","最新价","涨跌幅","成交额"}
    if raw.empty or not required.issubset(raw.columns):
        raise RuntimeError(f"full spot fields invalid: {list(raw.columns)}")
    keep=[c for c in ["代码","名称","最新价","涨跌幅","成交量","成交额","换手率","昨收","总市值","流通市值","市净率"] if c in raw.columns]
    frame=raw[keep].copy().rename(columns={"代码":"股票代码","名称":"股票名称","最新价":"收盘价","涨跌幅":"涨跌幅_pct","成交额":"成交额_元","成交量":"成交量","换手率":"换手率_pct","昨收":"昨收","总市值":"总市值_元","流通市值":"流通市值_元","市净率":"市净率"})
    frame["股票代码"]=frame["股票代码"].astype(str).str.zfill(6)
    frame["股票名称"]=frame["股票名称"].astype(str).str.strip()
    for c in ["收盘价","涨跌幅_pct","成交额_元","成交量","换手率_pct","昨收","总市值_元","流通市值_元"]:
        if c in frame.columns: frame[c]=pd.to_numeric(frame[c],errors="coerce")
    frame=frame[frame["成交额_元"].fillna(0).gt(0)&~frame["股票名称"].str.contains("ST",case=False,na=False)&~frame["股票名称"].str.startswith("N",na=False)].copy()
    frame=frame.drop_duplicates("股票代码")
    if len(frame)<4500: raise RuntimeError(f"effective universe too small: {len(frame)}")
    frame["日期"]="2026-08-05"
    frame["涨跌幅"]=frame["涨跌幅_pct"]/100.0
    frame["成交额（亿元）"]=frame["成交额_元"]/1e8
    frame.sort_values(["成交额_元","股票代码"],ascending=[False,True],inplace=True)
    hot=frame[frame["成交额_元"]>=10_000_000_000].copy()
    hot.insert(0,"当日排名",range(1,len(hot)+1))
    try: up_limit=len(ak.stock_zt_pool_em(date=TARGET_DATE))
    except Exception: up_limit=None; logging.exception("limit up failed")
    try: down_limit=len(ak.stock_zt_pool_dtgc_em(date=TARGET_DATE))
    except Exception: down_limit=None; logging.exception("limit down failed")
    amount=float(frame["成交额_元"].sum()/1e8)
    summary=pd.DataFrame([{"日期":"2026-08-05","上涨家数":int((frame["涨跌幅"]>0).sum()),"下跌家数":int((frame["涨跌幅"]<0).sum()),"平盘家数":int((frame["涨跌幅"]==0).sum()),"涨停家数":up_limit,"跌停家数":down_limit,"有效股票数":len(frame),"全部A股成交额（亿元）":amount,"百亿成交股数":len(hot),"百亿成交额（亿元）":float(hot["成交额（亿元）"].sum()),"百亿成交集中度":float(hot["成交额（亿元）"].sum())/amount,"数据源":"AKShare全A现货+腾讯指数+涨跌停池"}])
    indexes=fetch_indexes()
    for df,name in [(frame,"all_a_snapshot_20260805.csv"),(hot,"turnover_100bn_stocks_20260805.csv"),(summary,"market_summary_20260805.csv"),(indexes,"index_snapshot_20260805.csv")]:
        df.to_csv(OUT_DIR/name,index=False,encoding="utf-8-sig",float_format="%.10f")
    meta={"built_at_utc":datetime.utcnow().isoformat(timespec="seconds")+"Z","effective_rows":len(frame),"hot_rows":len(hot)}
    (OUT_DIR/"metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    logging.info("AKShare current build completed: %s",meta)

if __name__=="__main__": main()
