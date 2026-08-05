#!/usr/bin/env python3
from __future__ import annotations
import json, logging, time
from datetime import datetime
from pathlib import Path
import pandas as pd
from curl_cffi import requests

OUT=Path('data/bj_snapshot_20260805'); DAY='2026-08-05'
HOSTS=['https://82.push2.eastmoney.com/api/qt/clist/get','https://56.push2.eastmoney.com/api/qt/clist/get','https://push2.eastmoney.com/api/qt/clist/get']

def page(p):
    params={'pn':p,'pz':100,'po':1,'np':1,'ut':'bd1d9ddb04089700cf9c27f6f7426281','fltt':2,'invt':2,'fid':'f3','fs':'m:0+t:81+s:2048','fields':'f2,f3,f6,f12,f14,f18,f124'}; last=None
    for a in range(4):
        for h in HOSTS:
            try:
                r=requests.get(h,params=params,impersonate='chrome',headers={'Referer':'https://quote.eastmoney.com/'},timeout=15); r.raise_for_status(); j=r.json()
                if j.get('data') is not None:return j
            except Exception as e:last=e
        time.sleep(.5*(a+1))
    raise RuntimeError(str(last))

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s'); OUT.mkdir(parents=True,exist_ok=True)
    first=page(1); data=first.get('data') or {}; total=int(data.get('total') or 0); rec=list(data.get('diff') or []); pages=(total+99)//100
    for p in range(2,pages+1):rec.extend(((page(p).get('data') or {}).get('diff') or []))
    f=pd.DataFrame(rec).rename(columns={'f12':'股票代码','f14':'股票名称','f2':'收盘价','f3':'涨跌幅_pct','f6':'成交额_元','f18':'昨收','f124':'行情时间戳'})
    f['股票代码']=f['股票代码'].astype(str).str.zfill(6); f['股票名称']=f['股票名称'].astype(str).str.strip()
    for c in ['收盘价','涨跌幅_pct','成交额_元','昨收']:f[c]=pd.to_numeric(f[c],errors='coerce')
    f=f[f['成交额_元'].fillna(0).gt(0)&~f['股票名称'].str.contains('ST',case=False,na=False)&~f['股票名称'].str.startswith('N',na=False)].drop_duplicates('股票代码').copy()
    f.insert(0,'日期',DAY); f['涨跌幅']=f['涨跌幅_pct']/100; f['成交额（亿元）']=f['成交额_元']/1e8; f['行情代码']='bj'+f['股票代码']; f.sort_values('成交额（亿元）',ascending=False,inplace=True)
    hot=f[f['成交额（亿元）']>=100].copy(); amt=float(f['成交额（亿元）'].sum()); hotamt=float(hot['成交额（亿元）'].sum())
    summary=pd.DataFrame([{'日期':DAY,'上涨家数':int((f['涨跌幅']>0).sum()),'下跌家数':int((f['涨跌幅']<0).sum()),'平盘家数':int((f['涨跌幅']==0).sum()),'有效股票数':len(f),'成交额（亿元）':amt,'百亿成交股数':len(hot),'百亿成交额（亿元）':hotamt}])
    for d,n in [(f,'bj_all.csv'),(hot,'bj_hot.csv'),(summary,'bj_summary.csv')]:d.to_csv(OUT/n,index=False,encoding='utf-8-sig',float_format='%.10f')
    (OUT/'metadata.json').write_text(json.dumps({'built_at':datetime.utcnow().isoformat()+'Z','total':total,'effective':len(f)},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
