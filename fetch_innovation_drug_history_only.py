#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
import akshare as ak

OUT = Path('data/innovation_drug_history_raw_2026.csv')
hist = ak.stock_board_concept_index_ths(symbol='创新药', start_date='20260105', end_date='20260810').copy()
for c in ['收盘价','成交量','成交额']:
    hist[c] = pd.to_numeric(hist[c], errors='coerce')
hist['日期'] = pd.to_datetime(hist['日期'], errors='coerce')
hist = hist.dropna(subset=['日期','收盘价','成交量','成交额']).sort_values('日期')
hist['日收益率'] = hist['收盘价'].pct_change(fill_method=None)
OUT.parent.mkdir(parents=True, exist_ok=True)
hist[['日期','收盘价','成交量','成交额','日收益率']].assign(日期=lambda x: x['日期'].dt.strftime('%Y-%m-%d')).to_csv(OUT,index=False,encoding='utf-8-sig',float_format='%.8f')
print(f'history rows={len(hist)} last={hist.iloc[-1].to_dict()}')
