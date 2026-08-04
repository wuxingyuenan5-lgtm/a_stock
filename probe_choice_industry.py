#!/usr/bin/env python3
from __future__ import annotations

import json
import requests

UA = "Mozilla/5.0"


def get(url: str, params: dict):
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=30)
    r.raise_for_status()
    return r.json()


keywords = ["通信设备", "电脑硬件", "电子元器件", "半导体"]
for keyword in keywords:
    try:
        data = get(
            "https://searchapi.eastmoney.com/api/suggest/get",
            {
                "input": keyword,
                "type": 14,
                "token": "D43BF722C8E33BDC906FB84D85E326E8",
                "count": 20,
            },
        )
        print("SEARCH", keyword, json.dumps(data, ensure_ascii=False)[:5000])
    except Exception as exc:
        print("SEARCH_ERROR", keyword, repr(exc))

for secid in ["47.886060", "90.BK0448", "90.BK1036", "90.BK0816", "90.BK0917"]:
    try:
        quote = get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            {"secid": secid, "fields": "f12,f14,f43,f48,f57,f58,f60,f104,f105,f106,f170", "fltt": 2, "invt": 2},
        )
        print("QUOTE", secid, json.dumps(quote, ensure_ascii=False)[:3000])
    except Exception as exc:
        print("QUOTE_ERROR", secid, repr(exc))
    try:
        hist = get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": 101,
                "fqt": 0,
                "beg": "20260101",
                "end": "20260731",
                "lmt": 300,
            },
        )
        print("HIST", secid, json.dumps(hist, ensure_ascii=False)[:5000])
    except Exception as exc:
        print("HIST_ERROR", secid, repr(exc))
