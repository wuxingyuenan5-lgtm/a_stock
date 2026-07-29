#!/usr/bin/env python3
"""Build a date-consistent A-share monitoring snapshot.

Universe for breadth and turnover screens:
- Shanghai / Shenzhen / Beijing A shares
- exclude ST names
- exclude listing day
- exclude suspended / no-trade securities on the target date

No news articles are used as a numerical data source.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import logging
import math
from pathlib import Path
import random
import time
from typing import Callable, TypeVar

import akshare as ak
import pandas as pd
import requests

DATA_DIR = Path("data")
DEFAULT_TARGET_DATE = "20260728"
DEFAULT_WORKERS = 32
VOL_WINDOW = 20
ANNUALIZATION_DAYS = 252
T = TypeVar("T")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_MIN_INTERVAL = 0.8
_em_last_call = [0.0]


class NoTradingData(RuntimeError):
    """No target-date bar: suspension, no listing yet, or no trade."""


def retry(call: Callable[[], T], attempts: int = 3, delay: float = 0.8) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay * attempt)
    assert last_error is not None
    raise last_error


def em_get(url: str, params: dict, timeout: int = 20) -> requests.Response:
    """Eastmoney request with light throttling and retry-friendly headers."""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.05, 0.20))
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response
    finally:
        _em_last_call[0] = time.time()


def normalize_code(value: object) -> str:
    return str(value).strip().split(".")[0].zfill(6)


def parse_listing_date(value: object) -> str:
    text = str(value or "").strip().replace(".0", "")
    if len(text) == 8 and text.isdigit():
        return text
    return ""


def fetch_stock_universe() -> pd.DataFrame:
    """Fetch all Shanghai/Shenzhen/Beijing A shares, including listing date."""
    url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    rows: list[dict[str, object]] = []
    page_size = 1000
    for page in range(1, 12):
        params = {
            "pn": page,
            "pz": page_size,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "fields": "f12,f14,f20,f21,f26",
        }
        data = retry(lambda params=params: em_get(url, params).json()).get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        if not diff:
            break
        for item in diff:
            rows.append(
                {
                    "股票代码": normalize_code(item.get("f12")),
                    "股票名称": str(item.get("f14") or "").strip(),
                    "总市值": pd.to_numeric(item.get("f20"), errors="coerce"),
                    "流通市值": pd.to_numeric(item.get("f21"), errors="coerce"),
                    "上市日期": parse_listing_date(item.get("f26")),
                }
            )
        if len(diff) < page_size:
            break
    frame = pd.DataFrame(rows).drop_duplicates("股票代码")
    if frame.empty:
        raise RuntimeError("A股代码清单为空")
    return frame


def apply_static_universe_filter(universe: pd.DataFrame, target_date: str) -> tuple[pd.DataFrame, dict[str, int]]:
    name_upper = universe["股票名称"].astype(str).str.upper()
    st_mask = name_upper.str.contains("ST", regex=False)
    first_day_mask = universe["上市日期"].eq(target_date)
    eligible = universe[~st_mask & ~first_day_mask].copy()
    stats = {
        "原始沪深京A股数": int(len(universe)),
        "剔除ST数": int(st_mask.sum()),
        "剔除上市首日数": int((first_day_mask & ~st_mask).sum()),
        "静态筛选后数量": int(len(eligible)),
    }
    return eligible, stats


def fetch_one_stock(row: pd.Series, target_date: str) -> dict[str, object]:
    code = row["股票代码"]
    raw = retry(
        lambda: ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=target_date,
            end_date=target_date,
            adjust="",
            timeout=20,
        ),
        attempts=3,
        delay=0.5,
    )
    required = {"日期", "收盘", "成交额", "涨跌幅"}
    if raw.empty or not required.issubset(raw.columns):
        raise NoTradingData("目标日无行情")
    record = raw.iloc[-1]
    amount = pd.to_numeric(record["成交额"], errors="coerce")
    close = pd.to_numeric(record["收盘"], errors="coerce")
    if pd.isna(amount) or pd.isna(close) or float(amount) <= 0 or float(close) <= 0:
        raise NoTradingData("目标日停牌或无成交")
    return {
        "日期": pd.to_datetime(record["日期"]).strftime("%Y-%m-%d"),
        "股票代码": code,
        "股票名称": row["股票名称"],
        "上市日期": row["上市日期"],
        "收盘价": float(close),
        "涨跌幅": float(pd.to_numeric(record["涨跌幅"], errors="coerce")) / 100,
        "成交额": float(amount),
        "总市值": pd.to_numeric(row.get("总市值"), errors="coerce"),
        "流通市值": pd.to_numeric(row.get("流通市值"), errors="coerce"),
    }


def fetch_all_stock_history(
    universe: pd.DataFrame, target_date: str, workers: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    records: list[dict[str, object]] = []
    no_trade: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    rows = [row.copy() for _, row in universe.iterrows()]
    total = len(rows)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_one_stock, row, target_date): row for row in rows}
        for position, future in enumerate(as_completed(future_map), start=1):
            row = future_map[future]
            try:
                records.append(future.result())
            except NoTradingData as exc:
                no_trade.append({"股票代码": row["股票代码"], "股票名称": str(row["股票名称"]), "原因": str(exc)})
            except Exception as exc:
                errors.append({"股票代码": row["股票代码"], "股票名称": str(row["股票名称"]), "错误": str(exc)})
            if position % 250 == 0 or position == total:
                logging.info(
                    "个股进度 %s/%s, 成功 %s, 无交易 %s, 接口错误 %s",
                    position,
                    total,
                    len(records),
                    len(no_trade),
                    len(errors),
                )
    data = pd.DataFrame(records)
    if data.empty:
        raise RuntimeError("未获取到任何目标日个股行情")
    error_limit = max(20, math.ceil(total * 0.01))
    if len(errors) > error_limit:
        raise RuntimeError(f"接口错误 {len(errors)} 个，超过容忍上限 {error_limit}，拒绝输出不完整市场宽度")
    return data, pd.DataFrame(no_trade), pd.DataFrame(errors)


def fetch_em_index_row(name: str, secid: str, target_date: str, source: str) -> dict[str, object]:
    target_dt = datetime.strptime(target_date, "%Y%m%d")
    start_date = (target_dt - timedelta(days=20)).strftime("%Y%m%d")
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": 101,
        "fqt": 0,
        "beg": start_date,
        "end": target_date,
    }
    payload = retry(lambda: em_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", params).json())
    klines = ((payload.get("data") or {}).get("klines") or [])
    rows = [item.split(",") for item in klines]
    frame = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume", "amount", "extra"])
    if frame.empty:
        raise RuntimeError(f"{name} 无历史行情: secid={secid}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("close", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    target = frame[frame["date"].dt.strftime("%Y%m%d") == target_date]
    if target.empty:
        raise RuntimeError(f"{name} 缺少目标日 {target_date}")
    idx = target.index[-1]
    pos = frame.index.get_loc(idx)
    close = float(frame.loc[idx, "close"])
    previous = float(frame.iloc[pos - 1]["close"]) if pos > 0 else float("nan")
    return {
        "日期": target_dt.strftime("%Y-%m-%d"),
        "指标": name,
        "数据代码": secid,
        "收盘点位": close,
        "涨跌幅": close / previous - 1 if pos > 0 else float("nan"),
        "成交额_亿元": float(frame.loc[idx, "amount"]) / 1e8,
        "数据来源": source,
        "数据口径": "指数行情成交额",
        "替代状态": "原始指标",
    }


def build_micro_fallback(stocks: pd.DataFrame, n: int = 400) -> dict[str, object]:
    candidates = stocks.dropna(subset=["总市值"]).sort_values(["总市值", "股票代码"]).head(n)
    if len(candidates) < n * 0.9:
        raise RuntimeError("自建微盘组合有效样本不足")
    return {
        "日期": str(candidates["日期"].iloc[0]),
        "指标": f"自建微盘{n}等权",
        "数据代码": f"CUSTOM_MICRO_{n}",
        "收盘点位": float("nan"),
        "涨跌幅": float(candidates["涨跌幅"].mean()),
        "成交额_亿元": float(candidates["成交额"].sum() / 1e8),
        "数据来源": "沪深京A股筛选后自建",
        "数据口径": f"总市值最小{n}只等权收益、成交额求和",
        "替代状态": "Choice微盘接口失败后的明确替代",
    }


def fetch_index_snapshot(target_date: str, stocks: pd.DataFrame) -> pd.DataFrame:
    rows = [fetch_em_index_row("上证50", "1.000016", target_date, "东方财富指数行情")]
    try:
        rows.append(fetch_em_index_row("Choice微盘股指数", "47.800007", target_date, "东方财富Choice指数行情"))
    except Exception as exc:
        logging.warning("Choice微盘股指数失败，启用自建微盘400: %s", exc)
        rows.append(build_micro_fallback(stocks, 400))
    rows.append(fetch_em_index_row("中证全指", "1.000985", target_date, "东方财富指数行情"))
    return pd.DataFrame(rows)


def fetch_limit_pool(endpoint: str, target_date: str, sort: str) -> pd.DataFrame:
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": 0,
        "pagesize": 10000,
        "sort": sort,
        "date": target_date,
    }
    payload = retry(lambda: em_get(f"https://push2ex.eastmoney.com/{endpoint}", params).json())
    pool = ((payload.get("data") or {}).get("pool") or [])
    return pd.DataFrame(
        [{"股票代码": normalize_code(item.get("c")), "股票名称": str(item.get("n") or "")} for item in pool]
    ).drop_duplicates("股票代码")


def fetch_filtered_limit_counts(target_date: str, eligible_codes: set[str]) -> tuple[int, int, pd.DataFrame, pd.DataFrame]:
    up = fetch_limit_pool("getTopicZTPool", target_date, "fbt:asc")
    down = fetch_limit_pool("getTopicDTPool", target_date, "fund:asc")
    up_filtered = up[up["股票代码"].isin(eligible_codes)].copy()
    down_filtered = down[down["股票代码"].isin(eligible_codes)].copy()
    return len(up_filtered), len(down_filtered), up_filtered, down_filtered


def fetch_csi_all_share_constituents() -> set[str]:
    frame = retry(lambda: ak.index_stock_cons_csindex(symbol="000985"))
    if frame.empty or "成分券代码" not in frame.columns:
        raise RuntimeError("中证全指成分股清单为空")
    return set(frame["成分券代码"].map(normalize_code))


def build_sw_second_mapping() -> pd.DataFrame:
    info = retry(ak.sw_index_second_info)
    required = {"行业代码", "行业名称", "上级行业"}
    if info.empty or not required.issubset(info.columns):
        raise ValueError(f"申万二级行业信息异常: {list(info.columns)}")
    records: list[dict[str, str]] = []
    for _, row in info.iterrows():
        industry_code = normalize_code(row["行业代码"])
        try:
            cons = retry(lambda code=industry_code: ak.index_component_sw(symbol=code))
        except Exception as exc:
            logging.warning("申万二级行业成分失败 %s: %s", industry_code, exc)
            continue
        if cons.empty or "证券代码" not in cons.columns:
            continue
        records.extend(
            {
                "股票代码": normalize_code(code),
                "申万一级行业": str(row["上级行业"]).strip(),
                "申万二级行业": str(row["行业名称"]).strip(),
            }
            for code in cons["证券代码"].dropna().astype(str)
        )
    return pd.DataFrame(records).drop_duplicates("股票代码", keep="first")


def load_sw_universe() -> pd.DataFrame:
    first = retry(ak.sw_index_first_info)[["行业代码", "行业名称"]].copy()
    first.columns = ["指数代码", "指数名称"]
    first["指数代码"] = first["指数代码"].map(normalize_code)
    first["行业层级"] = "一级行业"
    first["一级行业"] = first["指数名称"]
    second = retry(ak.sw_index_second_info)[["行业代码", "行业名称", "上级行业"]].copy()
    second.columns = ["指数代码", "指数名称", "一级行业"]
    second["指数代码"] = second["指数代码"].map(normalize_code)
    second["行业层级"] = "二级行业"
    return pd.concat(
        [first[["行业层级", "一级行业", "指数代码", "指数名称"]], second[["行业层级", "一级行业", "指数代码", "指数名称"]]],
        ignore_index=True,
    ).drop_duplicates("指数代码")


def fetch_one_sw_index(row: pd.Series, target_date: str) -> dict[str, object]:
    raw = retry(lambda: ak.index_hist_sw(symbol=row["指数代码"], period="day"))
    required = {"日期", "收盘", "成交额"}
    if raw.empty or not required.issubset(raw.columns):
        raise RuntimeError("申万指数行情为空")
    frame = raw[["日期", "收盘", "成交额"]].copy()
    frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
    frame["收盘"] = pd.to_numeric(frame["收盘"], errors="coerce")
    frame["成交额"] = pd.to_numeric(frame["成交额"], errors="coerce")
    frame = frame.dropna(subset=["日期", "收盘"]).sort_values("日期")
    frame = frame[frame["日期"].dt.strftime("%Y%m%d") <= target_date].tail(VOL_WINDOW + 1)
    if len(frame) < VOL_WINDOW + 1 or frame.iloc[-1]["日期"].strftime("%Y%m%d") != target_date:
        raise NoTradingData("目标日申万指数数据未发布")
    returns = frame["收盘"].pct_change(fill_method=None).dropna()
    return {
        "日期": frame.iloc[-1]["日期"].strftime("%Y-%m-%d"),
        "行业层级": row["行业层级"],
        "一级行业": row["一级行业"],
        "指数代码": row["指数代码"],
        "指数名称": row["指数名称"],
        "收盘价": float(frame.iloc[-1]["收盘"]),
        "成交额_亿元": float(frame.iloc[-1]["成交额"]),
        "日收益率": float(returns.iloc[-1]),
        "20日年化波动率": float(returns.std(ddof=1) * math.sqrt(ANNUALIZATION_DAYS)),
    }


def fetch_sw_snapshot(target_date: str, workers: int = 6) -> tuple[pd.DataFrame, pd.DataFrame]:
    universe = load_sw_universe()
    records: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_one_sw_index, row, target_date): row for _, row in universe.iterrows()}
        for future in as_completed(future_map):
            row = future_map[future]
            try:
                records.append(future.result())
            except Exception as exc:
                failures.append({"指数代码": row["指数代码"], "指数名称": row["指数名称"], "错误": str(exc)})
    frame = pd.DataFrame(records)
    if not frame.empty:
        frame.sort_values(["行业层级", "一级行业", "指数名称"], inplace=True)
    return frame, pd.DataFrame(failures)


def write_outputs(target_date: str, workers: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_label = datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d")

    logging.info("获取沪深京A股清单并应用静态过滤")
    universe = fetch_stock_universe()
    eligible_static, filter_stats = apply_static_universe_filter(universe, target_date)

    logging.info("获取 %s 个股日行情", date_label)
    stocks, no_trade, errors = fetch_all_stock_history(eligible_static, target_date, workers)
    eligible_codes = set(stocks["股票代码"])

    logging.info("获取指数行情；Choice微盘使用专属 secid=47.800007，中证全指使用 secid=1.000985")
    indexes = fetch_index_snapshot(target_date, stocks)

    logging.info("获取中证全指官方成分并加总成交额")
    csi_codes = fetch_csi_all_share_constituents()
    csi_component_amount = float(stocks.loc[stocks["股票代码"].isin(csi_codes), "成交额"].sum() / 1e8)
    indexes["成分股加总成交额_亿元"] = pd.NA
    indexes.loc[indexes["指标"] == "中证全指", "成分股加总成交额_亿元"] = csi_component_amount

    logging.info("获取东财涨停/跌停池并与统一股票池取交集")
    limit_up, limit_down, up_pool, down_pool = fetch_filtered_limit_counts(target_date, eligible_codes)

    up_count = int((stocks["涨跌幅"] > 0).sum())
    down_count = int((stocks["涨跌幅"] < 0).sum())
    flat_count = int((stocks["涨跌幅"] == 0).sum())
    market_amount = float(stocks["成交额"].sum() / 1e8)

    hot = stocks[stocks["成交额"] >= 10_000_000_000].copy()
    hot["成交额_亿元"] = hot["成交额"] / 1e8
    hot.drop(columns=["成交额"], inplace=True)
    hot.sort_values(["成交额_亿元", "股票代码"], ascending=[False, True], inplace=True)

    logging.info("获取申万二级行业映射")
    sw_map = build_sw_second_mapping()
    hot = hot.merge(sw_map, on="股票代码", how="left")
    hot["申万一级行业"] = hot["申万一级行业"].fillna("未匹配")
    hot["申万二级行业"] = hot["申万二级行业"].fillna("未匹配")
    hot.insert(0, "序号", range(1, len(hot) + 1))
    industry = (
        hot.groupby(["申万一级行业", "申万二级行业"], as_index=False)
        .agg(百亿成交个股数=("股票代码", "count"), 合计成交额_亿元=("成交额_亿元", "sum"), 平均涨跌幅=("涨跌幅", "mean"))
        .sort_values(["百亿成交个股数", "合计成交额_亿元", "申万二级行业"], ascending=[False, False, True])
    )
    industry.insert(0, "排名", range(1, len(industry) + 1))

    logging.info("获取目标日申万一级/二级行业指数快照")
    sw_snapshot, sw_failures = fetch_sw_snapshot(target_date)

    summary = pd.DataFrame([
        {
            "日期": date_label,
            "股票池口径": "沪深京A股，剔除ST、停牌/无成交、上市首日",
            "上涨家数": up_count,
            "下跌家数": down_count,
            "平盘家数": flat_count,
            "涨停家数": limit_up,
            "跌停家数": limit_down,
            "最终有效股票数": len(stocks),
            "无交易/停牌数": len(no_trade),
            "接口错误数": len(errors),
            "全部A股成交额_亿元": market_amount,
            "成交额超百亿个股数": len(hot),
            "百亿个股成交额合计_亿元": float(hot["成交额_亿元"].sum()),
        }
    ])
    quality = pd.DataFrame([
        {"检查项": key, "数值": value, "状态": "通过", "说明": "统一股票池静态过滤"}
        for key, value in filter_stats.items()
    ] + [
        {"检查项": "最终有效交易股票数", "数值": len(stocks), "状态": "通过", "说明": "剔除停牌/无成交"},
        {"检查项": "历史行情接口错误数", "数值": len(errors), "状态": "通过" if len(errors) <= max(20, math.ceil(len(eligible_static) * 0.01)) else "失败", "说明": "超过1%则拒绝输出"},
        {"检查项": "涨停池过滤后数量", "数值": limit_up, "状态": "通过", "说明": "东财涨停池与统一股票池取交集"},
        {"检查项": "跌停池过滤后数量", "数值": limit_down, "状态": "通过", "说明": "东财跌停池与统一股票池取交集"},
        {"检查项": "申万目标日成功指数数", "数值": len(sw_snapshot), "状态": "通过" if len(sw_snapshot) > 100 else "提示", "说明": "只保留目标日已发布数据"},
        {"检查项": "申万目标日失败指数数", "数值": len(sw_failures), "状态": "提示" if len(sw_failures) else "通过", "说明": "不使用前一交易日冒充"},
    ])

    suffix = target_date
    indexes.to_csv(DATA_DIR / f"market_indexes_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    summary.to_csv(DATA_DIR / f"market_breadth_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    hot.to_csv(DATA_DIR / f"turnover_100bn_stocks_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    industry.to_csv(DATA_DIR / f"turnover_100bn_industries_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    quality.to_csv(DATA_DIR / f"market_quality_{suffix}.csv", index=False, encoding="utf-8-sig")
    stocks.to_csv(DATA_DIR / f"market_filtered_stocks_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    up_pool.to_csv(DATA_DIR / f"limit_up_filtered_{suffix}.csv", index=False, encoding="utf-8-sig")
    down_pool.to_csv(DATA_DIR / f"limit_down_filtered_{suffix}.csv", index=False, encoding="utf-8-sig")
    sw_snapshot.to_csv(DATA_DIR / f"sw_industry_snapshot_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    if not no_trade.empty:
        no_trade.to_csv(DATA_DIR / f"market_no_trade_{suffix}.csv", index=False, encoding="utf-8-sig")
    if not errors.empty:
        errors.to_csv(DATA_DIR / f"market_snapshot_errors_{suffix}.csv", index=False, encoding="utf-8-sig")
    if not sw_failures.empty:
        sw_failures.to_csv(DATA_DIR / f"sw_industry_failures_{suffix}.csv", index=False, encoding="utf-8-sig")

    logging.info(
        "完成 %s: 有效股票 %s, 上涨 %s, 下跌 %s, 平盘 %s, 涨停 %s, 跌停 %s, 百亿个股 %s, 接口错误 %s",
        date_label, len(stocks), up_count, down_count, flat_count, limit_up, limit_down, len(hot), len(errors),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股每日市场监控快照")
    parser.add_argument("--target-date", default=DEFAULT_TARGET_DATE, help="YYYYMMDD")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    write_outputs(args.target_date, args.workers)


if __name__ == "__main__":
    main()
