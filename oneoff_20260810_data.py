#!/usr/bin/env python3
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json, time
import pandas as pd
import requests
import akshare as ak

OUT=Path('data/oneoff_20260810'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'
TARGET='2026-08-10'; HIST='2026-08-07'

def num(x): return pd.to_numeric(x,errors='coerce')
def pick(df,*names):
    for n in names:
        if n in df.columns:return n
    raise KeyError((names,list(df.columns)))

def fetch_spot():
    last=None
    for i in range(5):
        try:
            df=ak.stock_zh_a_spot()
            if df is not None and not df.empty:return df
        except Exception as e:last=e
        time.sleep(2+i*2)
    raise RuntimeError(last)

def norm_spot(raw):
    c=pick(raw,'代码','symbol'); n=pick(raw,'名称','name'); cl=pick(raw,'最新价','最新','trade'); pc=pick(raw,'昨收','昨收盘','settlement'); am=pick(raw,'成交额','amount'); vo=pick(raw,'成交量','volume'); p=pick(raw,'涨跌幅','changepercent')
    o=pd.DataFrame({'股票代码':raw[c].astype(str).str.extract(r'(\d{6})',expand=False),'股票名称':raw[n].astype(str),'收盘价':num(raw[cl]),'昨收价':num(raw[pc]),'成交额_元':num(raw[am]),'成交量':num(raw[vo]),'涨跌幅_pct':num(raw[p])})
    o['涨跌幅']=o['涨跌幅_pct']/100
    o=o.dropna(subset=['股票代码','收盘价','昨收价','成交额_元','成交量','涨跌幅'])
    o=o[(o['收盘价']>0)&(o['昨收价']>0)&(o['成交额_元']>0)&(o['成交量']>0)]
    o=o[~o['股票名称'].str.contains('ST',case=False,na=False)]
    o=o[~o['股票名称'].str.startswith(('N','C'),na=False)]
    o=o.drop_duplicates('股票代码',keep='last')
    o['成交额（亿元）']=o['成交额_元']/1e8
    return o

def limit_rate(code):
    if code.startswith(('4','8','9')): return Decimal('0.30')
    if code.startswith(('300','301','688','689')): return Decimal('0.20')
    return Decimal('0.10')

def exact_limits(df):
    up=dn=0
    for r in df.itertuples(index=False):
        pre=Decimal(str(r.昨收价)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        close=Decimal(str(r.收盘价)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        rr=limit_rate(r.股票代码)
        up_px=(pre*(1+rr)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        dn_px=(pre*(1-rr)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        up+=int(close==up_px); dn+=int(close==dn_px)
    return up,dn

def summarize(df,date,source):
    up=int((df['涨跌幅']>0).sum()); dn=int((df['涨跌幅']<0).sum()); fl=int((df['涨跌幅']==0).sum())
    if '昨收价' in df.columns: lu,ld=exact_limits(df)
    else:
        def hit(row,sgn):
            rate=float(limit_rate(row['股票代码']))*100
            pct=float(row['涨跌幅']*100)
            return pct>=rate-0.25 if sgn>0 else pct<=-rate+0.25
        lu=sum(hit(r,1) for _,r in df.iterrows()); ld=sum(hit(r,-1) for _,r in df.iterrows())
    ta=float(df['成交额（亿元）'].sum())
    hot=df[df['成交额（亿元）']>=100].sort_values('成交额（亿元）',ascending=False).copy()
    hot.insert(0,'当日排名',range(1,len(hot)+1)); hot.insert(0,'日期',date)
    ha=float(hot['成交额（亿元）'].sum())
    sm=pd.DataFrame([{'日期':date,'上涨家数':up,'下跌家数':dn,'平盘家数':fl,'涨停家数':lu,'跌停家数':ld,'有效股票数':len(df),'全部A股成交额（亿元）':ta,'百亿成交股数':len(hot),'百亿成交额（亿元）':ha,'百亿成交集中度':ha/ta if ta else None,'数据源':source}])
    return sm,hot

def secid(code):
    return ('1.' if code.startswith(('5','6','9')) else '0.')+code

def kline_one(code,date_compact):
    url='https://push2his.eastmoney.com/api/qt/stock/kline/get'
    params={'secid':secid(code),'fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61','klt':'101','fqt':'0','beg':date_compact,'end':date_compact,'lmt':'2','ut':'fa5fd1943c7b386f172d6893dbfba10b'}
    last=None
    for i in range(3):
        try:
            r=requests.get(url,params=params,headers={'User-Agent':UA,'Referer':'https://quote.eastmoney.com/'},timeout=12)
            r.raise_for_status(); j=r.json(); ls=(j.get('data') or {}).get('klines') or []
            if not ls:return None
            x=ls[-1].split(',')
            return {'股票代码':code,'收盘价':float(x[2]),'成交额（亿元）':float(x[6])/1e8,'涨跌幅':float(x[8])/100,'换手率':float(x[10])/100 if x[10] not in ('','-') else None}
        except Exception as e:last=e; time.sleep(0.2*(i+1))
    return {'股票代码':code,'error':str(last)}

def fetch_hist_day(universe,date):
    compact=date.replace('-','')
    names=dict(zip(universe['股票代码'],universe['股票名称']))
    recs=[]; errors=[]
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs={ex.submit(kline_one,c,compact):c for c in universe['股票代码'].tolist()}
        for i,f in enumerate(as_completed(futs),1):
            z=f.result()
            if not z: continue
            if 'error' in z: errors.append(z); continue
            z['股票名称']=names.get(z['股票代码'],'')
            recs.append(z)
            if i%500==0: print('hist',date,i,'ok',len(recs),'err',len(errors),flush=True)
    df=pd.DataFrame(recs)
    if not df.empty:
        df=df[df['成交额（亿元）']>0]
    return df,pd.DataFrame(errors)

def fetch_index(symbol,start,end):
    last=None
    for i in range(4):
        try:
            df=ak.index_zh_a_hist(symbol=symbol,period='daily',start_date=start,end_date=end)
            if df is not None and not df.empty:return df
        except Exception as e:last=e
        time.sleep(2+i*2)
    print('index fail',symbol,last,flush=True); return pd.DataFrame()

def fetch_sw_analysis():
    last=None
    for i in range(4):
        try:
            df=ak.index_analysis_daily_sw(symbol='二级行业',start_date='20260105',end_date='20260810')
            if df is not None and not df.empty:return df
        except Exception as e:last=e
        time.sleep(3+i*3)
    raise RuntimeError(last)

def fetch_bk1106():
    url='https://push2his.eastmoney.com/api/qt/stock/kline/get'
    params={'secid':'90.BK1106','fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61','klt':'101','fqt':'0','beg':'20260101','end':'20260810','lmt':'1000','ut':'fa5fd1943c7b386f172d6893dbfba10b'}
    last=None
    for i in range(8):
        try:
            r=requests.get(url,params=params,headers={'User-Agent':UA,'Referer':'https://quote.eastmoney.com/bk/90.BK1106.html'},timeout=20)
            r.raise_for_status(); j=r.json(); ls=(j.get('data') or {}).get('klines') or []
            if ls:
                rows=[]
                for line in ls:
                    x=line.split(','); rows.append({'日期':x[0],'开盘':float(x[1]),'收盘':float(x[2]),'最高':float(x[3]),'最低':float(x[4]),'成交量':float(x[5]),'成交额（亿元）':float(x[6])/1e8,'振幅':float(x[7])/100,'涨跌幅':float(x[8])/100,'涨跌额':float(x[9]),'换手率':float(x[10])/100 if x[10] not in ('','-') else None})
                return pd.DataFrame(rows)
        except Exception as e:last=e; time.sleep(2+i*2)
    raise RuntimeError(last)

spot=norm_spot(fetch_spot())
sm10,hot10=summarize(spot,TARGET,'AKShare新浪A股实时快照')
spot.to_csv(OUT/'all_a_snapshot_20260810.csv',index=False,encoding='utf-8-sig')
sm10.to_csv(OUT/'market_summary_20260810.csv',index=False,encoding='utf-8-sig')
hot10.to_csv(OUT/'turnover_100bn_stocks_20260810.csv',index=False,encoding='utf-8-sig')

hist7,err7=fetch_hist_day(spot[['股票代码','股票名称']],HIST)
sm7,hot7=summarize(hist7,HIST,'东方财富逐股日K回溯') if not hist7.empty else (pd.DataFrame(),pd.DataFrame())
hist7.to_csv(OUT/'all_a_snapshot_20260807.csv',index=False,encoding='utf-8-sig'); err7.to_csv(OUT/'errors_20260807.csv',index=False,encoding='utf-8-sig')
sm7.to_csv(OUT/'market_summary_20260807.csv',index=False,encoding='utf-8-sig'); hot7.to_csv(OUT/'turnover_100bn_stocks_20260807.csv',index=False,encoding='utf-8-sig')

idx_frames=[]
for sym,name in [('000016','上证50'),('000985','中证全指'),('800007','Choice微盘')]:
    df=fetch_index(sym,'20260807','20260810')
    if not df.empty:
        df.insert(1,'指标',name); df.insert(2,'代码',sym); idx_frames.append(df)
pd.concat(idx_frames,ignore_index=True).to_csv(OUT/'index_snapshot_20260807_20260810.csv',index=False,encoding='utf-8-sig') if idx_frames else None

sw=fetch_sw_analysis(); sw.to_csv(OUT/'sw_analysis_daily_second_2026.csv',index=False,encoding='utf-8-sig')
bk=fetch_bk1106(); bk.to_csv(OUT/'innovation_drug_BK1106_2026.csv',index=False,encoding='utf-8-sig')

meta={'target':TARGET,'hist':HIST,'spot_rows':len(spot),'hist7_rows':len(hist7),'hist7_errors':len(err7),'bk_rows':len(bk),'sw_rows':len(sw)}
(OUT/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(meta,ensure_ascii=False),flush=True)
