#!/usr/bin/env python3
import inspect, json
from pathlib import Path
import akshare as ak

out=[]
for name in ['stock_board_concept_info_ths','stock_board_industry_info_ths','stock_board_concept_summary_ths','stock_board_industry_summary_ths']:
    func=getattr(ak,name,None)
    item={'name':name,'exists':func is not None}
    if func is not None:
        try:item['signature']=str(inspect.signature(func))
        except Exception as e:item['signature_error']=repr(e)
        for kwargs in ({'symbol':'创新药'},{'symbol_code':'创新药'},{}):
            try:
                df=func(**kwargs)
                item['call']={'kwargs':kwargs,'rows':len(df),'columns':[str(x) for x in df.columns],'head':df.head(10).astype(str).to_dict('records')}
                break
            except Exception as e:
                item.setdefault('errors',[]).append({'kwargs':kwargs,'error':repr(e)})
    out.append(item)
Path('data').mkdir(exist_ok=True)
Path('data/innovation_ths_diagnostic.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
