#!/usr/bin/env python3
from __future__ import annotations

import argparse
from html import escape
import json
import math
from pathlib import Path

UP = "#ef4444"
DOWN = "#10b981"
NAVY = "#123d68"
BLUE = "#2563eb"
ORANGE = "#f97316"
GRID = "#e2e8f0"


def _num(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value, digits=2):
    n = _num(value)
    return "—" if n is None else f"{n:,.{digits}f}"


def _pct(value, digits=2, signed=True):
    n = _num(value)
    if n is None:
        return "—"
    return f"{n * 100:+.{digits}f}%" if signed else f"{n * 100:.{digits}f}%"


def _cls(value):
    n = _num(value)
    if n is None or abs(n) < 1e-15:
        return "neutral"
    return "up" if n > 0 else "down"


def _table(headers, rows, row_attr="", classes=""):
    head = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body = []
    attr = f" {row_attr}" if row_attr else ""
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr{attr}>{cells}</tr>")
    return f'<div class="table-wrap {classes}"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _nice_ticks(max_abs, count=4):
    if not max_abs:
        return [0]
    raw = max_abs / count
    power = 10 ** math.floor(math.log10(raw))
    scaled = raw / power
    step = (1 if scaled <= 1 else 2 if scaled <= 2 else 5 if scaled <= 5 else 10) * power
    top = math.ceil(max_abs / step) * step
    return [i * step for i in range(-int(top / step), int(top / step) + 1)]


def _svg_market_structure(rows):
    rows = [r for r in rows if r.get("date")]
    if not rows:
        return '<div class="empty">暂无市场结构历史</div>'
    w, h = 1200, 430
    ml, mr, mt, mb = 70, 92, 24, 50
    x0, x1, y0, y1 = ml, w - mr, mt, h - mb
    zero_y = (y0 + y1) / 2
    left_max = max([abs(_num(r.get("advance")) or 0) for r in rows] + [abs(_num(r.get("decline")) or 0) for r in rows] + [1]) * 1.08
    right_max = max([abs(_num(r.get("limit_up")) or 0) for r in rows] + [abs(_num(r.get("limit_down")) or 0) for r in rows] + [1]) * 1.12
    inner_l, inner_r = x0 + 10, x1 - 24
    xs = [inner_l + (inner_r - inner_l) * i / max(1, len(rows) - 1) for i in range(len(rows))]
    bar_w = max(1.2, min(7.0, (inner_r - inner_l) / max(1, len(rows)) * 0.65))

    def yl(v):
        return zero_y - float(v) / left_max * ((y1 - y0) / 2 * .92)

    def yr(v):
        return zero_y - float(v) / right_max * ((y1 - y0) / 2 * .92)

    parts = [f'<svg class="chart-svg" viewBox="0 0 {w} {h}" role="img" aria-label="市场涨跌结构">']
    for tick in _nice_ticks(left_max):
        if abs(tick) > left_max:
            continue
        yy = yl(tick)
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{x0-9}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{int(tick):,}</text>')
    parts.append(f'<line x1="{x0}" y1="{zero_y:.1f}" x2="{x1}" y2="{zero_y:.1f}" stroke="#94a3b8" stroke-width="1.2"/>')
    for frac in (-1, -.5, 0, .5, 1):
        yy = zero_y - frac * ((y1 - y0) / 2 * .92)
        parts.append(f'<text x="{x1+13}" y="{yy+4:.1f}" text-anchor="start" class="axis-label">{int(round(frac*right_max))}</text>')

    limit_up_points, limit_down_points = [], []
    for i, row in enumerate(rows):
        x = xs[i]
        d = escape(str(row["date"]))
        advance, decline = _num(row.get("advance")), _num(row.get("decline"))
        lu, ld = _num(row.get("limit_up")), _num(row.get("limit_down"))
        if advance is not None:
            yy = yl(advance)
            parts.append(f'<rect x="{x-bar_w/2:.1f}" y="{yy:.1f}" width="{bar_w:.1f}" height="{zero_y-yy:.1f}" fill="{UP}" opacity=".23"><title>{d} 上涨 {int(advance)} 家</title></rect>')
        if decline is not None:
            yy = yl(-decline)
            parts.append(f'<rect x="{x-bar_w/2:.1f}" y="{zero_y:.1f}" width="{bar_w:.1f}" height="{yy-zero_y:.1f}" fill="{DOWN}" opacity=".23"><title>{d} 下跌 {int(decline)} 家</title></rect>')
        if lu is not None:
            limit_up_points.append((x, yr(lu), d, lu))
        if ld is not None:
            limit_down_points.append((x, yr(-ld), d, ld))
    for points, color, label in ((limit_up_points, UP, "涨停"), (limit_down_points, DOWN, "跌停")):
        if not points:
            continue
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in points)
        parts.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.3" stroke-linejoin="round"/>')
        for x, y, d, value in points:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.1" fill="{color}"><title>{d} {label} {int(value)} 家</title></circle>')
    label_count = min(10, len(rows))
    indexes = sorted(set(round(i * (len(rows)-1) / max(1, label_count-1)) for i in range(label_count)))
    for idx in indexes:
        anchor = "start" if idx == 0 else "end" if idx == len(rows)-1 else "middle"
        parts.append(f'<text x="{xs[idx]:.1f}" y="{h-17}" text-anchor="{anchor}" class="axis-label">{escape(rows[idx]["date"][5:])}</text>')
    last = rows[-1]
    parts.append(f'<g data-chart-date="{escape(last["date"])}" data-advance="{last.get("advance")}" data-decline="{last.get("decline")}" data-limit-up="{last.get("limit_up")}" data-limit-down="{last.get("limit_down")}"></g>')
    parts.append('</svg>')
    return "".join(parts)


def _svg_line(rows, field, title, percent=False, zero=True, color=BLUE):
    valid = [(r["date"], _num(r.get(field))) for r in rows if r.get("date") and _num(r.get(field)) is not None]
    if not valid:
        return '<div class="empty">暂无历史数据</div>'
    w, h, ml, mr, mt, mb = 1200, 300, 64, 52, 22, 44
    x0, x1, y0, y1 = ml, w-mr, mt, h-mb
    values = [v for _, v in valid]
    lo, hi = min(values), max(values)
    if zero:
        lo, hi = min(lo, 0), max(hi, 0)
    span = max(hi-lo, 1e-9)
    lo, hi = lo-span*.1, hi+span*.1
    xs = [x0+9+(x1-x0-28)*i/max(1, len(valid)-1) for i in range(len(valid))]
    y = lambda v: y1-(v-lo)/(hi-lo)*(y1-y0)
    parts = [f'<svg class="chart-svg" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">']
    for i in range(5):
        val = lo+(hi-lo)*i/4
        yy = y(val)
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="{GRID}"/>')
        label = f"{val*100:.1f}%" if percent else f"{val:,.2f}"
        parts.append(f'<text x="{x0-8}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{label}</text>')
    if zero and lo <= 0 <= hi:
        parts.append(f'<line x1="{x0}" y1="{y(0):.1f}" x2="{x1}" y2="{y(0):.1f}" stroke="#94a3b8"/>')
    poly = " ".join(f"{xs[i]:.1f},{y(v):.1f}" for i, (_, v) in enumerate(valid))
    parts.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.4"/>')
    for i, (d, v) in enumerate(valid):
        text = f"{v*100:.2f}%" if percent else f"{v:,.4f}"
        parts.append(f'<circle cx="{xs[i]:.1f}" cy="{y(v):.1f}" r="2" fill="{color}"><title>{escape(d)} {escape(title)} {text}</title></circle>')
    for idx in sorted(set(round(i*(len(valid)-1)/8) for i in range(9))):
        anchor = "start" if idx == 0 else "end" if idx == len(valid)-1 else "middle"
        parts.append(f'<text x="{xs[idx]:.1f}" y="{h-15}" text-anchor="{anchor}" class="axis-label">{escape(valid[idx][0][5:])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _svg_dual_line(rows, left_field, right_field, left_title, right_title):
    valid = [r for r in rows if r.get("date") and (_num(r.get(left_field)) is not None or _num(r.get(right_field)) is not None)]
    if not valid:
        return '<div class="empty">暂无历史数据</div>'
    w, h, ml, mr, mt, mb = 1200, 310, 66, 78, 22, 44
    x0, x1, y0, y1 = ml, w-mr, mt, h-mb
    xs = [x0+9+(x1-x0-30)*i/max(1, len(valid)-1) for i in range(len(valid))]
    left_values = [_num(r.get(left_field)) for r in valid if _num(r.get(left_field)) is not None]
    right_values = [_num(r.get(right_field)) for r in valid if _num(r.get(right_field)) is not None]
    left_max = max(max(left_values) if left_values else 0, .01) * 1.12
    right_max = max(max(right_values) if right_values else 0, .01) * 1.12
    yl = lambda v: y1-v/left_max*(y1-y0)
    yr = lambda v: y1-v/right_max*(y1-y0)
    parts = [f'<svg class="chart-svg" viewBox="0 0 {w} {h}">']
    for i in range(5):
        yy = y1-(y1-y0)*i/4
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{x0-8}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{left_max*i/4*100:.1f}%</text>')
        parts.append(f'<text x="{x1+10}" y="{yy+4:.1f}" text-anchor="start" class="axis-label">{right_max*i/4*100:.1f}%</text>')
    for field, transform, color, label in ((left_field, yl, BLUE, left_title), (right_field, yr, ORANGE, right_title)):
        points = []
        for i, row in enumerate(valid):
            value = _num(row.get(field))
            if value is not None:
                points.append((xs[i], transform(value), row["date"], value))
        if points:
            poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in points)
            parts.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.3"/>')
            for x, y, d, value in points:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="{color}"><title>{escape(d)} {escape(label)} {value*100:.2f}%</title></circle>')
    for idx in sorted(set(round(i*(len(valid)-1)/8) for i in range(9))):
        anchor = "start" if idx == 0 else "end" if idx == len(valid)-1 else "middle"
        parts.append(f'<text x="{xs[idx]:.1f}" y="{h-15}" text-anchor="{anchor}" class="axis-label">{escape(valid[idx]["date"][5:])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _latest_index_map(report):
    target = report["meta"]["report_date"]
    return {r["name"]: r for r in report.get("indices_history", []) if r.get("date") == target}


def _recent_indices(report):
    names = ["上证50", "Choice微盘", "中证全指"]
    by_date = {}
    for item in report.get("indices_history", []):
        if item.get("name") in names:
            by_date.setdefault(item["date"], {})[item["name"]] = item
    market = {r["date"]: r for r in report.get("market_history", [])}
    dates = sorted(set(by_date) | set(market), reverse=True)[:5]
    rows = []
    for d in dates:
        row = [escape(d)]
        for name in names:
            item = by_date.get(d, {}).get(name, {})
            row.extend([f'<span class="{_cls(item.get("return"))}">{_pct(item.get("return"))}</span>', _fmt(item.get("amount_100m"))])
        row.append(_fmt(market.get(d, {}).get("total_amount_100m")))
        rows.append(row)
    return _table(["日期", "上证50", "成交额", "Choice微盘", "成交额", "中证全指", "成交额", "全A成交额"], rows)


def _sw_industry(report):
    rows = []
    for r in report.get("sw_industry_latest", []):
        rows.append([
            escape(str(r.get("行业层级") or "")), escape(str(r.get("一级行业") or "")),
            escape(str(r.get("指数代码") or "")), escape(str(r.get("指数名称") or "")),
            _fmt(r.get("收盘价")), _fmt(r.get("成交额")),
            f'<span class="{_cls(r.get("日收益率"))}">{_pct(r.get("日收益率"))}</span>',
            _pct(r.get("20日年化波动率"), signed=False),
        ])
    toolbar = '<div class="toolbar"><input id="swSearch" type="search" placeholder="搜索行业/指数代码…"><select id="swLevel"><option value="">全部层级</option><option>一级行业</option><option>二级行业</option></select><span class="hint">本地筛选，不联网</span></div>'
    return toolbar + _table(["层级", "一级行业", "指数代码", "指数名称", "收盘", "成交额", "日收益率", "20日年化波动率"], rows, classes="sw-table")


def _hot_matrix(report):
    matrix = report.get("hot_stock_matrix", {})
    dates = matrix.get("dates", [])
    rows = [[escape(str(r.get("industry") or ""))] + [str(int(x or 0)) for x in r.get("counts", [])] + [str(int(r.get("history_total") or 0))] for r in matrix.get("rows", [])]
    return _table(["行业"] + [d[5:] for d in dates] + ["历史累计"], rows)


def _hot_detail(report):
    rows = []
    for r in report.get("hot_stocks_latest", []):
        rows.append([
            str(r.get("rank") or ""), f'<span class="code">{escape(str(r.get("stock_code") or "").zfill(6))}</span>',
            escape(str(r.get("stock_name") or "")), _fmt(r.get("close")),
            f'<span class="{_cls(r.get("return"))}">{_pct(r.get("return"))}</span>', _fmt(r.get("amount_100m")),
            escape(str(r.get("sw_level1") or "")), escape(str(r.get("sw_level2") or "")),
        ])
    return _table(["排名", "代码", "名称", "收盘价", "涨跌幅", "成交额(亿元)", "申万一级", "申万二级"], rows, row_attr='data-hot-row="1"')


def _crowding(report):
    history = report.get("sw_crowding_history", [])
    if not history:
        return '<div class="empty">暂无申万四行业拥挤度历史</div>'
    latest = history[-1]
    rows = []
    for name in ("通信设备", "计算机设备", "元件", "半导体"):
        item = latest.get("targets", {}).get(name, {})
        rows.append([escape(name), _fmt(item.get("amount_100m")), _pct(item.get("amount_share_of_a"), signed=False), _pct(item.get("turnover"), signed=False)])
    combined = latest.get("combined", {})
    rows.append(["四行业合计", _fmt(combined.get("amount_100m")), _pct(combined.get("amount_share_of_a"), signed=False), "—"])
    flat = []
    for item in history:
        comm = item.get("targets", {}).get("通信设备", {})
        flat.append({"date": item["date"], "share": comm.get("amount_share_of_a"), "turnover": comm.get("turnover"), "combined_share": item.get("combined", {}).get("amount_share_of_a"), "combined_amount": item.get("combined", {}).get("amount_100m")})
    charts = '<div class="chart-card"><h3>通信设备｜成交额占全A与换手率</h3>' + _svg_dual_line(flat, "share", "turnover", "成交额占全A", "换手率") + '</div>'
    charts += '<div class="chart-grid-two"><div class="chart-card"><h3>四行业成交额合计</h3>' + _svg_line(flat, "combined_amount", "四行业成交额合计", False, False, NAVY) + '</div>'
    charts += '<div class="chart-card"><h3>四行业成交额占全A</h3>' + _svg_line(flat, "combined_share", "四行业成交额占全A", True, False, ORANGE) + '</div></div>'
    return f'<div class="subnote">最新官方有效日：{escape(latest["date"])}</div>' + _table(["行业", "成交额(亿元)", "占全A", "换手率"], rows) + charts


def _innovation(report):
    history = report.get("innovation_history", [])
    if not history:
        return '<div class="empty">暂无创新药历史</div>'
    latest = history[-1]
    summary = _table(["最新日", "成交额(亿元)", "占全A", "换手率", "日收益率", "成交量"], [[
        escape(latest["date"]), _fmt(latest.get("amount_100m")), _pct(latest.get("amount_share_of_a"), signed=False),
        _pct(latest.get("turnover"), signed=False), f'<span class="{_cls(latest.get("return"))}">{_pct(latest.get("return"))}</span>', _fmt(latest.get("volume"), 0),
    ]])
    return summary + '<div class="chart-card"><h3>创新药｜成交额占全A与可靠换手率</h3>' + _svg_dual_line(history, "amount_share_of_a", "turnover", "成交额占全A", "换手率") + '</div>'


def _quality(report):
    quality = report.get("quality", {})
    label_map = {
        "market": "市场核心",
        "indices": "三项指数",
        "sw_industry": "申万行业",
        "sw_crowding": "四行业拥挤度",
        "innovation": "创新药",
    }
    latest_rows = [[escape(label_map.get(k, k)), escape(str(v or "—"))] for k, v in quality.get("module_latest_dates", {}).items()]
    html = _table(["模块", "最新有效日"], latest_rows)
    unresolved = quality.get("unresolved", [])
    if unresolved:
        module_map = {"market_denominator": "全A历史成交额分母", "indices_history": "指数历史", "hot_stocks_latest": "百亿成交明细"}
        items = "".join(f'<li><strong>{escape(module_map.get(str(x.get("module")), str(x.get("module"))))}</strong>：{escape(json.dumps(x.get("detail"), ensure_ascii=False))}</li>' for x in unresolved)
        return html + f'<div class="quality-warn"><b>未解决事项</b><ul>{items}</ul></div>'
    return html + '<div class="quality-pass">历史预检未发现未解决关键缺口。</div>'


def render_html(report: dict) -> str:
    meta = report.get("meta", {})
    target = str(meta.get("report_date") or "")
    market = report.get("market_history", [])
    latest_market = market[-1] if market else {}
    indices = _latest_index_map(report)
    status = str(meta.get("status") or "UNKNOWN")
    status_class = "pass" if status == "PASS" else "warn" if status == "WARN" else "fail"
    kpis = [
        ("上证50", _pct(indices.get("上证50", {}).get("return")), _cls(indices.get("上证50", {}).get("return"))),
        ("Choice微盘", _pct(indices.get("Choice微盘", {}).get("return")), _cls(indices.get("Choice微盘", {}).get("return"))),
        ("中证全指", _pct(indices.get("中证全指", {}).get("return")), _cls(indices.get("中证全指", {}).get("return"))),
        ("全A成交额", _fmt(latest_market.get("total_amount_100m"), 0) + " 亿", "neutral"),
        ("百亿成交股", str(latest_market.get("hot_count") if latest_market.get("hot_count") is not None else "—") + " 只", "neutral"),
        ("市场宽度", _pct(latest_market.get("market_breadth"), 1), _cls(latest_market.get("market_breadth"))),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="kpi-label">{escape(label)}</div><div class="kpi-value {css}">{escape(value)}</div></div>' for label, value, css in kpis)
    sw_latest = report.get("quality", {}).get("module_latest_dates", {}).get("sw_industry") or "—"
    hot_count = len(report.get("hot_stocks_latest", []))
    style = f'''
:root{{--navy:{NAVY};--text:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#f4f7fb;--up:{UP};--down:{DOWN}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",Arial,sans-serif;font-size:14px}}.page{{max-width:1500px;margin:auto;padding:18px 22px 56px}}.hero{{background:linear-gradient(135deg,#123d68,#174f82);color:#fff;padding:24px 28px;border-radius:12px;box-shadow:0 8px 24px #0f27401a}}.hero-top{{display:flex;justify-content:space-between;gap:20px}}h1{{margin:0;font-size:26px}}.meta{{margin-top:8px;color:#dbeafe}}.status{{padding:7px 12px;border-radius:999px;font-weight:700;background:#ffffff1c;border:1px solid #ffffff40;height:max-content}}.status.pass{{color:#d1fae5}}.status.warn{{color:#fef3c7}}.status.fail{{color:#fee2e2}}.kpis{{display:grid;grid-template-columns:repeat(6,minmax(140px,1fr));gap:12px;margin:16px 0}}.kpi,.card{{background:#fff;border:1px solid var(--line);box-shadow:0 2px 10px #0f172a0a}}.kpi{{padding:14px 16px;border-radius:10px}}.kpi-label{{font-size:12px;color:var(--muted)}}.kpi-value{{font-size:23px;font-weight:750;margin-top:5px}}.up{{color:var(--up)}}.down{{color:var(--down)}}.neutral{{color:#0f172a}}.section{{margin-top:18px}}.section-title{{background:var(--navy);color:#fff;border-radius:9px 9px 0 0;padding:10px 14px;font-size:17px;font-weight:700}}.card{{border-radius:0 0 10px 10px;padding:14px 16px}}.chart-card{{background:#fff;border:1px solid var(--line);border-radius:9px;padding:10px;margin-top:12px;overflow:auto}}.chart-card h3{{margin:3px 4px 9px;font-size:15px}}.chart-svg{{width:100%;height:auto;display:block;min-width:720px}}.chart-grid-two .chart-svg{{min-width:0}}.axis-label{{font-size:11px;fill:#64748b}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:8px;margin-top:10px;background:#fff}}.sw-table{{max-height:900px;overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:760px}}th{{background:#f1f5f9;color:#334155;font-weight:650;position:sticky;top:0;z-index:1}}th,td{{padding:8px 10px;border-bottom:1px solid #e8edf3;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}tbody tr:hover{{background:#f8fafc}}.code{{font-family:Consolas,monospace}}.subnote,.hint{{font-size:12px;color:var(--muted)}}.toolbar{{display:flex;gap:8px;align-items:center;margin:6px 0 9px}}.toolbar input,.toolbar select{{border:1px solid #cbd5e1;border-radius:6px;padding:7px 9px;background:#fff}}.chart-grid-two{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.quality-warn{{margin-top:12px;padding:12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px}}.quality-pass{{margin-top:12px;padding:12px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px}}.empty{{padding:22px;text-align:center;color:var(--muted)}}@media(max-width:1100px){{.kpis{{grid-template-columns:repeat(3,1fr)}}.chart-grid-two{{grid-template-columns:1fr}}}}@media(max-width:650px){{.page{{padding:10px}}.kpis{{grid-template-columns:repeat(2,1fr)}}.hero-top{{display:block}}.status{{display:inline-block;margin-top:12px}}}}
'''
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股每日市场监控 {escape(target)}</title><style>{style}</style></head><body><div class="page">
<header class="hero"><div class="hero-top"><div><h1>A股每日市场监控</h1><div class="meta">报告日期 {escape(target)} ｜ 申万行业最新有效日 {escape(str(sw_latest))} ｜ 单文件离线报告</div></div><div class="status {status_class}">数据状态 {escape(status)}</div></div></header><div class="kpis">{kpi_html}</div>
<section class="section"><div class="section-title">00｜市场总览 · 市场涨跌结构</div><div class="card"><div class="subnote">上涨/下跌家数使用左轴；涨停/跌停家数使用右轴。右侧预留安全边距，最新日期不会与右轴刻度重叠。</div><div class="chart-card">{_svg_market_structure(market)}</div></div></section>
<section class="section"><div class="section-title">00｜市场总览 · 市场宽度</div><div class="card"><div class="chart-card">{_svg_line(market, "market_breadth", "市场宽度", True, True, NAVY)}</div></div></section>
<section class="section"><div class="section-title">00｜市场总览 · 最近交易日指数与成交</div><div class="card">{_recent_indices(report)}</div></section>
<section class="section"><div class="section-title">01｜申万行业</div><div class="card"><div class="subnote">完整展示最新批量快照，可在本页搜索与筛选。</div>{_sw_industry(report)}</div></section>
<section class="section"><div class="section-title">04｜百亿成交</div><div class="card"><h3>最近日期矩阵</h3>{_hot_matrix(report)}<h3 style="margin-top:18px">{escape(target)} 成交额超过100亿元个股｜完整明细 {hot_count} 只</h3>{_hot_detail(report)}</div></section>
<section class="section"><div class="section-title">05｜申万四行业资金拥挤度</div><div class="card">{_crowding(report)}</div></section>
<section class="section"><div class="section-title">06｜创新药交易拥挤度</div><div class="card"><div class="subnote">仅使用供应商直接板块换手率；20日成交量活跃度代理已永久停用。</div>{_innovation(report)}</div></section>
<section class="section"><div class="section-title">99｜数据质量</div><div class="card">{_quality(report)}</div></section></div>
<script>(function(){{const q=document.getElementById('swSearch'),s=document.getElementById('swLevel');function filter(){{const text=(q?.value||'').trim().toLowerCase(),level=s?.value||'';document.querySelectorAll('.sw-table tbody tr').forEach(tr=>{{const cells=Array.from(tr.cells).map(x=>x.textContent.trim());tr.style.display=(!text||tr.textContent.toLowerCase().includes(text))&&(!level||cells[0]===level)?'':'none';}})}}q?.addEventListener('input',filter);s?.addEventListener('change',filter);}})();</script></body></html>'''
    return html


def main():
    parser = argparse.ArgumentParser(description="Render self-contained A-share market monitor HTML")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    html = render_html(report)
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"html={args.output} bytes={len(html.encode('utf-8'))}")


if __name__ == "__main__":
    main()
