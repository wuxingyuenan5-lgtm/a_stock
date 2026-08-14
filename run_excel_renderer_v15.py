#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import excel_renderer_artifact as core
import run_excel_renderer_v14 as v14


VERSION = "1.5"
ORIGINAL_SYNC_00 = v14.sync_00
ORIGINAL_UPDATE_99 = v14.update_99
ORIGINAL_VALIDATE = v14.validate


def _existing_innovation_rows(wb) -> dict[str, dict[str, object]]:
    sh = wb.worksheets.get_item("07_创新药交易拥挤度")
    n = core.nrows(sh, 33, 1000)
    out: dict[str, dict[str, object]] = {}
    if not n:
        return out
    for row in sh.get_range(f"A33:H{32+n}").values:
        if row[0] in (None, ""):
            continue
        d = v14.as_date(row[0]).isoformat()
        out[d] = {
            "date": d,
            "amount": row[1],
            "share": row[2],
            "turnover": row[3],
            "activity": None,
            "return": row[5],
            "volume": row[6],
            "source": row[7] or "滚动母表已验证历史",
            "mode": "rolling_verified",
        }
    return out


def _all_a_denominators(wb) -> dict[str, float]:
    out = {}
    for row in core.history02(wb):
        amount = row.get("market_amount")
        if amount not in (None, ""):
            out[v14.as_date(row["date"]).isoformat()] = float(amount)
    return out


def update_07_rolling(wb, selected_rows: list[dict], payload: dict):
    """Field-level rolling merge for innovation-drug history.

    Invariants:
    - a fallback source may fill a missing amount/share/return, but may never erase
      a verified historical turnover value already present in the rolling mother;
    - turnover is always a supplier-direct board turnover field, never a proxy;
    - the 20d volume-activity proxy is retired from the workbook and charts;
    - target-day turnover stays blank when no reliable direct field is available.
    """
    target = payload["date"]
    existing = _existing_innovation_rows(wb)
    denominators = _all_a_denominators(wb)

    # Seed only missing historical cells from the selected history bundle. Existing
    # verified non-null values always win across source changes.
    incoming = [r for r in selected_rows if r.get("date") and r["date"] <= target]
    for row in incoming:
        d = row["date"]
        current = existing.setdefault(d, {
            "date": d, "amount": None, "share": None, "turnover": None,
            "activity": None, "return": None, "volume": None,
            "source": row.get("source") or "render bundle history",
            "mode": row.get("mode") or "selected_history",
        })
        for field in ("amount", "share", "return", "volume"):
            if current.get(field) in (None, "") and row.get(field) not in (None, ""):
                current[field] = row[field]
        if current.get("turnover") in (None, "") and row.get("turnover") not in (None, ""):
            current["turnover"] = row["turnover"]
        # Do not carry or chart the retired activity proxy.
        current["activity"] = None
        if current.get("source") in (None, "", "滚动母表已验证历史") and row.get("source"):
            current["source"] = row["source"]

    # Mathematically recover missing historical amount-share when the same-day
    # all-A denominator is already verified in sheet 02. This is not cross-source
    # substitution; it is the defined ratio amount / all-A amount.
    for d, row in existing.items():
        if row.get("share") in (None, "") and row.get("amount") not in (None, "") and d in denominators:
            row["share"] = float(row["amount"]) / denominators[d]

    # Target-day current snapshot has priority for current amount/share/return.
    # A null turnover never overwrites a verified turnover on same-date reruns.
    current_payload = payload.get("innovation_drug") or {}
    if current_payload.get("date") == target:
        row = existing.setdefault(target, {
            "date": target, "amount": None, "share": None, "turnover": None,
            "activity": None, "return": None, "volume": None,
            "source": "", "mode": "current",
        })
        mapping = {
            "amount": current_payload.get("amount_100m"),
            "share": current_payload.get("amount_share_of_a"),
            "turnover": current_payload.get("turnover"),
            "return": current_payload.get("return"),
            "volume": current_payload.get("volume"),
        }
        for field, value in mapping.items():
            if value not in (None, ""):
                row[field] = value
        row["activity"] = None
        source = current_payload.get("source") or "current innovation snapshot"
        if current_payload.get("turnover") in (None, ""):
            row["source"] = f"{source}；成交额/收益已更新；换手率等待可靠供应商直接字段"
        else:
            row["source"] = f"{source}；换手率=供应商直接板块字段"
        row["mode"] = "current"

    rows = sorted(existing.values(), key=lambda r: r["date"], reverse=True)
    if not rows:
        return None

    sh = wb.worksheets.get_item("07_创新药交易拥挤度")
    old_n = core.nrows(sh, 33, 1000)
    core.grow_style(sh, 33, old_n, len(rows), "H")
    values = [[
        v14.serial(r["date"]), r.get("amount"), r.get("share"), r.get("turnover"), None,
        r.get("return"), r.get("volume"), r.get("source") or "滚动历史",
    ] for r in rows]
    sh.get_range(f"A33:H{32+len(rows)}").values = values
    core.clear_tail(sh, 33, old_n, len(rows), "H", 8)
    sh.get_range("A32:H32").values = [[
        "日期", "成交额（亿元）", "成交额占全部A股", "换手率", "",
        "日收益率", "成交量（股）", "数据状态/来源",
    ]]
    sh.get_range("A1").values = [["创新药交易拥挤度｜成交额占比 + 可靠换手率"]]
    sh.get_range("A3").values = [[
        "创新药为独立主题。换手率仅接受供应商直接板块换手率；"
        "20日成交量活跃度代理已停用，不得替代换手率。"
        "来源切换时只填补缺失字段，不得覆盖滚动母表已验证历史。"
    ]]

    asc = sorted(rows, key=lambda r: r["date"])
    share_rows = [r for r in asc if r.get("share") not in (None, "")]
    turnover_rows = [r for r in asc if r.get("turnover") not in (None, "")]
    c0, c1 = sh.charts.items[0], sh.charts.items[1]
    s0, s1 = c0.series.items[0], c1.series.items[0]
    s0.name = "创新药成交额占全A"
    s0.categories = [datetime.strptime(r["date"], "%Y-%m-%d").strftime("%m-%d") for r in share_rows]
    s0.values = [r["share"] for r in share_rows]
    s1.name = "创新药换手率"
    s1.categories = [datetime.strptime(r["date"], "%Y-%m-%d").strftime("%m-%d") for r in turnover_rows]
    s1.values = [r["turnover"] for r in turnover_rows]

    share_latest = share_rows[-1]["date"] if share_rows else None
    turnover_latest = turnover_rows[-1]["date"] if turnover_rows else None
    c0.title_text = (
        f"创新药｜成交额占全A（至{share_latest[5:] if share_latest else '无'}）"
        f"与换手率（至{turnover_latest[5:] if turnover_latest else '无'}）"
    )
    sh.get_range("A4").values = [[
        f"创新药｜成交额占全A（最新{share_latest or '无'}）与可靠换手率（最新{turnover_latest or '无'}）"
    ]]
    sh.get_range("A30").values = [[
        f"创新药历史明细｜成交额/占比最新{share_latest or '无'}｜可靠换手率最新{turnover_latest or '无'}"
    ]]

    target_row = next((r for r in rows if r["date"] == target), None)
    return {
        "mode": "rolling_field_level",
        "has_turnover": bool(turnover_rows),
        "target_turnover_available": bool(target_row and target_row.get("turnover") not in (None, "")),
        "share_latest_date": share_latest,
        "turnover_latest_date": turnover_latest,
        "rows": rows,
    }


def sync_00_v15(wb, payload: dict, market_rows: list[dict], innovation) -> None:
    ORIGINAL_SYNC_00(wb, payload, market_rows, innovation)
    sh = wb.worksheets.get_item("00_市场总览")

    # Make the effective date visually explicit; Excel may auto-skip x-axis labels.
    sh.charts.items[0].title_text = f"市场涨跌结构｜至{payload['date']}"
    sh.charts.items[1].title_text = f"涨停与跌停家数｜至{payload['date']}"
    sh.charts.items[2].title_text = f"市场宽度｜至{payload['date']}"

    if innovation:
        latest = innovation["rows"][0]
        sh.get_range("A30:H30").values = [[
            v14.serial(latest["date"]), latest.get("amount"), latest.get("share"), latest.get("turnover"),
            None, latest.get("return"),
            "已更新" if innovation.get("target_turnover_available") else "部分更新",
            latest.get("source") or "创新药滚动历史",
        ]]
        share_latest = innovation.get("share_latest_date")
        turnover_latest = innovation.get("turnover_latest_date")
        sh.get_range("A38:E38").values = [[
            "07创新药",
            f"成交额/占比至{share_latest or '无'}；换手率至{turnover_latest or '无'}",
            "已更新" if innovation.get("target_turnover_available") else "部分更新",
            "字段级滚动来源",
            "20日成交量活跃度代理已停用",
        ]]
        sh.get_range("Q78").values = [[
            f"创新药｜成交额占全A（至{share_latest[5:] if share_latest else '无'}）"
            f"与换手率（至{turnover_latest[5:] if turnover_latest else '无'}）"
        ]]
        sh.get_range("AC79").values = [["━ 创新药换手率（右轴，供应商直接字段）"]]
        sh.charts.items[7].title_text = sh.get_range("Q78").values[0][0]


def update_99_v15(wb, payload: dict, validation: dict, innovation, mother_sha: str, extra: dict) -> None:
    ORIGINAL_UPDATE_99(wb, payload, validation, innovation, mother_sha, extra)
    sh = wb.worksheets.get_item("99_口径与质量")
    sh.get_range("A3").values = [[
        f"截至{payload['date']}。缺失保持空白，不以0替代；创新药换手率仅接受供应商直接字段；"
        f"20日成交量活跃度代理已停用；Renderer v{VERSION}；滚动母表字段级合并。"
    ]]
    if innovation:
        share_latest = innovation.get("share_latest_date")
        turnover_latest = innovation.get("turnover_latest_date")
        sh.get_range("A14:F16").values = [
            ["创新药成交额", f"最新{share_latest}", "字段级滚动来源", "独立07页，不并入05", "已更新", "当前/历史来源可不同，非空历史不被覆盖"],
            ["创新药成交占比", f"最新{share_latest}", "创新药成交额 + 02同日全A成交额", "成交额/全部A股成交额", "已更新", "同日分母缺失则留空；可数学恢复时补算"],
            ["创新药换手率", f"最新可靠{turnover_latest}", "供应商直接板块换手率", "禁止代理/倒算", "已更新" if innovation.get("target_turnover_available") else "当日待可靠源", "历史可靠值必须保留"],
        ]
        sh.get_range("A30:F34").values = [
            ["板块口径", "创新药主题", "东方财富概念板块为可靠换手率主源", "独立07页", "执行中", "字段级滚动合并"],
            ["成交额占比", "创新药成交额/全部A股成交额", "同日成交额 + 02分母", "缺分母留空", "已实现", f"最新{share_latest}"],
            ["换手率", "仅供应商直接板块换手率", "东方财富概念板块", "不得代理/倒算", "已实现", f"最新可靠{turnover_latest}"],
            ["20日成交量活跃度代理", "停用", "—", "不进入表格/图表/生产规则", "已剔除", "不得替代换手率"],
            ["图表", "成交额占比 + 可靠换手率", "07/00", "原图表对象仅更新series", "已实现", "横轴可能抽样显示，标题明确最新日期"],
        ]


def validate_v15(wb, payload: dict, innovation, matrix: dict, before_structure: dict, extra: dict) -> dict:
    result = ORIGINAL_VALIDATE(wb, payload, innovation, matrix, before_structure, extra)
    warnings = list(result.get("warnings") or [])
    if innovation and not innovation.get("target_turnover_available"):
        warnings.append("07_target_turnover_waiting_reliable_source")
    result["renderer_version"] = VERSION
    result["warnings"] = warnings
    result["status"] = "FAIL" if result.get("failures") else ("WARN" if warnings else "PASS")
    return result


def render(mother: Path, bundle: Path, output: Path, config: Path) -> dict:
    # Patch v1.4's generic orchestration with v1.5 field-level innovation semantics.
    v14.VERSION = VERSION
    core.VERSION = VERSION
    core.update_07 = update_07_rolling
    v14.sync_00 = sync_00_v15
    v14.update_99 = update_99_v15
    v14.validate = validate_v15
    return v14.render(mother, bundle, output, config)


def main() -> None:
    parser = argparse.ArgumentParser(description="A股每日市场监控 Renderer v1.5")
    parser.add_argument("--template", required=True, help="上一份正式验证工作簿（滚动母表）")
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/excel_renderer.json")
    args = parser.parse_args()
    print(json.dumps(
        render(Path(args.template), Path(args.bundle_dir), Path(args.output), Path(args.config)),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
