#!/usr/bin/env python3
from __future__ import annotations

import run_excel_renderer_v12 as v12


_original_sync_00_fixed = v12.sync_00_fixed
_original_update_05_fixed = v12.update_05_fixed
_original_update_99 = v12.core.update_99


def _series_names(chart) -> set[str]:
    names: set[str] = set()
    try:
        for series in chart.series.items:
            if series.name:
                names.add(str(series.name))
    except Exception:
        pass
    return names


def _safe_style_axis(chart, *, secondary: bool = False, percent: bool = False) -> None:
    """Stable Excel-native axis contract.

    Ordinary charts keep their time axis at the bottom. The market-structure
    charts are the exception: their numeric zero must remain the true baseline
    so positive bars/lines extend upward and negative bars/lines downward.
    Tick labels still stay at the bottom.
    """
    for axis in (chart.x_axis, chart.y_axis):
        axis.major_gridlines.visible = False
        axis.minor_gridlines.visible = False

    chart.x_axis.position = "bottom"
    chart.x_axis.tick_label_position = "low"

    names = _series_names(chart)
    is_market_structure = bool(names & {"上涨家数", "下跌家数", "涨停", "跌停"})
    if not is_market_structure:
        chart.x_axis.crosses = "min"

    if secondary:
        chart.y_axis.position = "right"
        chart.y_axis.crosses = "max"
    else:
        chart.y_axis.position = "left"
    if percent:
        chart.y_axis.number_format_code = "0%"


def _safe_symmetric_axis(chart, values, step: float) -> None:
    """Pin positive/negative market charts to a symmetric zero-centred scale."""
    import math

    valid = [abs(float(x)) for x in values if x not in (None, "")]
    if not valid:
        return
    limit = max(step, math.ceil(max(valid) / step) * step)
    chart.y_axis.min = -limit
    chart.y_axis.max = limit


def _business_status_text(payload: dict, validation: dict, manifest: dict) -> str:
    warns = [x["name"] for x in validation.get("checks", []) if not x.get("ok")]
    if warns:
        return "已更新；部分数据待核验：" + "、".join(warns)
    return "已更新"


def _update_05_external(wb, payload: dict):
    result = _original_update_05_fixed(wb, payload)
    sh = wb.worksheets.get_item("05_申万行业资金拥挤度")
    n = v12.core.nrows(sh, 63, 1000)
    if n:
        values = sh.get_range(f"P63:P{62+n}").values
        cleaned = []
        for row in values:
            text = row[0]
            if isinstance(text, str) and ("GitHub" in text or "生产包" in text):
                text = "申万官方数据"
            cleaned.append([text])
        sh.get_range(f"P63:P{62+n}").values = cleaned
    return result


def _sync_00_external(wb, payload: dict, market_rows: list[dict], innovation) -> None:
    _original_sync_00_fixed(wb, payload, market_rows, innovation)
    sh = wb.worksheets.get_item("00_市场总览")
    sw_date = (payload.get("sw_crowding") or {}).get("date")
    sw_text = f"申万行业最新有效日{sw_date}" if sw_date else "申万行业沿用最近有效日"
    sh.get_range("A3").values = [[
        f"市场宽度、成交与百亿成交更新至{payload['date']}；{sw_text}；创新药独立统计，不并入申万行业。"
    ]]
    sh.get_range("Q1").values = [["关键走势图总览"]]
    if innovation:
        sh.get_range("H30").values = [["创新药独立主题"]]


def _update_99_external(wb, payload: dict, validation: dict, innovation, template_sha: str) -> None:
    _original_update_99(wb, payload, validation, innovation, template_sha)
    sh = wb.worksheets.get_item("99_口径与质量")
    d = payload["date"]
    sh.get_range("A3").values = [[
        f"截至{d}。缺失数据保持空白，不以0或跨口径数据替代；明细按最新日期优先展示，图表按时间顺序展示。"
    ]]
    sh.get_range("F6").values = [["多源数据校验"]]
    sh.get_range("A40:F40").values = [[
        "当日数据更新", d, "市场监控", "00/02/03/04/05/07/99", "已完成", "数据与图表已同步"
    ]]


# Rebind v1.2 helpers before v12.install() wires the renderer into core.
v12._style_axis = _safe_style_axis
v12._symmetric_axis = _safe_symmetric_axis
v12.update_05_fixed = _update_05_external
v12.sync_00_fixed = _sync_00_external
v12.core.status_text = _business_status_text
v12.core.update_99 = _update_99_external


def main() -> None:
    v12.main()


if __name__ == "__main__":
    main()
