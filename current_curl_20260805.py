#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime
import json, logging, time
from pathlib import Path
import pandas as pd
import akshare as ak
from curl_cffi import requests

OUT=Path('data/current_curl_20260805'); DATE='20260805'
HOSTS=['https://82.push2.eastmoney.com/api/qt/clist/get','https://56.push2.eastmoney.com/api/qt/clist/get','https://push2.eastmoney.com/api/qt/clist/get']
BASE={'po':1,'np':1,'ut':'bd1d9ddb04089700cf9c27f6f7426281','fltt':2,'invt':2,'fid':'f3','fs':'m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048','fields':'f2,f3,f5,f6,f8,f12,f13,f14,f18,f20,f21,f23,f100,f124'}

def page(p:int,pz:int=100):
    params={**BASE,'pn':p,'pz':pz}; last=None
    for n in range(6):
        for h in HOSTS:
            try:
                r=requests.get(h,params=params,impersonate='chrome',headers={'Referer':'https://quote.eastmoney.com/'},timeout=25)
                r.raise_for_status(); j=r.json()
                if j.get('data') is not None:return j
            except Exception as e:last=e
        time.sleep(1+n)
    raise RuntimeError(f'page {p}: {last}')

def indexes():
    r=requests.get('https://qt.gtimg.cn/q=sh000016,sh000985',impersonate='chrome',timeout=20); r.raise_for_status(); rows=[]
    for line in r.content.decode('gbk',errors='ignore').splitlines():
        if '="' not in line:continue
        x=line.split('="',1)[1].rsplit('"',1)[0].split('~')
        if len(x)<38:continue
        rows.append({'日期':'2026-08-05','指标':'上证50' if x[2]=='000016' else '中证全指','数据代码':x[2],'收盘点位':float(x[3]),'涨跌幅':float(x[32])/100,'成交额（亿元）':float(x[37])/10000,'数据源':'腾讯行情'})
    return pd.DataFrame(rows)

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s'); OUT.mkdir(parents=True,exist_ok=True)
    first=page(1); total=int((first.get('data') or {}).get('total') or 0); rows=list((first.get('data') or {}).get('diff') or []); pages=(total+99)//100
    logging.info('total=%s pages=%s',total,pages)
    for p in range(2,pages+1):
        rows.extend(((page(p).get('data') or {}).get('diff') or []));
        if p%10==0 or p==pages:logging.info('%s/%s rows=%s',p,pages,len(rows))
        time.sleep(.05)
    f=pd.DataFrame(rows).rename(columns={'f12':'股票代码','f14':'股票名称','f2':'收盘价','f3':'涨跌幅_pct','f6':'成交额_元','f5':'成交量','f8':'换手率_pct','f18':'昨收','f20':'总市值_元','f21':'流通市值_元','f23':'市净率','f100':'东方财富行业','f124':'行情时间戳','f13':'市场标识'})
    f['股票代码']=f['股票代码'].astype(str).str.zfill(6); f['股票名称']=f['股票名称'].astype(str).str.strip()
    for c in ['收盘价','涨跌幅_pct','成交额_元','成交量','换手率_pct','昨收','总市值_元','流通市值_元']:f[c]=pd.to_numeric(f[c],errors='coerce')
    f=f[f['成交额_元'].fillna(0).gt(0)&~f['股票名称'].str.contains('ST',case=False,na=False)&~f['股票名称'].str.startswith('N',na=False)].drop_duplicates('股票代码').copy()
    if len(f)<4500:raise RuntimeError(f'universe too small {len(f)}')
    f['日期']='2026-08-05'; f['涨跌幅']=f['涨跌幅_pct']/100; f['成交额（亿元）']=f['成交额_元']/1e8; f.sort_values(['成交额_元','股票代码'],ascending=[False,True],inplace=True)
    hot=f[f['成交额_元']>=1e10].copy(); hot.insert(0,'当日排名',range(1,len(hot)+1))
    try:lu=len(ak.stock_zt_pool_em(date=DATE))
    except Exception:lu=None
    try:ld=len(ak.stock_zt_pool_dtgc_em(date=DATE))
    except Exception:ld=None
    amt=float(f['成交额_元'].sum()/1e8); summary=pd.DataFrame([{'日期':'2026-08-05','上涨家数':int((f['涨跌幅']>0).sum()),'下跌家数':int((f['涨跌幅']<0).sum()),'平盘家数':int((f['涨跌幅']==0).sum()),'涨停家数':lu,'跌停家数':ld,'有效股票数':len(f),'全部A股成交额（亿元）':amt,'百亿成交股数':len(hot),'百亿成交额（亿元）':float(hot['成交额（亿元）'].sum()),'百亿成交集中度':float(hot['成交额（亿元）'].sum())/amt,'数据源':'curl_cffi东方财富全A分页+腾讯指数'}])
    for d,n in [(f,'all_a_snapshot_20260805.csv'),(hot,'turnover_100bn_stocks_20260805.csv'),(summary,'market_summary_20260805.csv'),(indexes(),'index_snapshot_20260805.csv')]:d.to_csv(OUT/n,index=False,encoding='utf-8-sig',float_format='%.10f')
    (OUT/'metadata.json').write_text(json.dumps({'built_at_utc':datetime.utcnow().isoformat()+'Z','rows':len(f),'hot':len(hot)},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
