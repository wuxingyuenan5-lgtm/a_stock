#!/usr/bin/env python3
from __future__ import annotations

import excel_renderer_artifact as core


# Renderer v1.1 freezes the chart visual contract:
# - time axis always at the bottom
# - no major/minor gridlines
# - primary value axis on the left, overlay/secondary axis on the right
# - dashboard market-structure chart combines advance/decline bars with limit-up/down lines
# - advance/decline bars are intentionally pale so the foreground limit lines remain legible
core.VERSION = "1.1"

NAVY = "#17365D"
MARKET_UP_BAR = "#F8DDCD"      # pale warm peach
MARKET_DOWN_BAR = "#DDEED7"    # pale soft green
LIMIT_UP_LINE = "#F00000"      # strong red
LIMIT_DOWN_LINE = "#00A651"    # strong green
BLUE = "#4F81BD"
RED = "#C0504D"
CYAN = "#4BB3D3"
ORANGE = "#F28E2B"
DARK_BLUE = "#156082"


def _style_axis(chart, *, secondary: bool = False, percent: bool = False, bottom: bool = True) -> None:
    """Apply the frozen axis/grid contract to one chart layer."""
    for axis in (chart.x_axis, chart.y_axis):
        axis.major_gridlines.visible = False
        axis.minor_gridlines.visible = False
    if bottom:
        chart.x_axis.position = "bottom"
        chart.x_axis.tick_label_position = "low"
        chart.x_axis.crosses = "min"
    if secondary:
        chart.y_axis.position = "right"
        chart.y_axis.crosses = "max"
    else:
        chart.y_axis.position = "left"
    if percent:
        chart.y_axis.number_format_code = "0%"


def _add_secondary_line(
    sheet,
    categories,
    series_defs,
    start: str,
    end: str,
    *,
    percent: bool = False,
    legend_position: str = "top",
):
    """Overlay a transparent line chart whose value axis is forced to the right."""
    chart = sheet.charts.add(
        "line",
        {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 760, "heightPx": 320}},
    )
    chart.categories = categories
    for name, values, color, width in series_defs:
        series = chart.series.add(name)
        series.categories = categories
        series.values = values
        series.line = {"color": color, "width": width}
    chart.title_text = ""
    chart.has_legend = True
    chart.legend.position = legend_position
    _style_axis(chart, secondary=True, percent=percent, bottom=True)
    chart.chart_fill = {"type": "none"}
    chart.plot_area_fill = {"type": "none"}
    chart.set_position(start, end)
    # Keep one visible time axis only; the base chart owns the bottom labels.
    try:
        chart.x_axis.deleted = True
    except Exception:
        pass
    return chart


def _rebuild_03_charts(wb, rows: list[dict]) -> None:
    """Rebuild the dedicated market-breadth sheet with the frozen visual style."""
    sh = wb.worksheets.get_item("03_市场宽度图")
    sh.delete_all_drawings()
    cats = [core.as_date(x["date"]).strftime("%m-%d") for x in rows]
    up = [x["up"] for x in rows]
    down = [-x["down"] if x["down"] is not None else None for x in rows]
    limit_up = [x["lu"] for x in rows]
    limit_down = [-x["ld"] if x["ld"] is not None else None for x in rows]
    width = [x["width"] for x in rows]

    c1 = sh.charts.add(
        "bar", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 350}}
    )
    c1.categories = cats
    s = c1.series.add("上涨家数")
    s.categories, s.values = cats, up
    s.fill, s.line = DARK_BLUE, {"color": DARK_BLUE, "width": 0.5}
    s = c1.series.add("下跌绘图值")
    s.categories, s.values = cats, down
    s.fill, s.line = ORANGE, {"color": ORANGE, "width": 0.5}
    c1.title_text = "上涨与下跌家数"
    c1.has_legend = True
    c1.legend.position = "bottom"
    c1.bar_options.direction = "column"
    c1.bar_options.grouping = "clustered"
    c1.bar_options.gap_width = 30
    c1.x_axis.tick_label_interval = 10
    _style_axis(c1)
    c1.set_position("A5", "O24")

    c2 = sh.charts.add(
        "line", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 350}}
    )
    c2.categories = cats
    s = c2.series.add("涨停家数")
    s.categories, s.values = cats, limit_up
    s.line = {"color": DARK_BLUE, "width": 2.1}
    s = c2.series.add("跌停绘图值")
    s.categories, s.values = cats, limit_down
    s.line = {"color": ORANGE, "width": 2.1}
    c2.title_text = "涨停与跌停家数"
    c2.has_legend = True
    c2.legend.position = "bottom"
    c2.x_axis.tick_label_interval = 10
    _style_axis(c2)
    c2.set_position("A26", "O45")

    c3 = sh.charts.add(
        "line", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 350}}
    )
    c3.categories = cats
    s = c3.series.add("市场宽度")
    s.categories, s.values = cats, width
    s.line = {"color": DARK_BLUE, "width": 2.2}
    c3.title_text = f"市场宽度｜至{core.as_date(rows[-1]['date']).isoformat()}"
    c3.has_legend = False
    c3.x_axis.tick_label_interval = 10
    _style_axis(c3, percent=True)
    c3.set_position("A47", "O66")


def _rebuild_05_charts(wb) -> None:
    """Rebuild Shenwan charts with explicit left/right axes and no gridlines."""
    sh = wb.worksheets.get_item("05_申万行业资金拥挤度")
    n = core.nrows(sh, 63, 1000)
    rows = sh.get_range(f"A63:P{62+n}").values if n else []
    asc = sorted(rows, key=lambda r: r[0] or 0)
    sh.delete_all_drawings()

    share_rows = [r for r in asc if r[3] not in (None, "")]
    turn_rows = [r for r in asc if r[2] not in (None, "")]
    share_cats = [core.as_date(r[0]).strftime("%m-%d") for r in share_rows]
    area = sh.charts.add(
        "area", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 360}}
    )
    area.categories = share_cats
    s = area.series.add("通信设备成交额占全A")
    s.categories, s.values = share_cats, [r[3] for r in share_rows]
    s.fill, s.line = BLUE, {"color": BLUE, "width": 1}
    area.title_text = "通信设备｜成交额占比与换手率"
    area.has_legend = False
    area.x_axis.tick_label_interval = 10
    _style_axis(area, percent=True)
    area.set_position("A5", "P29")
    _add_secondary_line(
        sh,
        [core.as_date(r[0]).strftime("%m-%d") for r in turn_rows],
        [("通信设备换手率", [r[2] for r in turn_rows], RED, 2.5)],
        "A5",
        "P29",
        percent=True,
    )

    four_rows = [r for r in asc if r[13] not in (None, "") and r[14] not in (None, "")]
    four_cats = [core.as_date(r[0]).strftime("%m-%d") for r in four_rows]
    bar = sh.charts.add(
        "bar", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 360}}
    )
    bar.categories = four_cats
    s = bar.series.add("申万四行业成交额合计")
    s.categories, s.values = four_cats, [r[13] for r in four_rows]
    s.fill, s.line = CYAN, {"color": CYAN, "width": 0.5}
    bar.title_text = "通信设备 + 计算机设备 + 元件 + 半导体｜成交额与成交额占比"
    bar.has_legend = False
    bar.bar_options.direction = "column"
    bar.bar_options.grouping = "clustered"
    bar.x_axis.tick_label_interval = 10
    _style_axis(bar)
    bar.set_position("A31", "P57")
    _add_secondary_line(
        sh,
        four_cats,
        [("申万四行业成交额占全A", [r[14] for r in four_rows], ORANGE, 2.5)],
        "A31",
        "P57",
        percent=True,
    )


def _rebuild_07_charts(wb, innovation) -> None:
    if not innovation:
        return
    sh = wb.worksheets.get_item("07_创新药交易拥挤度")
    rows = sorted(innovation["rows"], key=lambda r: r["date"])
    sh.delete_all_drawings()

    share_rows = [r for r in rows if r["share"] is not None]
    share_cats = [r["date"][5:] for r in share_rows]
    area = sh.charts.add(
        "area", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 760, "heightPx": 340}}
    )
    area.categories = share_cats
    s = area.series.add("创新药成交额占全A")
    s.categories, s.values = share_cats, [r["share"] for r in share_rows]
    s.fill, s.line = BLUE, {"color": BLUE, "width": 1}
    area.has_legend = False
    area.x_axis.tick_label_interval = 10
    _style_axis(area, percent=True)
    area.set_position("A5", "H28")

    if innovation["has_turnover"]:
        line_rows = [r for r in rows if r["turnover"] is not None]
        area.title_text = "创新药｜成交额占全A与换手率"
        name, vals, percent = "创新药换手率", [r["turnover"] for r in line_rows], True
    else:
        line_rows = [r for r in rows if r["activity"] is not None]
        area.title_text = "创新药｜成交额占全A与20日成交量活跃度代理（非官方换手率）"
        name, vals, percent = "20日成交量活跃度代理", [r["activity"] for r in line_rows], False
    _add_secondary_line(
        sh,
        [r["date"][5:] for r in line_rows],
        [(name, vals, RED, 2.5)],
        "A5",
        "H28",
        percent=percent,
    )


def _rebuild_00_charts(wb, payload: dict, market_rows: list[dict], innovation) -> None:
    """Build the fixed dashboard chart stack, including the combined market-structure chart."""
    sh = wb.worksheets.get_item("00_市场总览")
    sh.delete_all_drawings()
    asc = sorted(market_rows, key=lambda x: x["date"])
    cats = [core.as_date(x["date"]).strftime("%m-%d") for x in asc]

    # 1) Combined market structure chart, patterned after the approved reference:
    #    pale bars in the background, strong lines in the foreground, shared zero line.
    bars = sh.charts.add(
        "bar", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 360}}
    )
    bars.categories = cats
    s = bars.series.add("上涨家数")
    s.categories, s.values = cats, [x["up"] for x in asc]
    s.fill, s.line = MARKET_UP_BAR, {"color": MARKET_UP_BAR, "width": 0.25}
    s = bars.series.add("下跌家数")
    s.categories, s.values = cats, [-x["down"] if x["down"] is not None else None for x in asc]
    s.fill, s.line = MARKET_DOWN_BAR, {"color": MARKET_DOWN_BAR, "width": 0.25}
    bars.title_text = "市场涨跌结构｜上涨/下跌家数 + 涨停/跌停家数"
    bars.has_legend = True
    bars.legend.position = "top"
    bars.bar_options.direction = "column"
    bars.bar_options.grouping = "clustered"
    bars.bar_options.gap_width = 20
    bars.x_axis.tick_label_interval = 12
    _style_axis(bars)
    bars.set_position("Q2", "AE20")
    _add_secondary_line(
        sh,
        cats,
        [
            ("涨停", [x["lu"] for x in asc], LIMIT_UP_LINE, 2.5),
            ("跌停", [-x["ld"] if x["ld"] is not None else None for x in asc], LIMIT_DOWN_LINE, 2.5),
        ],
        "Q2",
        "AE20",
        percent=False,
        legend_position="top",
    )

    # 2) Market breadth.
    c = sh.charts.add(
        "line", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 280}}
    )
    c.categories = cats
    s = c.series.add("市场宽度")
    s.categories, s.values = cats, [x["width"] for x in asc]
    s.line = {"color": DARK_BLUE, "width": 2.2}
    c.title_text = f"市场宽度｜至{payload['date']}"
    c.has_legend = False
    c.x_axis.tick_label_interval = 12
    _style_axis(c, percent=True)
    c.set_position("Q22", "AE36")

    # 3-4) Shenwan charts use the same data/visual contract as sheet 05.
    s05 = wb.worksheets.get_item("05_申万行业资金拥挤度")
    n05 = core.nrows(s05, 63, 1000)
    r05 = sorted(s05.get_range(f"A63:P{62+n05}").values if n05 else [], key=lambda r: r[0] or 0)

    share_rows = [r for r in r05 if r[3] not in (None, "")]
    turn_rows = [r for r in r05 if r[2] not in (None, "")]
    share_cats = [core.as_date(r[0]).strftime("%m-%d") for r in share_rows]
    a = sh.charts.add(
        "area", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 300}}
    )
    a.categories = share_cats
    s = a.series.add("通信设备成交额占全A")
    s.categories, s.values = share_cats, [r[3] for r in share_rows]
    s.fill, s.line = BLUE, {"color": BLUE, "width": 1}
    a.title_text = "通信设备｜成交额占比与换手率"
    a.has_legend = False
    a.x_axis.tick_label_interval = 10
    _style_axis(a, percent=True)
    a.set_position("Q38", "AE54")
    _add_secondary_line(
        sh,
        [core.as_date(r[0]).strftime("%m-%d") for r in turn_rows],
        [("通信设备换手率", [r[2] for r in turn_rows], RED, 2.3)],
        "Q38",
        "AE54",
        percent=True,
    )

    four_rows = [r for r in r05 if r[13] not in (None, "") and r[14] not in (None, "")]
    four_cats = [core.as_date(r[0]).strftime("%m-%d") for r in four_rows]
    b = sh.charts.add(
        "bar", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 300}}
    )
    b.categories = four_cats
    s = b.series.add("申万四行业成交额合计")
    s.categories, s.values = four_cats, [r[13] for r in four_rows]
    s.fill, s.line = CYAN, {"color": CYAN, "width": 0.5}
    b.title_text = "四行业｜成交额与成交额占比"
    b.has_legend = False
    b.bar_options.direction = "column"
    b.bar_options.grouping = "clustered"
    b.x_axis.tick_label_interval = 10
    _style_axis(b)
    b.set_position("Q56", "AE72")
    _add_secondary_line(
        sh,
        four_cats,
        [("申万四行业成交额占全A", [r[14] for r in four_rows], ORANGE, 2.3)],
        "Q56",
        "AE72",
        percent=True,
    )

    # 5) Innovation drug chart, independent of Shenwan sheet 05.
    if innovation:
        ir = sorted(innovation["rows"], key=lambda r: r["date"])
        share_ir = [r for r in ir if r["share"] is not None]
        icats = [r["date"][5:] for r in share_ir]
        a2 = sh.charts.add(
            "area", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 300}}
        )
        a2.categories = icats
        s = a2.series.add("创新药成交额占全A")
        s.categories, s.values = icats, [r["share"] for r in share_ir]
        s.fill, s.line = BLUE, {"color": BLUE, "width": 1}
        a2.has_legend = False
        a2.x_axis.tick_label_interval = 10
        _style_axis(a2, percent=True)
        a2.set_position("Q74", "AE91")
        if innovation["has_turnover"]:
            line_ir = [r for r in ir if r["turnover"] is not None]
            a2.title_text = "创新药｜成交额占全A与换手率"
            line_name, line_vals, line_percent = "创新药换手率", [r["turnover"] for r in line_ir], True
        else:
            line_ir = [r for r in ir if r["activity"] is not None]
            a2.title_text = "创新药｜成交额占全A与20日成交量活跃度代理（非官方换手率）"
            line_name, line_vals, line_percent = "20日成交量活跃度代理", [r["activity"] for r in line_ir], False
        _add_secondary_line(
            sh,
            [r["date"][5:] for r in line_ir],
            [(line_name, line_vals, RED, 2.3)],
            "Q74",
            "AE91",
            percent=line_percent,
        )

    for col in ["Q","R","S","T","U","V","W","X","Y","Z","AA","AB","AC","AD","AE"]:
        sh.get_range(f"{col}:{col}").format.column_width = 10


def update_04_fixed(wb, payload: dict) -> dict:
    sh = wb.worksheets.get_item("04_百亿成交历史")
    old = core.hot_rows(wb)
    target = core.serial(payload["date"])
    prior = {str(r[2]): r for r in old if r[0] == target}
    rest = [r for r in old if r[0] != target]
    new = []
    for item in payload.get("hot_stocks", []):
        code = str(item.get("stock_code") or "")
        sw1 = item.get("sw_level1") or "未匹配"
        sw2 = item.get("sw_level2") or "未匹配"
        state = "已匹配" if sw1 != "未匹配" and sw2 != "未匹配" else "待申万映射"
        if (sw1 == "未匹配" or sw2 == "未匹配") and code in prior:
            p = prior[code]
            if p[7] not in (None, "未匹配") and p[8] not in (None, "未匹配"):
                sw1, sw2, state = p[7], p[8], p[9]
        new.append([
            target, item.get("rank"), code, item.get("stock_name"), item.get("close"),
            item.get("return"), item.get("amount_100m"), sw1, sw2, state,
        ])

    rows = new + rest
    rows.sort(key=lambda r: (-int(r[0]), int(r[1] or 9999)))
    core.grow_style(sh, 23, len(old), len(rows), "J")
    if rows:
        sh.get_range(f"A23:J{22 + len(rows)}").values = rows
    core.clear_tail(sh, 23, len(old), len(rows), "J", 10)

    dates = []
    for r in rows:
        if r[0] not in dates:
            dates.append(r[0])
        if len(dates) == 6:
            break
    recent = set(dates)
    counts: dict[str, dict[int, int]] = {}
    cumulative: dict[str, int] = {}
    for r in rows:
        ind = r[8] if r[8] not in (None, "", "未匹配") else "待申万映射"
        cumulative[ind] = cumulative.get(ind, 0) + 1
        if r[0] in recent:
            counts.setdefault(ind, {d: 0 for d in dates})
            counts[ind][r[0]] += 1

    existing_order = [str(x[0]) for x in sh.get_range("A6:A19").values if x[0] and x[0] != "其他行业汇总"]
    industries = list(counts)
    industries.sort(key=lambda x: (
        existing_order.index(x) if x in existing_order else 999,
        -cumulative.get(x, 0),
        x,
    ))
    source_unique = len(industries)

    if source_unique <= 14:
        display = industries
        display_counts = counts
        display_cumulative = cumulative
    else:
        keep = sorted(industries, key=lambda x: (-cumulative.get(x, 0), x))[:13]
        overflow = [x for x in industries if x not in keep]
        display = keep + ["其他行业汇总"]
        display_counts = {x: counts[x] for x in keep}
        display_counts["其他行业汇总"] = {
            d: sum(counts[x].get(d, 0) for x in overflow) for d in dates
        }
        display_cumulative = {x: cumulative[x] for x in keep}
        display_cumulative["其他行业汇总"] = sum(cumulative[x] for x in overflow)

    sh.get_range("A6:H19").values = [[None] * 8 for _ in range(14)]
    sh.get_range("B5:G5").values = [dates + [None] * (6 - len(dates))]
    matrix = [
        [ind]
        + [display_counts[ind].get(d, 0) for d in dates]
        + [0] * (6 - len(dates))
        + [display_cumulative.get(ind, 0)]
        for ind in display
    ]
    if matrix:
        sh.get_range(f"A6:H{5 + len(matrix)}").values = matrix
    sh.get_range("A21").values = [[f"百亿成交个股明细｜最新{payload['date']}共{len(new)}只"]]
    return {
        "target_rows": len(new),
        "target_matrix_sum": sum(display_counts[ind].get(target, 0) for ind in display),
        "recent_unique_industries": len(display),
        "source_unique_industries": source_unique,
        "matrix_capacity": 14,
        "overflow_aggregated": source_unique > 14,
    }


_original_update_03 = core.update_03
_original_update_05 = core.update_05
_original_update_07 = core.update_07
_original_sync_00 = core.sync_00


def update_03_fixed(wb):
    rows = _original_update_03(wb)
    _rebuild_03_charts(wb, rows)
    return rows


def update_05_fixed(wb, payload: dict):
    result = _original_update_05(wb, payload)
    _rebuild_05_charts(wb)
    return result


def update_07_fixed(wb, rows: list[dict], payload: dict):
    innovation = _original_update_07(wb, rows, payload)
    _rebuild_07_charts(wb, innovation)
    return innovation


def sync_00_fixed(wb, payload: dict, market_rows: list[dict], innovation) -> None:
    _original_sync_00(wb, payload, market_rows, innovation)
    sh = wb.worksheets.get_item("00_市场总览")
    sh.get_range("C30:D30").format.number_format = "0.00%"
    sh.get_range("E30").format.number_format = "0.00x"
    sh.get_range("F30").format.number_format = "0.00%"
    sh.get_range("H30").format.wrap_text = True
    _rebuild_00_charts(wb, payload, market_rows, innovation)


core.update_03 = update_03_fixed
core.update_04 = update_04_fixed
core.update_05 = update_05_fixed
core.update_07 = update_07_fixed
core.sync_00 = sync_00_fixed


if __name__ == "__main__":
    core.main()
