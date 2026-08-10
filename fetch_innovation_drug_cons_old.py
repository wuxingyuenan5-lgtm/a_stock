#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
import akshare as ak

OUT = Path('data/innovation_drug_constituents_20260810.csv')
cons = ak.stock_board_concept_cons_ths(symbol_code='创新药').copy()
OUT.parent.mkdir(parents=True, exist_ok=True)
cons.to_csv(OUT,index=False,encoding='utf-8-sig')
print('columns=', list(cons.columns))
print('rows=', len(cons))
print(cons.head().to_string(index=False))
