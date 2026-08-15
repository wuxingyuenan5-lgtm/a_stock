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
MUTED = "#64748b"
GRID = "#e2e8f0"
ORANGE = "#f97316"


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v, digits=2):
    n = _num(v)
    return "—" if n is None else f"{n:,.{digits}f}"


def _pct(v, digits=2):
    n = _num(v)
    return "—" if n is None else f"{n * 100:+.{digits}f}%"


def _pct_plain(v, digits=2):
    n = _num(v)
    return "—" if n is None else f"{n * 100:.{digits}f}%"


def _cls(v):
    n = _num(v)
    if n is None or abs(n) < 1e-15:
        return "neutral"
    return "up" if n > 0 else "down"


def _safe_max(values, default=1.0):
    vals = [abs(float(v)) for v in values if v is not None]
    return max(vals) if vals else default


def _ticks(max_abs: float, count: int = 4):
    if max_abs <= 0:
        return [0]
    raw = max_abs / count
    power = 10 ** math.floor(math.log10(raw)) if raw else 1
    scaled = raw / power
    step = (1 if scaled <= 1 else 2 if scaled <= 2 else 5 if scaled <= 5 else 10) * power
    top = math.ceil(max_abs / step) * step
    return [i * step for i in range(-int(top / step), int(top / step) + 1)]


def _svg_market_structure(rows: list[dict]) -> str:
    rows = [r for r in rows if r.get("date")]
    if not rows:
        return '<div class="empty">暂无市场结构历史</div>'
    w, h = 1200, 430
    ml, mr, mt, mb = 68, 82, 26, 48
    x0, x1 = ml, w - mr
    y0, y1 = mt, h - mb
    zero_y = (y0 + y1) / 2
    left_max = _safe_max([r.get("advance") for r in rows] + [r.get("decline") for r in rows]) * 1.08
    right_max = _safe_max([r.get("limit_up") for r in rows] + [r.get("limit_down") for r in rows]) * 1.12
    left_max = max(left_max, 1)
    right_max = max(right_max, 1)
    n = len(rows)
    inner_l, inner_r = x0 + 8, x1 - 18
    xs = [inner_l + (inner_r - inner_l) * i / max(1, n - 1) for i in range(n)]
    bar_w = max(1.2, min(7.0, (inner_r-inner_l) / max(1,n) * 0.65))

    def yl(v):
        return zero_y - (float(v) / left_max) * ((y1-y0)/2 * 0.92)
    def yr(v):
        return zero_y - (float(v) / right_max) * ((y1-y0)/2 * 0.92)

    parts = [f'<svg class="chart-svg" viewBox="0 0 {w} {h}" role="img" aria-label="市场涨跌结构">']
    parts.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="#fff"/>')
    for t in _ticks(left_max, 4):
        if t < -left_max or t > left_max:
            continue
        yy = yl(t)
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{x0-9}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{int(t):,}</text>')
    parts.append(f'<line x1="{x0}" y1="{zero_y:.1f}" x2="{x1}" y2="{zero_y:.1f}" stroke="#94a3b8" stroke-width="1.2"/>')
    # Right-axis ticks placed outside plot boundary so the last x label does not collide.
    for frac in (-1, -0.5, 0, 0.5, 1):
        yy = zero_y - frac * ((y1-y0)/2 * 0.92)
        val = frac * right_max
        parts.append(f'<text x="{x1+12}" y="{yy+4:.1f}" text-anchor="start" class="axis-label">{int(round(val))}</text>')

    up_pts, down_pts = [], []
    for i, row in enumerate(rows):
        x = xs[i]
        adv, dec = _num(row.get("advance")), _num(row.get("decline"))
        lu, ld = _num(row.get("limit_up")), _num(row.get("limit_down"))
        d = escape(str(row["date"]))
        if adv is not None:
            y = yl(adv)
            parts.append(f'<rect x="{x-bar_w/2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{zero_y-y:.1f}" fill="{UP}" opacity=".22"><title>{d} 上涨 {int(adv)} 家</title></rect>')
        if dec is not None:
            y = yl(-dec)
            parts.append(f'<rect x="{x-bar_w/2:.1f}" y="{zero_y:.1f}" width="{bar_w:.1f}" height="{y-zero_y:.1f}" fill="{DOWN}" opacity=".22"><title>{d} 下跌 {int(dec)} 家</title></rect>')
        if lu is not None:
            up_pts.append((x, yr(lu), d, lu))
        if ld is not None:
            down_pts.append((x, yr(-ld), d, ld))
    for points, color, label in ((up_pts, UP, "涨停"), (down_pts, DOWN, "跌停")):
        if points:
            poly = " ".join(f"{x:.1f},{y:.1f}" for x,y,_,_ in points)
            parts.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round"/>')
            for x,y,d,v in points:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2" fill="{color}"><title>{d} {label} {int(v)} 家</title></circle>')
    label_count = min(10, n)
    idxs = sorted(set(round(i*(n-1)/max(1,label_count-1)) for i in range(label_count)))
    for j,i in enumerate(idxs):
        anchor = "start" if i == 0 else "end" if i == n-1 else "middle"
        dx = 0 if i != n-1 else -2
        parts.append(f'<text x="{xs[i]+dx:.1f}" y="{h-18}" text-anchor="{anchor}" class="axis-label">{escape(rows[i]["date"][5:])}</text>')
    last = rows[-1]
    parts.append(
        f'<g data-chart-date="{escape(last["date"])}" data-advance="{last.get("advance")}" '
        f'data-decline="{last.get("decline")}" data-limit-up="{last.get("limit_up")}" '
        f'data-limit-down="{last.get("limit_down")}"></g>'
    )
    parts.append('</svg>')
    return "".join(parts)


def _svg_line(rows: list[dict], field: str, title: str, percent: bool = False, zero_line: bool = True, color: str = BLUE) -> str:
    valid = [(r["date"], _num(r.get(field))) for r in rows if r.get("date") and _num(r.get(field)) is not None]
    if not valid:
        return '<div class="empty">暂无历史数据</div>'
    w,h=1200,300; ml,mr,mt,mb=62,48,24,42; x0,x1=ml,w-mr; y0,y1=mt,h-mb
    vals=[v for _,v in valid]
    lo,hi=min(vals),max(vals)
    if zero_line:
        lo=min(lo,0); hi=max(hi,0)
    span=max(hi-lo,1e-9); pad=span*0.10; lo-=pad; hi+=pad
    xs=[x0+8+(x1-x0-26)*i/max(1,len(valid)-1) for i in range(len(valid))]
    def y(v): return y1-(v-lo)/(hi-lo)*(y1-y0)
    parts=[f'<svg class="chart-svg" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">']
    if zero_line and lo <= 0 <= hi:
        zy=y(0); parts.append(f'<line x1="{x0}" y1="{zy:.1f}" x2="{x1}" y2="{zy:.1f}" stroke="#94a3b8" stroke-width="1.1"/>')
    for i in range(5):
        val=lo+(hi-lo)*i/4; yy=y(val)
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="{GRID}"/>')
        label=f"{val*100:.1f}%" if percent else f"{val:.2f}"
        parts.append(f'<text x="{x0-8}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{label}</text>')
    poly=" ".join(f"{xs[i]:.1f},{y(v):.1f}" for i,(_,v) in enumerate(valid))
    parts.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>')
    for i,(d,v) in enumerate(valid):
        label=f"{v*100:.2f}%" if percent else f"{v:.4f}"
        parts.append(f'<circle cx="{xs[i]:.1f}" cy="{y(v):.1f}" r="2" fill="{color}"><title>{escape(d)} {escape(title)} {label}</title></circle>')
    idxs=sorted(set(round(i*(len(valid)-1)/8) for i in range(9)))
    for i in idxs:
        anchor="start" if i==0 else "end" if i==len(valid)-1 else "middle"
        parts.append(f'<text x="{xs[i]:.1f}" y="{h-15}" text-anchor="{anchor}" class="axis-label">{escape(valid[i][0][5:])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _svg_dual_line(rows: list[dict], field_left: str, field_right: str, title_left: str, title_right: str) -> str:
    valid=[r for r in rows if r.get("date") and (_num(r.get(field_left)) is not None or _num(r.get(field_right)) is not None)]
    if not valid: return '<div class="empty">暂无历史数据</div>'
    w,h=1200,310; ml,mr,mt,mb=64,70,24,42; x0,x1=ml,w-mr; y0,y1=mt,h-mb
    xs=[x0+8+(x1-x0-26)*i/max(1,len(valid)-1) for i in range(len(valid))]
    lv=[_num(r.get(field_left)) for r in valid if _num(r.get(field_left)) is not None]
    rv=[_num(r.get(field_right)) for r in valid if _num(r.get(field_right)) is not None]
    lmax=max(lv) if lv else 1; rmax=max(rv) if rv else 1
    lmax=max(lmax*1.12,0.01); rmax=max(rmax*1.12,0.01)
    def yl(v): return y1-(v/lmax)*(y1-y0)
    def yr(v): return y1-(v/rmax)*(y1-y0)
    parts=[f'<svg class="chart-svg" viewBox="0 0 {w} {h}">']
    for i in range(5):
        yy=y1-(y1-y0)*i/4
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{x0-8}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{lmax*i/4*100:.1f}%</text>')
        parts.append(f'<text x="{x1+9}" y="{yy+4:.1f}" text-anchor="start" class="axis-label">{rmax*i/4*100:.1f}%</text>')
    for field,fn,color,label in ((field_left,yl,BLUE,title_left),(field_right,yr,ORANGE,title_right)):
        pts=[]
        for i,r in enumerate(valid):
            v=_num(r.get(field))
            if v is not None: pts.append((xs[i],fn(v),r["date"],v))
        if pts:
            parts.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x,y,_,_ in pts)}" fill="none" stroke="{color}" stroke-width="2.3"/>')
            for x,y,d,v in pts:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="{color}"><title>{escape(d)} {escape(label)} {v*100:.2f}%</title></circle>')
    idxs=sorted(set(round(i*(len(valid)-1)/8) for i in range(9)))
    for i in idxs:
        anchor="start" if i==0 else "end" if i==len(valid)-1 else "middle"
        parts.append(f'<text x="{xs[i]:.1f}" y="{h-15}" text-anchor="{anchor}" class="axis-label">{escape(valid[i]["date"][5:])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _table(headers, rows, classes=""):
    head="".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body=[]
    for row in rows:
        cells="".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap {classes}"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _latest_index_map(report):
    target=report["meta"]["report_date"]
    return {r["name"]:r for r in report.get("indices_history",[]) if r.get("date")==target}


def _recent_index_table(report):
    names=["上证50","Choice微盘","中证全指"]
    by_date={}
    for r in report.get("indices_history",[]):
        if r.get("name") in names:
            by_date.setdefault(r["date"],{})[r["name"]]=r
    market={r["date"]:r for r in report.get("market_history",[])}
    dates=sorted(set(by_date)|set(market), reverse=True)[:5]
    rows=[]
    for d in dates:
        row=[escape(d)]
        for name in names:
            item=by_date.get(d,{}).get(name,{})
            row += [f'<span class="{_cls(item.get("return"))}">{_pct(item.get("return"))}</span>', _fmt(item.get("amount_100m"))]
        row.append(_fmt(market.get(d,{}).get("total_amount_100m")))
        rows.append(row)
    return _table(["日期","上证50","成交额","Choice微盘","成交额","中证全指","成交额","全A成交额"], rows)


def _sw_industry_table(report):
    rows=[]
    for r in report.get("sw_industry_latest",[]):
        rows.append([
            escape(str(r.get("行业层级") or "")), escape(str(r.get("一级行业") or "")), escape(str(r.get("指数代码") or "")),
            escape(str(r.get("指数名称") or "")), _fmt(r.get("收盘价")), _fmt(r.get("成交额")),
            f'<span class="{_cls(r.get("日收益率"))}">{_pct(r.get("日收益率"))}</span>', _pct_plain(r.get("20日年化波动率")),
        ])
    return '<div class="toolbar"><input id="swSearch" type="search" placeholder="搜索行业/指数代码…"><select id="swLevel"><option value="">全部层级</option><option>一级行业</option><option>二级行业</option></select><span class="hint">本地筛选，不联网</span></div>' + _table(["层级","一级行业","指数代码","指数名称","收盘","成交额","日收益率","20日年化波动率"], rows, "sw-table")


def _hot_matrix(report):
    m=report.get("hot_stock_matrix",{})
    dates=m.get("dates",[])
    rows=[]
    for r in m.get("rows",[]):
        rows.append([escape(str(r.get("industry") or ""))]+[str(int(x or 0)) for x in r.get("counts",[])]+[str(int(r.get("history_total") or 0))])
    return _table(["行业"]+[d[5:] for d in dates]+["历史累计"], rows)


def _hot_detail(report):
    rows=[]
    for r in report.get("hot_stocks_latest",[]):
        rows.append([
            str(r.get("rank") or ""), f'<span class="code">{escape(str(r.get("stock_code") or "").zfill(6))}</span>', escape(str(r.get("stock_name") or "")),
            _fmt(r.get("close")), f'<span class="{_cls(r.get("return"))}">{_pct(r.get("return"))}</span>', _fmt(r.get("amount_100m")),
            escape(str(r.get("sw_level1") or "")), escape(str(r.get("sw_level2") or "")),
        ])
    table=_table(["排名","代码","名称","收盘价","涨跌幅","成交额(亿元)","申万一级","申万二级"], rows)
    return table.replace("<tr>", '<tr data-hot-row="1">', len(rows)).replace('<tr data-hot-row="1"><th', '<tr><th', 1)


def _crowding_section(report):
    history=report.get("sw_crowding_history",[])
    if not history: return '<div class="empty">暂无申万四行业拥挤度历史</div>'
    latest=history[-1]
    targets=latest.get("targets",{})
    rows=[]
    for name in ("通信设备","计算机设备","元件","半导体"):
        r=targets.get(name,{})
        rows.append([escape(name),_fmt(r.get("amount_100m")),_pct_plain(r.get("amount_share_of_a")),_pct_plain(r.get("turnover"))])
    combined=latest.get("combined",{})
    rows.append(["四行业合计",_fmt(combined.get("amount_100m")),_pct_plain(combined.get("amount_share_of_a")),"—"])
    flat=[]
    for item in history:
        comm=item.get("targets",{}).get("通信设备",{})
        flat.append({"date":item["date"],"share":comm.get("amount_share_of_a"),"turnover":comm.get("turnover"),"combined_share":item.get("combined",{}).get("amount_share_of_a"),"combined_amount":item.get("combined",{}).get("amount_100m")})
    charts=(
        '<div class="chart-card"><h3>通信设备｜成交额占全A与换手率</h3>'+_svg_dual_line(flat,"share","turnover","成交额占全A","换手率")+'</div>'+
        '<div class="chart-grid-two"><div class="chart-card"><h3>四行业成交额合计</h3>'+_svg_line(flat,"combined_amount","四行业成交额合计",False,False,NAVY)+'</div>'+
        '<div class="chart-card"><h3>四行业成交额占全A</h3>'+_svg_line(flat,"combined_share","四行业成交额占全A",True,False,ORANGE)+'</div></div>'
    )
    return f'<div class="subnote">最新官方有效日：{escape(latest["date"])}</div>'+_table(["行业","成交额(亿元)","占全A","换手率"],rows)+charts


def _innovation_section(report):
    hist=report.get("innovation_history",[])
    if not hist:return '<div class="empty">暂无创新药历史</div>'
    latest=hist[-1]
    summary=_table(["最新日","成交额(亿元)","占全A","换手率","日收益率","成交量"],[[escape(latest["date"]),_fmt(latest.get("amount_100m")),_pct_plain(latest.get("amount_share_of_a")),_pct_plain(latest.get("turnover")),f'<span class="{_cls(latest.get("return"))}">{_pct(latest.get("return"))}</span>',_fmt(latest.get("volume"),0)]])
    chart=_svg_dual_line(hist,"amount_share_of_a","turnover","成交额占全A","换手率")
    return summary+'<div class="chart-card"><h3>创新药｜成交额占全A与可靠换手率</h3>'+chart+'</div>'


def _quality(report):
    q=report.get("quality",{})
    latest=q.get("module_latest_dates",{})
    unresolved=q.get("unresolved",[])
    rows=[[escape(k),escape(str(v or "—"))] for k,v in latest.items()]
    blocks=[_table(["模块","最新有效日"],rows)]
    if unresolved:
        items="".join(f'<li><strong>{escape(str(x.get("module")))}</strong>：{escape(json.dumps(x.get("detail"),ensure_ascii=False))}</li>' for x in unresolved)
        blocks.append(f'<div class="quality-warn"><b>未解决事项</b><ul>{items}</ul></div>')
    else:
        blocks.append('<div class="quality-pass">历史预检未发现未解决关键缺口。</div>')
    return "".join(blocks)


def render_html(report: dict) -> str:
    meta=report.get("meta",{}); target=meta.get("report_date","")
    market=report.get("market_history",[]); latest_market=market[-1] if market else {}
    indices=_latest_index_map(report)
    status=meta.get("status","UNKNOWN")
    status_cls="pass" if status=="PASS" else "warn" if status=="WARN" else "fail"
    kpis=[
        ("上证50",_pct(indices.get("上证50",{}).get("return")),_cls(indices.get("上证50",{}).get("return"))),
        ("Choice微盘",_pct(indices.get("Choice微盘",{}).get("return")),_cls(indices.get("Choice微盘",{}).get("return"))),
        ("中证全指",_pct(indices.get("中证全指",{}).get("return")),_cls(indices.get("中证全指",{}).get("return"))),
        ("全A成交额",_fmt(latest_market.get("total_amount_100m"),0)+" 亿","neutral"),
        ("百亿成交股",str(latest_market.get("hot_count") if latest_market.get("hot_count") is not None else "—")+" 只","neutral"),
        ("市场宽度",_pct(latest_market.get("market_breadth"),1),_cls(latest_market.get("market_breadth"))),
    ]
    kpi_html="".join(f'<div class="kpi"><div class="kpi-label">{escape(label)}</div><div class="kpi-value {cls}">{escape(value)}</div></div>' for label,value,cls in kpis)
    sw_latest=report.get("quality",{}).get("module_latest_dates",{}).get("sw_industry") or "—"
    html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股每日市场监控 {escape(target)}</title><style>
:root{{--navy:{NAVY};--text:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#f4f7fb;--up:{UP};--down:{DOWN};}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",Arial,sans-serif;font-size:14px}}.page{{max-width:1500px;margin:auto;padding:18px 22px 56px}}.hero{{background:linear-gradient(135deg,#123d68,#174f82);color:white;padding:24px 28px;border-radius:12px;box-shadow:0 8px 24px #0f27401a}}.hero-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}}h1{{margin:0;font-size:26px;letter-spacing:.5px}}.meta{{margin-top:8px;color:#dbeafe}}.status{{padding:7px 12px;border-radius:999px;font-weight:700;background:#ffffff1c;border:1px solid #ffffff40}}.status.pass{{color:#d1fae5}}.status.warn{{color:#fef3c7}}.status.fail{{color:#fee2e2}}.kpis{{display:grid;grid-template-columns:repeat(6,minmax(140px,1fr));gap:12px;margin:16px 0}}.kpi,.card{{background:white;border:1px solid var(--line);border-radius:10px;box-shadow:0 2px 10px #0f172a0a}}.kpi{{padding:14px 16px}}.kpi-label{{font-size:12px;color:var(--muted)}}.kpi-value{{font-size:23px;font-weight:750;margin-top:5px}}.up{{color:var(--up)}}.down{{color:var(--down)}}.neutral{{color:#0f172a}}.section{{margin-top:18px}}.section-title{{background:var(--navy);color:white;border-radius:9px 9px 0 0;padding:10px 14px;font-size:17px;font-weight:700}}.card{{border-radius:0 0 10px 10px;padding:14px 16px}}.chart-card{{background:#fff;border:1px solid var(--line);border-radius:9px;padding:10px;margin-top:12px;overflow:hidden}}.chart-card h3{{margin:3px 4px 9px;font-size:15px}}.chart-svg{{width:100%;height:auto;display:block;min-width:720px}}.axis-label{{font-size:11px;fill:#64748b}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:8px;margin-top:10px;background:white}}table{{border-collapse:collapse;width:100%;min-width:760px}}th{{background:#f1f5f9;color:#334155;font-weight:650;position:sticky;top:0;z-index:1}}th,td{{padding:8px 10px;border-bottom:1px solid #e8edf3;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}tbody tr:hover{{background:#f8fafc}}.code{{font-family:Consolas,monospace}}.subnote,.hint{{font-size:12px;color:var(--muted)}}.toolbar{{display:flex;gap:8px;align-items:center;margin:6px 0 9px}}.toolbar input,.toolbar select{{border:1px solid #cbd5e1;border-radius:6px;padding:7px 9px;background:white}}.chart-grid-two{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.quality-warn{{margin-top:12px;padding:12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px}}.quality-pass{{margin-top:12px;padding:12px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px}}.empty{{padding:22px;text-align:center;color:var(--muted)}}@media(max-width:1100px){{.kpis{{grid-template-columns:repeat(3,1fr)}}.chart-grid-two{{grid-template-columns:1fr}}}}@media(max-width:650px){{.page{{padding:10px}}.kpis{{grid-template-columns:repeat(2,1fr)}}.hero-top{{display:block}}.status{{display:inline-block;margin-top:12px}}}}
</style></head><body><div class="page"><header class="hero"><div class="hero-top"><div><h1>A股每日市场监控</h1><div class="meta">报告日期 {escape(target)} ｜ 申万行业最新有效日 {escape(str(sw_latest))} ｜ 单文件离线报告</div></div><div class="status {status_cls}">数据状态 {escape(str(status))}</div></div></header><div class="kpis">{kpi_html}</div>
<section class="section"><div class="section-title">01｜市场涨跌结构</div><div class="card"><div class="subnote">上涨/下跌家数使用左轴；涨停/跌停家数使用右轴。横轴右侧预留安全边距，最新日期不会与右轴刻度重叠。</div><div class="chart-card">{_svg_market_structure(market)}</div></div></section>
<section class="section"><div class="section-title">02｜市场宽度</div><div class="card"><div class="chart-card">{_svg_line(market,"market_breadth","市场宽度",True,True,NAVY)}</div></div></section>
<section class="section"><div class="section-title">03｜最近交易日指数与成交</div><div class="card">{_recent_index_table(report)}</div></section>
<section class="section"><div class="section-title">04｜申万行业</div><div class="card"><div class="subnote">完整展示最新批量快照，可在本页搜索与筛选。</div>{_sw_industry_table(report)}</div></section>
<section class="section"><div class="section-title">05｜百亿成交</div><div class="card"><h3>最近日期矩阵</h3>{_hot_matrix(report)}<h3 style="margin-top:18px">{escape(target)} 成交额超过100亿元个股｜完整明细 {len(report.get("hot_stocks_latest",[]))} 只</h3>{_hot_detail(report)}</div></section>
<section class="section"><div class="section-title">06｜申万四行业资金拥挤度</div><div class="card">{_crowding_section(report)}</div></section>
<section class="section"><div class="section-title">07｜创新药交易拥挤度</div><div class="card"><div class="subnote">仅使用供应商直接板块换手率；20日成交量活跃度代理已永久停用。</div>{_innovation_section(report)}</div></section>
<section class="section"><div class="section-title">99｜数据质量</div><div class="card">{_quality(report)}</div></section>
</div><script>
(function(){{const q=document.getElementById('swSearch'),s=document.getElementById('swLevel');function f(){{const text=(q?.value||'').trim().toLowerCase(),level=s?.value||'';document.querySelectorAll('.sw-table tbody tr').forEach(tr=>{{const cells=Array.from(tr.cells).map(x=>x.textContent.trim());const okText=!text||tr.textContent.toLowerCase().includes(text);const okLevel=!level||cells[0]===level;tr.style.display=okText&&okLevel?'':'none';}})}}q?.addEventListener('input',f);s?.addEventListener('change',f);}})();
</script></body></html>'''
    return html


def main():
    p=argparse.ArgumentParser(description="Render self-contained A-share market monitor HTML")
    p.add_argument("--input",required=True); p.add_argument("--output",required=True)
    a=p.parse_args(); report=json.loads(Path(a.input).read_text(encoding="utf-8")); html=render_html(report); Path(a.output).write_text(html,encoding="utf-8"); print(f"html={a.output} bytes={len(html.encode('utf-8'))}")


if __name__=="__main__": main()
