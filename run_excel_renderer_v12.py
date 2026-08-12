#!/usr/bin/env python3
from __future__ import annotations

import math

import excel_renderer_artifact as core

core.VERSION = "1.2"

NAVY = "#17365D"
DARK = "#1F1F1F"
AXIS = "#7F7F7F"
BLUE = "#4F81BD"
RED = "#C0504D"
CYAN = "#4BB3D3"
ORANGE = "#F28E2B"
DARK_BLUE = "#156082"
MARKET_UP_BAR = "#F8DDCD"
MARKET_DOWN_BAR = "#DDEED7"
LIMIT_UP_LINE = "#F00000"
LIMIT_DOWN_LINE = "#00A651"

_original_update_03 = core.update_03
_original_update_05 = core.update_05
_original_update_07 = core.update_07
_original_sync_00 = core.sync_00


def _style_axis(chart, *, secondary: bool = False, percent: bool = False) -> None:
    for axis in (chart.x_axis, chart.y_axis):
        axis.major_gridlines.visible = False
        axis.minor_gridlines.visible = False
        try:
            axis.line = {"color": AXIS, "width": 1}
        except Exception:
            pass
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


def _symmetric_axis(chart, values, step: float) -> None:
    valid = [abs(float(x)) for x in values if x not in (None, "")]
    if not valid:
        return
    limit = max(step, math.ceil(max(valid) / step) * step)
    try:
        chart.y_axis.minimum_scale = -limit
        chart.y_axis.maximum_scale = limit
    except Exception:
        pass


def _clear_merge(sheet, cell_range: str) -> None:
    try:
        sheet.unmerge_cells(cell_range)
    except Exception:
        pass


def _title_row(sheet, cell_range: str, text: str, size: int = 14) -> None:
    _clear_merge(sheet, cell_range)
    sheet.merge_cells(cell_range)
    cell = cell_range.split(":")[0]
    sheet.get_range(cell).values = [[text]]
    rng = sheet.get_range(cell_range)
    rng.format.font = {"bold": True, "size": size, "color": DARK}
    rng.format.horizontal_alignment = "center"
    rng.format.vertical_alignment = "center"
    rng.format.row_height = 24


def _legend_cell(sheet, cell_range: str, text: str, *, color: str = DARK, fill: str | None = None) -> None:
    _clear_merge(sheet, cell_range)
    sheet.merge_cells(cell_range)
    cell = cell_range.split(":")[0]
    sheet.get_range(cell).values = [[text]]
    rng = sheet.get_range(cell_range)
    rng.format.font = {"bold": True, "size": 10, "color": color}
    rng.format.horizontal_alignment = "center"
    rng.format.vertical_alignment = "center"
    if fill:
        rng.format.fill = fill


def _secondary_line(sheet, categories, defs, start: str, end: str, *, percent: bool = False, symmetric_step: float | None = None):
    chart = sheet.charts.add("line", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 760, "heightPx": 320}})
    chart.categories = categories
    all_values = []
    for name, values, color, width in defs:
        s = chart.series.add(name)
        s.categories = categories
        s.values = values
        s.line = {"color": color, "width": width}
        all_values.extend(values)
    chart.title_text = ""
    chart.has_legend = False
    _style_axis(chart, secondary=True, percent=percent)
    if symmetric_step:
        _symmetric_axis(chart, all_values, symmetric_step)
    chart.chart_fill = {"type": "none"}
    chart.plot_area_fill = {"type": "none"}
    chart.set_position(start, end)
    try:
        chart.x_axis.deleted = True
    except Exception:
        pass
    return chart


def _rebuild_03_charts(wb, rows: list[dict]) -> None:
    sh = wb.worksheets.get_item("03_市场宽度图")
    sh.delete_all_drawings()
    cats = [core.as_date(x["date"]).strftime("%m-%d") for x in rows]
    up = [x["up"] for x in rows]
    down = [-x["down"] if x["down"] is not None else None for x in rows]
    lu = [x["lu"] for x in rows]
    ld = [-x["ld"] if x["ld"] is not None else None for x in rows]
    width = [x["width"] for x in rows]

    c1 = sh.charts.add("bar", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 350}})
    c1.categories = cats
    s = c1.series.add("上涨家数"); s.categories, s.values = cats, up; s.fill, s.line = MARKET_UP_BAR, {"color": MARKET_UP_BAR, "width": 0.25}
    s = c1.series.add("下跌家数"); s.categories, s.values = cats, down; s.fill, s.line = MARKET_DOWN_BAR, {"color": MARKET_DOWN_BAR, "width": 0.25}
    c1.title_text = "上涨与下跌家数｜上涨为正、下跌为负"
    c1.has_legend = True; c1.legend.position = "top"
    c1.bar_options.direction = "column"; c1.bar_options.grouping = "clustered"; c1.bar_options.gap_width = 20
    c1.x_axis.tick_label_interval = 10
    _style_axis(c1); _symmetric_axis(c1, up + down, 500)
    c1.set_position("A5", "O24")

    c2 = sh.charts.add("line", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 350}})
    c2.categories = cats
    s = c2.series.add("涨停"); s.categories, s.values = cats, lu; s.line = {"color": LIMIT_UP_LINE, "width": 2.3}
    s = c2.series.add("跌停"); s.categories, s.values = cats, ld; s.line = {"color": LIMIT_DOWN_LINE, "width": 2.3}
    c2.title_text = "涨停与跌停｜涨停为正、跌停为负"
    c2.has_legend = True; c2.legend.position = "top"; c2.x_axis.tick_label_interval = 10
    _style_axis(c2); _symmetric_axis(c2, lu + ld, 50)
    c2.set_position("A26", "O45")

    c3 = sh.charts.add("line", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 350}})
    c3.categories = cats
    s = c3.series.add("市场宽度"); s.categories, s.values = cats, width; s.line = {"color": DARK_BLUE, "width": 2.2}
    c3.title_text = f"市场宽度｜至{core.as_date(rows[-1]['date']).isoformat()}"
    c3.has_legend = False; c3.x_axis.tick_label_interval = 10
    _style_axis(c3, percent=True)
    c3.set_position("A47", "O66")


def _rebuild_05_charts(wb) -> None:
    sh = wb.worksheets.get_item("05_申万行业资金拥挤度")
    n = core.nrows(sh, 63, 1000)
    rows = sorted(sh.get_range(f"A63:P{62+n}").values if n else [], key=lambda r: r[0] or 0)
    sh.delete_all_drawings()

    share_rows = [r for r in rows if r[3] not in (None, "")]
    turn_rows = [r for r in rows if r[2] not in (None, "")]
    share_cats = [core.as_date(r[0]).strftime("%m-%d") for r in share_rows]
    _title_row(sh, "A4:P4", "通信设备｜成交额占全A与换手率")
    _legend_cell(sh, "A5:H5", "■ 通信设备成交额占全A（左轴）", color=DARK, fill="#D9E7F5")
    _legend_cell(sh, "I5:P5", "━ 通信设备换手率（右轴）", color=RED)
    area = sh.charts.add("area", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 350}})
    area.categories = share_cats
    s = area.series.add("通信设备成交额占全A"); s.categories, s.values = share_cats, [r[3] for r in share_rows]; s.fill, s.line = BLUE, {"color": BLUE, "width": 1}
    area.title_text = ""; area.has_legend = False; area.x_axis.tick_label_interval = 10
    _style_axis(area, percent=True); area.set_position("A6", "P29")
    _secondary_line(sh, [core.as_date(r[0]).strftime("%m-%d") for r in turn_rows], [("通信设备换手率", [r[2] for r in turn_rows], RED, 2.5)], "A6", "P29", percent=True)

    four_rows = [r for r in rows if r[13] not in (None, "") and r[14] not in (None, "")]
    four_cats = [core.as_date(r[0]).strftime("%m-%d") for r in four_rows]
    _title_row(sh, "A31:P31", "通信设备 + 计算机设备 + 元件 + 半导体｜成交额与成交额占比")
    _legend_cell(sh, "A32:H32", "■ 四行业成交额合计（亿元，左轴）", color=DARK, fill="#DDF3F8")
    _legend_cell(sh, "I32:P32", "━ 四行业成交额占全A（右轴）", color=ORANGE)
    bar = sh.charts.add("bar", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 350}})
    bar.categories = four_cats
    s = bar.series.add("四行业成交额合计"); s.categories, s.values = four_cats, [r[13] for r in four_rows]; s.fill, s.line = CYAN, {"color": CYAN, "width": 0.5}
    bar.title_text = ""; bar.has_legend = False; bar.bar_options.direction = "column"; bar.bar_options.grouping = "clustered"; bar.x_axis.tick_label_interval = 10
    _style_axis(bar); bar.set_position("A33", "P57")
    _secondary_line(sh, four_cats, [("四行业成交额占全A", [r[14] for r in four_rows], ORANGE, 2.5)], "A33", "P57", percent=True)


def _rebuild_07_charts(wb, innovation) -> None:
    if not innovation:
        return
    sh = wb.worksheets.get_item("07_创新药交易拥挤度")
    rows = sorted(innovation["rows"], key=lambda r: r["date"])
    sh.delete_all_drawings()
    share_rows = [r for r in rows if r["share"] is not None]
    share_cats = [r["date"][5:] for r in share_rows]
    _title_row(sh, "A4:H4", "创新药｜成交额占全A与换手率")
    _legend_cell(sh, "A5:D5", "■ 创新药成交额占全A（左轴）", color=DARK, fill="#D9E7F5")
    line_name = "创新药换手率（右轴）" if innovation["has_turnover"] else "20日成交量活跃度代理（右轴）"
    _legend_cell(sh, "E5:H5", f"━ {line_name}", color=RED)
    area = sh.charts.add("area", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 760, "heightPx": 330}})
    area.categories = share_cats
    s = area.series.add("创新药成交额占全A"); s.categories, s.values = share_cats, [r["share"] for r in share_rows]; s.fill, s.line = BLUE, {"color": BLUE, "width": 1}
    area.title_text = ""; area.has_legend = False; area.x_axis.tick_label_interval = 10
    _style_axis(area, percent=True); area.set_position("A6", "H28")
    if innovation["has_turnover"]:
        line_rows = [r for r in rows if r["turnover"] is not None]
        vals, percent = [r["turnover"] for r in line_rows], True
    else:
        line_rows = [r for r in rows if r["activity"] is not None]
        vals, percent = [r["activity"] for r in line_rows], False
    _secondary_line(sh, [r["date"][5:] for r in line_rows], [(line_name, vals, RED, 2.5)], "A6", "H28", percent=percent)


def _format_dashboard(sh) -> None:
    body = sh.get_range("A1:O40")
    body.format.horizontal_alignment = "center"
    body.format.vertical_alignment = "center"
    body.format.wrap_text = True

    sh.get_range("A1:O1").format.font = {"bold": True, "size": 19, "color": "#FFFFFF"}
    sh.get_range("A3:O3").format.font = {"size": 12, "color": "#44546A"}
    sh.get_range("A5:O5").format.font = {"bold": True, "size": 12, "color": DARK}
    sh.get_range("A6:O6").format.font = {"bold": True, "size": 14, "color": DARK}
    for row in (8, 15, 24, 28, 32):
        sh.get_range(f"A{row}:O{row}").format.font = {"bold": True, "size": 13, "color": "#FFFFFF"}
        sh.get_range(f"{row}:{row}").format.row_height = 28
    for row in (9, 16, 25, 29, 33):
        sh.get_range(f"A{row}:O{row}").format.font = {"bold": True, "size": 12, "color": DARK}
        sh.get_range(f"{row}:{row}").format.row_height = 32
    for rng in ("A10:O14", "A17:O23", "A26:O26", "A30:O30", "A34:O38"):
        sh.get_range(rng).format.font = {"size": 12, "color": DARK}
    for row in list(range(10, 15)) + list(range(17, 24)) + [26, 30] + list(range(34, 39)):
        sh.get_range(f"{row}:{row}").format.row_height = 28
    sh.get_range("O10:O38").format.wrap_text = True


def _rebuild_00_charts(wb, payload: dict, market_rows: list[dict], innovation) -> None:
    sh = wb.worksheets.get_item("00_市场总览")
    sh.delete_all_drawings()
    asc = sorted(market_rows, key=lambda x: x["date"])
    cats = [core.as_date(x["date"]).strftime("%m-%d") for x in asc]

    _title_row(sh, "Q2:AE2", "市场涨跌结构｜上涨/下跌家数 + 涨停/跌停家数")
    _legend_cell(sh, "Q3:T3", "■ 上涨家数（左轴，正值）", fill=MARKET_UP_BAR)
    _legend_cell(sh, "U3:X3", "■ 下跌家数（左轴，负值）", fill=MARKET_DOWN_BAR)
    _legend_cell(sh, "Y3:AB3", "━ 涨停（右轴，正值）", color=LIMIT_UP_LINE)
    _legend_cell(sh, "AC3:AE3", "━ 跌停（右轴，负值）", color=LIMIT_DOWN_LINE)
    bars = sh.charts.add("bar", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 360}})
    bars.categories = cats
    up = [x["up"] for x in asc]
    down = [-x["down"] if x["down"] is not None else None for x in asc]
    lu = [x["lu"] for x in asc]
    ld = [-x["ld"] if x["ld"] is not None else None for x in asc]
    s = bars.series.add("上涨家数"); s.categories, s.values = cats, up; s.fill, s.line = MARKET_UP_BAR, {"color": MARKET_UP_BAR, "width": 0.25}
    s = bars.series.add("下跌家数"); s.categories, s.values = cats, down; s.fill, s.line = MARKET_DOWN_BAR, {"color": MARKET_DOWN_BAR, "width": 0.25}
    bars.title_text = ""; bars.has_legend = False; bars.bar_options.direction = "column"; bars.bar_options.grouping = "clustered"; bars.bar_options.gap_width = 20; bars.x_axis.tick_label_interval = 12
    _style_axis(bars); _symmetric_axis(bars, up + down, 500); bars.set_position("Q4", "AE21")
    _secondary_line(sh, cats, [("涨停", lu, LIMIT_UP_LINE, 2.5), ("跌停", ld, LIMIT_DOWN_LINE, 2.5)], "Q4", "AE21", symmetric_step=50)

    _title_row(sh, "Q23:AE23", f"市场宽度｜至{payload['date']}")
    _legend_cell(sh, "Q24:AE24", "━ 市场宽度（左轴）", color=DARK_BLUE)
    c = sh.charts.add("line", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 280}})
    c.categories = cats
    s = c.series.add("市场宽度"); s.categories, s.values = cats, [x["width"] for x in asc]; s.line = {"color": DARK_BLUE, "width": 2.2}
    c.title_text = ""; c.has_legend = False; c.x_axis.tick_label_interval = 12
    _style_axis(c, percent=True); c.set_position("Q25", "AE38")

    s05 = wb.worksheets.get_item("05_申万行业资金拥挤度")
    n05 = core.nrows(s05, 63, 1000)
    r05 = sorted(s05.get_range(f"A63:P{62+n05}").values if n05 else [], key=lambda r: r[0] or 0)
    share_rows = [r for r in r05 if r[3] not in (None, "")]
    turn_rows = [r for r in r05 if r[2] not in (None, "")]
    share_cats = [core.as_date(r[0]).strftime("%m-%d") for r in share_rows]

    _title_row(sh, "Q40:AE40", "通信设备｜成交额占全A与换手率")
    _legend_cell(sh, "Q41:AB41", "■ 通信设备成交额占全A（左轴）", fill="#D9E7F5")
    _legend_cell(sh, "AC41:AE41", "━ 换手率（右轴）", color=RED)
    a = sh.charts.add("area", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 300}})
    a.categories = share_cats
    s = a.series.add("通信设备成交额占全A"); s.categories, s.values = share_cats, [r[3] for r in share_rows]; s.fill, s.line = BLUE, {"color": BLUE, "width": 1}
    a.title_text = ""; a.has_legend = False; a.x_axis.tick_label_interval = 10
    _style_axis(a, percent=True); a.set_position("Q42", "AE57")
    _secondary_line(sh, [core.as_date(r[0]).strftime("%m-%d") for r in turn_rows], [("通信设备换手率", [r[2] for r in turn_rows], RED, 2.3)], "Q42", "AE57", percent=True)

    four_rows = [r for r in r05 if r[13] not in (None, "") and r[14] not in (None, "")]
    four_cats = [core.as_date(r[0]).strftime("%m-%d") for r in four_rows]
    _title_row(sh, "Q59:AE59", "四行业｜成交额与成交额占比")
    _legend_cell(sh, "Q60:AB60", "■ 四行业成交额合计（亿元，左轴）", fill="#DDF3F8")
    _legend_cell(sh, "AC60:AE60", "━ 成交额占全A（右轴）", color=ORANGE)
    b = sh.charts.add("bar", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 300}})
    b.categories = four_cats
    s = b.series.add("四行业成交额合计"); s.categories, s.values = four_cats, [r[13] for r in four_rows]; s.fill, s.line = CYAN, {"color": CYAN, "width": 0.5}
    b.title_text = ""; b.has_legend = False; b.bar_options.direction = "column"; b.bar_options.grouping = "clustered"; b.x_axis.tick_label_interval = 10
    _style_axis(b); b.set_position("Q61", "AE76")
    _secondary_line(sh, four_cats, [("四行业成交额占全A", [r[14] for r in four_rows], ORANGE, 2.3)], "Q61", "AE76", percent=True)

    if innovation:
        ir = sorted(innovation["rows"], key=lambda r: r["date"])
        share_ir = [r for r in ir if r["share"] is not None]
        icats = [r["date"][5:] for r in share_ir]
        _title_row(sh, "Q78:AE78", "创新药｜成交额占全A与换手率")
        _legend_cell(sh, "Q79:AB79", "■ 创新药成交额占全A（左轴）", fill="#D9E7F5")
        legend2 = "━ 创新药换手率（右轴）" if innovation["has_turnover"] else "━ 20日成交量活跃度代理（右轴）"
        _legend_cell(sh, "AC79:AE79", legend2, color=RED)
        a2 = sh.charts.add("area", {"from": {"row": 0, "col": 0}, "extent": {"widthPx": 900, "heightPx": 300}})
        a2.categories = icats
        s = a2.series.add("创新药成交额占全A"); s.categories, s.values = icats, [r["share"] for r in share_ir]; s.fill, s.line = BLUE, {"color": BLUE, "width": 1}
        a2.title_text = ""; a2.has_legend = False; a2.x_axis.tick_label_interval = 10
        _style_axis(a2, percent=True); a2.set_position("Q80", "AE95")
        if innovation["has_turnover"]:
            line_ir = [r for r in ir if r["turnover"] is not None]; vals = [r["turnover"] for r in line_ir]; percent = True
        else:
            line_ir = [r for r in ir if r["activity"] is not None]; vals = [r["activity"] for r in line_ir]; percent = False
        _secondary_line(sh, [r["date"][5:] for r in line_ir], [(legend2.replace("━ ", ""), vals, RED, 2.3)], "Q80", "AE95", percent=percent)

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
        new.append([target, item.get("rank"), code, item.get("stock_name"), item.get("close"), item.get("return"), item.get("amount_100m"), sw1, sw2, state])
    rows = new + rest
    rows.sort(key=lambda r: (-int(r[0]), int(r[1] or 9999)))
    core.grow_style(sh, 23, len(old), len(rows), "J")
    if rows:
        sh.get_range(f"A23:J{22+len(rows)}").values = rows
    core.clear_tail(sh, 23, len(old), len(rows), "J", 10)

    dates = []
    for r in rows:
        if r[0] not in dates:
            dates.append(r[0])
        if len(dates) == 6:
            break
    recent = set(dates)
    counts, cumulative = {}, {}
    for r in rows:
        ind = r[8] if r[8] not in (None, "", "未匹配") else "待申万映射"
        cumulative[ind] = cumulative.get(ind, 0) + 1
        if r[0] in recent:
            counts.setdefault(ind, {d: 0 for d in dates})
            counts[ind][r[0]] += 1
    industries = sorted(counts, key=lambda x: (-cumulative.get(x, 0), x))
    source_unique = len(industries)
    if source_unique <= 14:
        display = industries; display_counts = counts; display_cumulative = cumulative
    else:
        keep, overflow = industries[:13], industries[13:]
        display = keep + ["其他行业汇总"]
        display_counts = {x: counts[x] for x in keep}
        display_counts["其他行业汇总"] = {d: sum(counts[x].get(d, 0) for x in overflow) for d in dates}
        display_cumulative = {x: cumulative[x] for x in keep}
        display_cumulative["其他行业汇总"] = sum(cumulative[x] for x in overflow)
    sh.get_range("A6:H19").values = [[None] * 8 for _ in range(14)]
    sh.get_range("B5:G5").values = [dates + [None] * (6-len(dates))]
    matrix = [[ind] + [display_counts[ind].get(d, 0) for d in dates] + [0] * (6-len(dates)) + [display_cumulative.get(ind, 0)] for ind in display]
    if matrix:
        sh.get_range(f"A6:H{5+len(matrix)}").values = matrix
    sh.get_range("A21").values = [[f"百亿成交个股明细｜最新{payload['date']}共{len(new)}只"]]
    return {"target_rows": len(new), "target_matrix_sum": sum(display_counts[ind].get(target, 0) for ind in display), "recent_unique_industries": len(display), "source_unique_industries": source_unique, "matrix_capacity": 14, "overflow_aggregated": source_unique > 14}


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
    _format_dashboard(sh)
    _rebuild_00_charts(wb, payload, market_rows, innovation)


def install() -> None:
    core.update_03 = update_03_fixed
    core.update_04 = update_04_fixed
    core.update_05 = update_05_fixed
    core.update_07 = update_07_fixed
    core.sync_00 = sync_00_fixed


def main() -> None:
    install()
    core.main()


if __name__ == "__main__":
    main()
