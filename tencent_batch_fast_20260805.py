#!/usr/bin/env python3
from __future__ import annotations
import json, logging, re, time
from datetime import datetime
from pathlib import Path
import baostock as bs
import pandas as pd
import requests

OUT=Path('data/tencent_batch_fast_20260805'); DAY='2026-08-05'; COMPACT='20260805'

def universe():
    lg=bs.login()
    if lg.error_code!='0': raise RuntimeError(lg.error_msg)
    try:
        rs=bs.query_all_stock(day=DAY); rows=[]
        while rs.error_code=='0' and rs.next():
            x=rs.get_row_data()[0].lower()
            if x.startswith(('sh.','sz.','bj.')):
                m,n=x.split('.',1)
                if len(n)==6 and n.isdigit(): rows.append(m+n)
        return list(dict.fromkeys(rows))
    finally: bs.logout()

def get_batch(codes):
    url='https://qt.gtimg.cn/q='+','.join(codes); last=None
    for attempt in range(2):
        try:
            r=requests.get(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://stockapp.finance.qq.com/'},timeout=8)
            r.raise_for_status(); return r.content.decode('gbk',errors='ignore')
        except Exception as e: last=e; time.sleep(.3)
    raise RuntimeError(str(last))

def parse(line):
    m=re.search(r'v_([^=]+)="(.*)";',line.strip())
    if not m:return None
    q=m.group(1); p=m.group(2).split('~')
    if len(p)<38 or not p[2]:return None
    try:
        return {'行情代码':q,'股票代码':p[2].zfill(6),'股票名称':p[1].strip(),'收盘价':float(p[3] or 0),'昨收':float(p[4] or 0),'涨跌幅':float(p[32] or 0)/100,'成交额（亿元）':float(p[37] or 0)/10000,'行情日期':(p[30] or '')[:8]}
    except Exception:return None

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s'); OUT.mkdir(parents=True,exist_ok=True)
    codes=universe(); rec=[]; fail=[]; size=80
    for s in range(0,len(codes),size):
        b=codes[s:s+size]
        try:
            text=get_batch(b); got=set()
            for line in text.splitlines():
                r=parse(line)
                if r: rec.append(r); got.add(r['行情代码'])
            fail += [{'行情代码':x,'错误':'未返回'} for x in b if x not in got]
        except Exception as e: fail += [{'行情代码':x,'错误':str(e)} for x in b]
        if min(s+size,len(codes))%800==0 or s+size>=len(codes): logging.info('%s/%s parsed=%s fail=%s',min(s+size,len(codes)),len(codes),len(rec),len(fail))
    f=pd.DataFrame(rec).drop_duplicates('行情代码',keep='last')
    f=f[f['行情日期'].eq(COMPACT)&f['成交额（亿元）'].gt(0)&f['收盘价'].gt(0)&~f['股票名称'].str.contains('ST',case=False,na=False)&~f['股票名称'].str.startswith('N',na=False)].copy()
    if len(f)<4700: raise RuntimeError(f'effective rows too small {len(f)}, failures {len(fail)}')
    f.insert(0,'日期',DAY); f.sort_values(['成交额（亿元）','股票代码'],ascending=[False,True],inplace=True)
    hot=f[f['成交额（亿元）']>=100].copy(); hot.insert(1,'当日排名',range(1,len(hot)+1))
    amt=float(f['成交额（亿元）'].sum()); hotamt=float(hot['成交额（亿元）'].sum())
    summary=pd.DataFrame([{'日期':DAY,'上涨家数':int((f['涨跌幅']>0).sum()),'下跌家数':int((f['涨跌幅']<0).sum()),'平盘家数':int((f['涨跌幅']==0).sum()),'有效股票数':len(f),'全部A股成交额（亿元）':amt,'百亿成交股数':len(hot),'百亿成交额（亿元）':hotamt,'百亿成交集中度':hotamt/amt,'未解析代码数':len(fail),'数据源':'BaoStock股票池+腾讯批量行情'}])
    for d,n in [(f,'all_a_snapshot.csv'),(hot,'hot.csv'),(summary,'summary.csv')]: d.to_csv(OUT/n,index=False,encoding='utf-8-sig',float_format='%.10f')
    if fail: pd.DataFrame(fail).to_csv(OUT/'failures.csv',index=False,encoding='utf-8-sig')
    (OUT/'metadata.json').write_text(json.dumps({'built_at':datetime.utcnow().isoformat()+'Z','universe':len(codes),'effective':len(f),'hot':len(hot),'fail':len(fail)},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
