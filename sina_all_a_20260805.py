#!/usr/bin/env python3
from __future__ import annotations
import json, logging
from datetime import datetime
from pathlib import Path
import akshare as ak
import pandas as pd

OUT=Path('data/sina_all_a_20260805'); DAY='2026-08-05'

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s'); OUT.mkdir(parents=True,exist_ok=True)
    raw=ak.stock_zh_a_spot()
    required={'代码','名称','最新价','涨跌幅','成交额'}
    if raw.empty or not required.issubset(raw.columns):raise RuntimeError(f'fields {list(raw.columns)}')
    f=raw.copy().rename(columns={'代码':'行情代码','名称':'股票名称','最新价':'收盘价','涨跌幅':'涨跌幅_pct','成交额':'成交额_元','昨收':'昨收'})
    f['行情代码']=f['行情代码'].astype(str); f['股票代码']=f['行情代码'].str[-6:]; f['股票名称']=f['股票名称'].astype(str).str.strip()
    for c in ['收盘价','涨跌幅_pct','成交额_元','昨收']:f[c]=pd.to_numeric(f[c],errors='coerce')
    f=f[f['行情代码'].str.startswith(('sh','sz','bj'))&f['成交额_元'].fillna(0).gt(0)&f['收盘价'].fillna(0).gt(0)&~f['股票名称'].str.contains('ST',case=False,na=False)&~f['股票名称'].str.startswith('N',na=False)].drop_duplicates('行情代码').copy()
    if len(f)<5000:raise RuntimeError(f'effective rows too small {len(f)}')
    f.insert(0,'日期',DAY); f['涨跌幅']=f['涨跌幅_pct']/100; f['成交额（亿元）']=f['成交额_元']/1e8; f.sort_values(['成交额（亿元）','股票代码'],ascending=[False,True],inplace=True)
    hot=f[f['成交额（亿元）']>=100].copy(); hot.insert(1,'当日排名',range(1,len(hot)+1))
    amt=float(f['成交额（亿元）'].sum()); hotamt=float(hot['成交额（亿元）'].sum())
    summary=pd.DataFrame([{'日期':DAY,'上涨家数':int((f['涨跌幅']>0).sum()),'下跌家数':int((f['涨跌幅']<0).sum()),'平盘家数':int((f['涨跌幅']==0).sum()),'有效股票数':len(f),'全部A股成交额（亿元）':amt,'百亿成交股数':len(hot),'百亿成交额（亿元）':hotamt,'百亿成交集中度':hotamt/amt,'数据源':'AKShare新浪沪深京A股实时行情'}])
    for d,n in [(f,'all_a.csv'),(hot,'hot.csv'),(summary,'summary.csv')]:d.to_csv(OUT/n,index=False,encoding='utf-8-sig',float_format='%.10f')
    (OUT/'metadata.json').write_text(json.dumps({'built_at':datetime.utcnow().isoformat()+'Z','effective':len(f),'hot':len(hot)},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
