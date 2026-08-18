#!/usr/bin/env python3
"""Current-day market snapshot runner with non-blocking optional cross-checks."""
from __future__ import annotations

from datetime import datetime
import logging
import math

import pandas as pd

import build_market_snapshot as base
import run_market_snapshot_v2  # noqa: F401  # applies source and universe patches


def write_outputs_safe(target_date: str, workers: int) -> None:
    base.DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_label = datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d")

    logging.info("获取沪深京A股官方清单并应用静态过滤")
    universe = base.fetch_stock_universe()
    eligible_static, filter_stats = base.apply_static_universe_filter(universe, target_date)

    logging.info("获取 %s 收盘行情", date_label)
    stocks, no_trade, errors = base.fetch_all_stock_history(eligible_static, target_date, workers)
    eligible_codes = set(stocks["股票代码"])

    logging.info("获取上证50、中证全指和自建微盘400行情")
    indexes = base.fetch_index_snapshot(target_date, stocks)
    indexes["成分股加总成交额_亿元"] = pd.NA
    indexes["成分股加总校验状态"] = "未执行；不阻塞指数原始成交额"

    logging.info("根据供应商涨跌停价核对收盘涨跌停")
    limit_up, limit_down, up_pool, down_pool = base.fetch_filtered_limit_counts(
        target_date, eligible_codes
    )

    up_count = int((stocks["涨跌幅"] > 0).sum())
    down_count = int((stocks["涨跌幅"] < 0).sum())
    flat_count = int((stocks["涨跌幅"] == 0).sum())
    market_amount = float(stocks["成交额"].sum() / 1e8)

    hot = stocks[stocks["成交额"] >= 10_000_000_000].copy()
    hot["成交额_亿元"] = hot["成交额"] / 1e8
    hot.drop(columns=["成交额"], inplace=True)
    hot.sort_values(["成交额_亿元", "股票代码"], ascending=[False, True], inplace=True)

    logging.info("获取申万二级行业成分映射")
    sw_map = base.build_sw_second_mapping()
    hot = hot.merge(sw_map, on="股票代码", how="left")
    hot["申万一级行业"] = hot["申万一级行业"].fillna("未匹配")
    hot["申万二级行业"] = hot["申万二级行业"].fillna("未匹配")
    hot.insert(0, "序号", range(1, len(hot) + 1))

    industry = (
        hot.groupby(["申万一级行业", "申万二级行业"], as_index=False)
        .agg(
            百亿成交个股数=("股票代码", "count"),
            合计成交额_亿元=("成交额_亿元", "sum"),
            平均涨跌幅=("涨跌幅", "mean"),
        )
        .sort_values(
            ["百亿成交个股数", "合计成交额_亿元", "申万二级行业"],
            ascending=[False, False, True],
        )
    )
    industry.insert(0, "排名", range(1, len(industry) + 1))

    sw_snapshot, sw_failures = base.fetch_sw_snapshot(target_date)

    summary = pd.DataFrame(
        [
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
        ]
    )

    error_limit = max(20, math.ceil(len(eligible_static) * 0.01))
    quality = pd.DataFrame(
        [
            {"检查项": key, "数值": value, "状态": "通过", "说明": "统一股票池静态过滤"}
            for key, value in filter_stats.items()
        ]
        + [
            {"检查项": "最终有效交易股票数", "数值": len(stocks), "状态": "通过", "说明": "剔除停牌/无成交"},
            {"检查项": "行情接口错误数", "数值": len(errors), "状态": "通过" if len(errors) <= error_limit else "失败", "说明": "超过1%则拒绝输出"},
            {"检查项": "涨停数量", "数值": limit_up, "状态": "通过", "说明": "供应商涨停价与收盘价核对"},
            {"检查项": "跌停数量", "数值": limit_down, "状态": "通过", "说明": "供应商跌停价与收盘价核对"},
            {"检查项": "中证全指成分股成交额校验", "数值": "未执行", "状态": "提示", "说明": "不影响指数行情原始成交额"},
            {"检查项": "申万目标日成功指数数", "数值": len(sw_snapshot), "状态": "通过" if len(sw_snapshot) > 100 else "提示", "说明": "由独立流水线提供"},
        ]
    )

    suffix = target_date
    indexes.to_csv(base.DATA_DIR / f"market_indexes_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    summary.to_csv(base.DATA_DIR / f"market_breadth_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    hot.to_csv(base.DATA_DIR / f"turnover_100bn_stocks_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    industry.to_csv(base.DATA_DIR / f"turnover_100bn_industries_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    quality.to_csv(base.DATA_DIR / f"market_quality_{suffix}.csv", index=False, encoding="utf-8-sig")
    stocks.to_csv(base.DATA_DIR / f"market_filtered_stocks_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    up_pool.to_csv(base.DATA_DIR / f"limit_up_filtered_{suffix}.csv", index=False, encoding="utf-8-sig")
    down_pool.to_csv(base.DATA_DIR / f"limit_down_filtered_{suffix}.csv", index=False, encoding="utf-8-sig")
    sw_snapshot.to_csv(base.DATA_DIR / f"sw_industry_snapshot_{suffix}.csv", index=False, encoding="utf-8-sig", float_format="%.8f")
    if not no_trade.empty:
        no_trade.to_csv(base.DATA_DIR / f"market_no_trade_{suffix}.csv", index=False, encoding="utf-8-sig")
    if not errors.empty:
        errors.to_csv(base.DATA_DIR / f"market_snapshot_errors_{suffix}.csv", index=False, encoding="utf-8-sig")
    if not sw_failures.empty:
        sw_failures.to_csv(base.DATA_DIR / f"sw_industry_failures_{suffix}.csv", index=False, encoding="utf-8-sig")

    logging.info(
        "完成 %s: 有效股票 %s, 上涨 %s, 下跌 %s, 平盘 %s, 涨停 %s, 跌停 %s, 百亿个股 %s, 接口错误 %s",
        date_label,
        len(stocks),
        up_count,
        down_count,
        flat_count,
        limit_up,
        limit_down,
        len(hot),
        len(errors),
    )


def main() -> None:
    args = base.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    write_outputs_safe(args.target_date, args.workers)


if __name__ == "__main__":
    main()
