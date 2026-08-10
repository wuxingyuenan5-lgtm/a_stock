#!/usr/bin/env python3
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json, time
import akshare as ak
import pandas as pd
import requests

TARGET='2026-08-10'; TARGET_COMPACT='20260810'; OUT_TAG='20260810'; DATA=Path('data'); DATA.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'
def num(s): return pd.to_numeric(s,errors='coerce')
def pick(f,*names):
    for n in names:
        if n in f.columns:return n
    raise KeyError(f'missing {names}; actual={list(f.columns)}')
def fetch_spot():
    last=None
    for a in range(1,5):
        try:
            f=ak.stock_zh_a_spot()
            if f is None or f.empty:raise RuntimeError('empty')
            return f
        except Exception as e:last=e;time.sleep(a*3)
    raise RuntimeError(last)
def normalize(raw):
    c=pick(raw,'代码','symbol');n=pick(raw,'名称','name');cl=pick(raw,'最新价','最新','trade');pc=pick(raw,'昨收','昨收盘','settlement');am=pick(raw,'成交额','amount');vo=pick(raw,'成交量','volume');p=pick(raw,'涨跌幅','changepercent')
    o=pd.DataFrame({'股票代码':raw[c].astype(str).str.extract(r'(\d{6})',expand=False),'股票名称':raw[n].astype(str),'收盘价':num(raw[cl]),'昨收价':num(raw[pc]),'成交额_元':num(raw[am]),'成交量':num(raw[vo]),'涨跌幅_pct':num(raw[p])})
    o['涨跌幅']=o['涨跌幅_pct']/100;o=o.dropna();o=o[(o.收盘价>0)&(o.昨收价>0)&(o.成交额_元>0)&(o.成交量>0)];o=o[~o.股票名称.str.contains('ST',case=False,na=False)];o=o[~o.股票名称.str.startswith(('N','C'),na=False)];o=o.drop_duplicates('股票代码',keep='last');o['成交额（亿元）']=o.成交额_元/1e8;return o
def rate(code):
    if code.startswith(('4','8','9')):return Decimal('0.30')
    if code.startswith(('300','301','688','689')):return Decimal('0.20')
    return Decimal('0.10')
def limits(f):
    u=d=0
    for r in f.itertuples(index=False):
        pre=Decimal(str(r.昨收价)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP);close=Decimal(str(r.收盘价)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP);rr=rate(r.股票代码);up=(pre*(1+rr)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP);dn=(pre*(1-rr)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP);u+=int(close==up);d+=int(close==dn)
    return u,d
def index(secid,name):
    url='https://push2his.eastmoney.com/api/qt/stock/kline/get';params={'secid':secid,'fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61','klt':'101','fqt':'0','beg':TARGET_COMPACT,'end':TARGET_COMPACT,'lmt':'10','ut':'fa5fd1943c7b386f172d6893dbfba10b'}
    last=None
    for i in range(5):
        try:
            r=requests.get(url,params=params,headers={'User-Agent':UA,'Referer':'https://quote.eastmoney.com/'},timeout=20);r.raise_for_status();j=r.json();ls=(j.get('data') or {}).get('klines') or []
            if not ls: raise RuntimeError('empty kline')
            x=ls[-1].split(',');return {'日期':x[0],'指标':name,'数据代码':secid,'收盘点位':float(x[2]),'涨跌幅':float(x[8])/100,'成交额（亿元）':float(x[6])/1e8,'数据源':'东方财富历史接口'}
        except Exception as e:last=e;time.sleep(2*(i+1))
    return {'日期':TARGET,'指标':name,'数据代码':secid,'收盘点位':None,'涨跌幅':None,'成交额（亿元）':None,'数据源':f'接口失败: {last}'}
spot=normalize(fetch_spot());u=int((spot.涨跌幅>0).sum());d=int((spot.涨跌幅<0).sum());fl=int((spot.涨跌幅==0).sum());lu,ld=limits(spot);ta=float(spot['成交额（亿元）'].sum());hot=spot[spot['成交额（亿元）']>=100].sort_values('成交额（亿元）',ascending=False).copy();hot.insert(0,'当日排名',range(1,len(hot)+1));hot.insert(0,'日期',TARGET);ha=float(hot['成交额（亿元）'].sum())
summary=pd.DataFrame([{'日期':TARGET,'上涨家数':u,'下跌家数':d,'平盘家数':fl,'涨停家数':lu,'跌停家数':ld,'有效股票数':len(spot),'全部A股成交额（亿元）':ta,'百亿成交股数':len(hot),'百亿成交额（亿元）':ha,'百亿成交集中度':ha/ta if ta else None,'数据源':'AKShare新浪沪深京A股收盘快照+逐股涨跌停价回推'}])
# Persist the reliable market snapshot before attempting any less-stable index endpoints.
summary.to_csv(DATA/f'market_summary_{OUT_TAG}.csv',index=False,encoding='utf-8-sig');hot.to_csv(DATA/f'turnover_100bn_stocks_{OUT_TAG}.csv',index=False,encoding='utf-8-sig');spot.to_csv(DATA/f'all_a_snapshot_{OUT_TAG}.csv',index=False,encoding='utf-8-sig')
indices=pd.DataFrame([index('1.000016','上证50'),index('47.800007','Choice微盘'),index('1.000985','中证全指')]);indices.to_csv(DATA/f'index_snapshot_{OUT_TAG}.csv',index=False,encoding='utf-8-sig')
(DATA/f'metadata_{OUT_TAG}.json').write_text(json.dumps({'target_date':TARGET,'effective':len(spot),'hot':len(hot)},ensure_ascii=False,indent=2),encoding='utf-8');print(summary.to_string(index=False));print(indices.to_string(index=False))
