#!/usr/bin/env python3
from pathlib import Path
import akshare as ak

OUT=Path('data/innovation_drug_cons_em_20260810.csv')
df=ak.stock_board_concept_cons_em(symbol='创新药')
OUT.parent.mkdir(exist_ok=True)
df.to_csv(OUT,index=False,encoding='utf-8-sig')
print('rows=',len(df),'cols=',list(df.columns))
print(df.head().to_string(index=False))
