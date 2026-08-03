#!/usr/bin/env python3
"""Fetch 2026 BSE stock history from Tencent using the validated 2026-07-31 code list."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time

import akshare as ak
import pandas as pd

DATA_DIR = Path("data")
BJ_CODES = "920000,920001,920002,920003,920005,920006,920007,920008,920009,920010,920011,920012,920014,920015,920016,920017,920018,920019,920020,920021,920022,920026,920027,920028,920029,920030,920033,920035,920036,920037,920039,920045,920046,920047,920050,920055,920056,920057,920058,920060,920061,920062,920065,920066,920068,920069,920072,920075,920076,920077,920078,920079,920080,920081,920082,920083,920086,920087,920088,920089,920091,920092,920096,920098,920099,920100,920101,920106,920108,920110,920111,920112,920116,920117,920118,920119,920121,920122,920123,920124,920125,920126,920128,920130,920132,920136,920139,920145,920146,920149,920152,920156,920158,920159,920160,920161,920163,920166,920167,920168,920169,920171,920174,920175,920176,920177,920178,920179,920180,920181,920183,920184,920185,920186,920187,920188,920189,920190,920191,920193,920195,920198,920199,920200,920204,920206,920207,920208,920211,920212,920218,920220,920221,920222,920223,920225,920227,920230,920237,920238,920239,920242,920245,920247,920249,920252,920260,920261,920262,920263,920266,920267,920270,920271,920273,920274,920275,920278,920284,920299,920300,920304,920339,920344,920346,920351,920357,920363,920367,920368,920370,920371,920374,920375,920378,920392,920394,920395,920396,920402,920403,920405,920407,920414,920415,920418,920419,920422,920425,920427,920429,920433,920436,920438,920445,920454,920455,920469,920471,920475,920476,920478,920489,920491,920493,920496,920504,920505,920508,920509,920510,920519,920522,920523,920526,920527,920533,920541,920547,920553,920556,920564,920566,920570,920571,920576,920578,920579,920580,920592,920593,920599,920608,920627,920634,920639,920640,920641,920642,920651,920656,920662,920663,920665,920670,920675,920679,920682,920685,920689,920690,920693,920694,920699,920701,920703,920706,920717,920718,920719,920720,920725,920726,920729,920735,920748,920751,920753,920765,920768,920770,920779,920781,920786,920790,920792,920799,920802,920806,920807,920808,920809,920810,920819,920821,920826,920832,920833,920834,920837,920839,920855,920856,920857,920866,920870,920871,920873,920876,920879,920885,920892,920895,920896,920906,920914,920924,920925,920926,920931,920932,920942,920943,920946,920950,920953,920957,920961,920964,920970,920971,920974,920976,920978,920981,920982,920985,920992".split(",")


def fetch_one(code: str, start: str, end: str) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            frame = ak.stock_zh_a_hist_tx(symbol=f"bj{code}", start_date=start, end_date=end, adjust="", timeout=25)
            if frame is None or frame.empty:
                raise RuntimeError("empty")
            frame = frame.copy()
            frame["日期"] = pd.to_datetime(frame["date"], errors="coerce")
            frame["收盘价"] = pd.to_numeric(frame["close"], errors="coerce")
            frame["成交量"] = pd.to_numeric(frame["volume"], errors="coerce")
            frame["成交额"] = pd.to_numeric(frame["amount"], errors="coerce")
            frame["换手率"] = pd.to_numeric(frame["turnover"], errors="coerce")
            frame["昨收价"] = frame["收盘价"].shift(1)
            frame["涨跌幅"] = frame["收盘价"] / frame["昨收价"] - 1
            frame["股票代码"] = code
            # First available row is the listing/no-limit session if the stock listed during the interval.
            frame = frame.iloc[1:].copy() if not frame.empty else frame
            frame = frame[(frame["成交额"] > 0) & (frame["成交量"] > 0)]
            return frame[["日期","股票代码","收盘价","昨收价","成交量","成交额","换手率","涨跌幅"]]
        except Exception as exc:
            last_error = exc
            time.sleep(attempt * 0.6)
    assert last_error is not None
    raise last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="20260101")
    parser.add_argument("--end-date", default="20260803")
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    DATA_DIR.mkdir(exist_ok=True)
    frames = []
    errors = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch_one, code, args.start_date, args.end_date): code for code in BJ_CODES}
        for future in as_completed(futures):
            code = futures[future]
            try:
                frames.append(future.result())
            except Exception as exc:
                errors.append({"股票代码": code, "错误": str(exc)})
    output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not output.empty:
        output.sort_values(["日期", "股票代码"], inplace=True)
        output.to_csv(DATA_DIR / "bj_stock_history_tx_static_2026.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    pd.DataFrame(errors).to_csv(DATA_DIR / "bj_stock_history_tx_static_errors_2026.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([
        {"检查项":"北交所静态代码数","数值":len(BJ_CODES),"状态":"通过","说明":"2026-07-31已验证非ST有效池"},
        {"检查项":"腾讯成功股票数","数值":int(output["股票代码"].nunique()) if not output.empty else 0,"状态":"通过" if not output.empty and output["股票代码"].nunique()>250 else "提示","说明":f"失败={len(errors)}"},
        {"检查项":"腾讯历史记录数","数值":len(output),"状态":"通过" if len(output)>30000 else "提示","说明":f"{args.start_date}-{args.end_date}"},
    ]).to_csv(DATA_DIR / "bj_stock_history_tx_static_quality_2026.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
