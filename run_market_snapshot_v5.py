#!/usr/bin/env python3
"""Final audit runner: corrected market caps and clean SW industry ranking."""
from __future__ import annotations

import logging

import pandas as pd

import build_market_snapshot as base
import run_market_snapshot_v4  # noqa: F401  # applies corrected Tencent parser
import run_market_snapshot_v3 as report


def postprocess_industry_ranking(target_date: str) -> None:
    suffix = target_date
    hot_path = base.DATA_DIR / f"turnover_100bn_stocks_{suffix}.csv"
    industry_path = base.DATA_DIR / f"turnover_100bn_industries_{suffix}.csv"
    quality_path = base.DATA_DIR / f"market_quality_{suffix}.csv"
    unmapped_path = base.DATA_DIR / f"turnover_100bn_unmapped_{suffix}.csv"

    hot = pd.read_csv(hot_path, encoding="utf-8-sig", dtype={"股票代码": str})
    unmapped_mask = hot["申万二级行业"].eq("未匹配") | hot["申万二级行业"].isna()
    unmapped = hot[unmapped_mask].copy()
    mapped = hot[~unmapped_mask].copy()

    industry = (
        mapped.groupby(["申万一级行业", "申万二级行业"], as_index=False)
        .agg(
            百亿成交个股数=("股票代码", "count"),
            合计成交额_亿元=("成交额_亿元", "sum"),
            平均涨跌幅=("涨跌幅", "mean"),
        )
        .sort_values(
            ["百亿成交个股数", "合计成交额_亿元", "申万二级行业"],
            ascending=[False, False, True],
        )
        .reset_index(drop=True)
    )
    industry.insert(0, "排名", range(1, len(industry) + 1))
    industry.to_csv(industry_path, index=False, encoding="utf-8-sig", float_format="%.8f")
    unmapped.to_csv(unmapped_path, index=False, encoding="utf-8-sig", float_format="%.8f")

    quality = pd.read_csv(quality_path, encoding="utf-8-sig")
    quality = pd.concat(
        [
            quality,
            pd.DataFrame(
                [
                    {
                        "检查项": "百亿成交股未匹配申万二级数",
                        "数值": len(unmapped),
                        "状态": "提示" if len(unmapped) else "通过",
                        "说明": "不纳入行业排名，单独输出待申万映射清单",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    quality.to_csv(quality_path, index=False, encoding="utf-8-sig")


def main() -> None:
    args = base.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report.write_outputs_safe(args.target_date, args.workers)
    postprocess_industry_ranking(args.target_date)


if __name__ == "__main__":
    main()
