#!/usr/bin/env python3
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path

UP = "#ef4444"
DOWN = "#10b981"
NAVY = "#123d68"
COLORS = ["#2563eb", "#f97316", "#7c3aed", "#0891b2", "#dc2626", "#16a34a"]
CHART_RUNTIME_PATH = Path(__file__).resolve().parent / "assets" / "market_monitor_charts.js"


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


def _table(headers, rows, classes="", row_attrs=None, sortable=None):
    sortable = sortable or {}
    head = []
    for index, header in enumerate(headers):
        if index in sortable:
            field = sortable[index]
            head.append(
                f'<th class="sortable" data-sort-field="{escape(field)}" '
                f'data-sort-state="original">{escape(str(header))}'
                '<span class="sort-ind">↕</span></th>'
            )
        else:
            head.append(f"<th>{escape(str(header))}</th>")
    body = []
    for index, row in enumerate(rows):
        attr = ""
        if row_attrs:
            attrs = row_attrs[index]
            attr = " " + " ".join(
                f'{key}="{escape(str(value), quote=True)}"' for key, value in attrs.items()
            )
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr{attr}>{cells}</tr>")
    return (
        f'<div class="table-wrap {classes}"><table><thead><tr>{"".join(head)}</tr>'
        f'</thead><tbody>{"".join(body)}</tbody></table></div>'
    )


def _time_chart(
    chart_id: str,
    title: str,
    dates: list[str],
    series: list[dict],
    left_title: str,
    left_unit: str = "",
    right_title: str | None = None,
    right_unit: str = "",
    zero_line: bool = False,
    marker: str = "",
) -> str:
    payload = {
        "title": title,
        "dates": dates,
        "series": series,
        "leftAxis": {"title": left_title, "unit": left_unit},
        "rightAxis": {"title": right_title, "unit": right_unit} if right_title else None,
        "zeroLine": zero_line,
    }
    serialized = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f'''<div class="time-chart" data-time-chart="1" id="{escape(chart_id)}" {marker}>
<div class="chart-head"><h3>{escape(title)}</h3><div class="time-chart-legend"></div></div>
<div class="chart-axis-note">左轴：{escape(left_title)}{('（' + escape(left_unit) + '）') if left_unit else ''}{(' ｜ 右轴：' + escape(str(right_title)) + (('（' + escape(right_unit) + '）') if right_unit else '')) if right_title else ''}</div>
<div class="time-chart-canvas"></div>
<div class="time-range"><input class="time-range-start" type="range"><input class="time-range-end" type="range"><span class="time-range-label"></span><button class="time-range-all" type="button">全部</button></div>
<script type="application/json" class="time-chart-config">{serialized}</script></div>'''


def _latest_index_map(report):
    target = report.get("meta", {}).get("report_date")
    return {
        row["name"]: row
        for row in report.get("indices_history", [])
        if row.get("date") == target
    }


def _recent_indices(report):
    names = ["上证50", "Choice微盘", "中证全指"]
    by_date = {}
    for item in report.get("indices_history", []):
        if item.get("name") in names:
            by_date.setdefault(item["date"], {})[item["name"]] = item
    market = {row["date"]: row for row in report.get("market_history", [])}
    dates = sorted(set(by_date) | set(market), reverse=True)[:5]
    rows = []
    for row_date in dates:
        row = [escape(row_date)]
        for name in names:
            item = by_date.get(row_date, {}).get(name, {})
            row.extend([
                f'<span class="{_cls(item.get("return"))}">{_pct(item.get("return"))}</span>',
                _fmt(item.get("amount_100m")),
            ])
        row.append(_fmt(market.get(row_date, {}).get("total_amount_100m")))
        rows.append(row)
    return _table(
        ["日期", "上证50", "成交额", "Choice微盘", "成交额", "中证全指", "成交额", "全A成交额"],
        rows,
    )


def _sw_industry(report):
    rows, attrs = [], []
    for index, item in enumerate(report.get("sw_industry_latest", [])):
        amount = item.get("成交额")
        daily_return = item.get("日收益率")
        volatility = item.get("20日年化波动率")
        rows.append([
            escape(str(item.get("行业层级") or "")),
            escape(str(item.get("一级行业") or "")),
            escape(str(item.get("指数代码") or "")),
            escape(str(item.get("指数名称") or "")),
            _fmt(item.get("收盘价")),
            _fmt(amount),
            f'<span class="{_cls(daily_return)}">{_pct(daily_return)}</span>',
            _pct(volatility, signed=False),
        ])
        attrs.append({
            "data-original-index": index,
            "data-level": str(item.get("行业层级") or ""),
            "data-search": " ".join(
                str(item.get(key) or "")
                for key in ("行业层级", "一级行业", "指数代码", "指数名称")
            ).lower(),
            "data-sort-amount": "" if _num(amount) is None else _num(amount),
            "data-sort-return": "" if _num(daily_return) is None else _num(daily_return),
            "data-sort-volatility": "" if _num(volatility) is None else _num(volatility),
        })
    toolbar = (
        '<div class="toolbar"><input id="swSearch" type="search" placeholder="搜索行业/指数代码…">'
        '<select id="swLevel"><option value="">全部层级</option><option>一级行业</option>'
        '<option>二级行业</option></select><span class="hint">点击成交额 / 日收益率 / '
        '20日年化波动率：原始→降序→升序→原始</span></div>'
    )
    return toolbar + _table(
        ["层级", "一级行业", "指数代码", "指数名称", "收盘", "成交额", "日收益率", "20日年化波动率"],
        rows,
        classes="sw-table",
        row_attrs=attrs,
        sortable={5: "amount", 6: "return", 7: "volatility"},
    )


def _hot_matrix(report):
    matrix = report.get("hot_stock_matrix", {})
    dates = matrix.get("dates", [])
    rows = []
    for item in matrix.get("rows", []):
        rows.append(
            [escape(str(item.get("industry") or ""))]
            + [str(int(value or 0)) for value in item.get("counts", [])]
            + [str(int(item.get("history_total") or 0))]
        )
    return _table(["行业"] + [row_date[5:] for row_date in dates] + ["历史累计"], rows)


def _hot_detail(report):
    rows, attrs = [], []
    for item in report.get("hot_stocks_latest", []):
        rows.append([
            str(item.get("rank") or ""),
            f'<span class="code">{escape(str(item.get("stock_code") or "").zfill(6))}</span>',
            escape(str(item.get("stock_name") or "")),
            _fmt(item.get("close")),
            f'<span class="{_cls(item.get("return"))}">{_pct(item.get("return"))}</span>',
            _fmt(item.get("amount_100m")),
            escape(str(item.get("sw_level1") or "")),
            escape(str(item.get("sw_level2") or "")),
        ])
        attrs.append({"data-hot-row": "1"})
    return _table(
        ["排名", "代码", "名称", "收盘价", "涨跌幅", "成交额(亿元)", "申万一级", "申万二级"],
        rows,
        row_attrs=attrs,
    )


def _market_charts(report):
    rows = [row for row in report.get("market_history", []) if row.get("date")]
    dates = [row["date"] for row in rows]
    marker = ""
    if rows:
        latest = rows[-1]
        marker = (
            f'data-chart-date="{escape(latest["date"])}" '
            f'data-advance="{latest.get("advance")}" data-decline="{latest.get("decline")}" '
            f'data-limit-up="{latest.get("limit_up")}" data-limit-down="{latest.get("limit_down")}"'
        )
    structure_series = [
        {"name": "上涨家数", "values": [row.get("advance") for row in rows], "kind": "bar", "axis": "left", "color": UP, "unit": "家"},
        {"name": "下跌家数", "values": [None if row.get("decline") is None else -row.get("decline") for row in rows], "kind": "bar", "axis": "left", "color": DOWN, "unit": "家"},
        {"name": "涨停家数", "values": [row.get("limit_up") for row in rows], "kind": "line", "axis": "right", "color": UP, "unit": "家"},
        {"name": "跌停家数", "values": [None if row.get("limit_down") is None else -row.get("limit_down") for row in rows], "kind": "line", "axis": "right", "color": DOWN, "unit": "家"},
    ]
    breadth_series = [
        {"name": "市场宽度", "values": [row.get("market_breadth") for row in rows], "kind": "line", "axis": "left", "color": NAVY, "unit": "%"}
    ]
    return (
        _time_chart(
            "market-structure-chart",
            "市场涨跌结构",
            dates,
            structure_series,
            "上涨 / 下跌家数",
            "家",
            "涨停 / 跌停家数",
            "家",
            True,
            marker,
        ),
        _time_chart(
            "market-breadth-chart",
            "市场宽度",
            dates,
            breadth_series,
            "市场宽度",
            "%",
            zero_line=True,
        ),
    )


def _crowding(report):
    history = report.get("sw_crowding_history", [])
    if not history:
        return '<div class="empty">暂无申万四行业拥挤度历史</div>'
    latest = history[-1]
    names = ["通信设备", "计算机设备", "元件", "半导体"]
    rows = []
    for name in names:
        item = latest.get("targets", {}).get(name, {})
        rows.append([
            escape(name),
            _fmt(item.get("amount_100m")),
            _pct(item.get("amount_share_of_a"), signed=False),
            _pct(item.get("turnover"), signed=False),
        ])
    dates = [row["date"] for row in history]
    share_series = []
    turnover_series = []
    for index, name in enumerate(names):
        color = COLORS[index]
        share_series.append({
            "name": f"{name}成交额占全A",
            "values": [row.get("targets", {}).get(name, {}).get("amount_share_of_a") for row in history],
            "kind": "area",
            "axis": "left",
            "color": color,
            "unit": "%",
        })
        turnover_series.append({
            "name": f"{name}换手率",
            "values": [row.get("targets", {}).get(name, {}).get("turnover") for row in history],
            "kind": "line",
            "axis": "left",
            "color": color,
            "unit": "%",
        })
    charts = _time_chart(
        "sw-share-chart",
        "四行业成交额占全A",
        dates,
        share_series,
        "成交额占全部A股",
        "%",
        zero_line=False,
        marker='data-area-chart="crowding-share"',
    )
    charts += _time_chart(
        "sw-turnover-chart",
        "四行业换手率",
        dates,
        turnover_series,
        "换手率",
        "%",
        zero_line=False,
        marker='data-line-chart="crowding-turnover"',
    )
    return (
        f'<div class="subnote">最新官方有效日：{escape(latest["date"])}</div>'
        + _table(["行业", "成交额(亿元)", "占全A", "换手率"], rows)
        + charts
    )


def _innovation(report):
    history = report.get("innovation_history", [])
    if not history:
        return '<div class="empty">暂无创新药历史</div>'
    latest = history[-1]
    summary = _table(
        ["最新日", "成交额(亿元)", "占全A", "换手率", "日收益率", "成交量"],
        [[
            escape(latest["date"]),
            _fmt(latest.get("amount_100m")),
            _pct(latest.get("amount_share_of_a"), signed=False),
            _pct(latest.get("turnover"), signed=False),
            f'<span class="{_cls(latest.get("return"))}">{_pct(latest.get("return"))}</span>',
            _fmt(latest.get("volume"), 0),
        ]],
    )
    dates = [row["date"] for row in history]
    share_series = [{
        "name": "创新药成交额占全A",
        "values": [row.get("amount_share_of_a") for row in history],
        "kind": "area",
        "axis": "left",
        "color": COLORS[0],
        "unit": "%",
    }]
    turnover_series = [{
        "name": "创新药换手率",
        "values": [row.get("turnover") for row in history],
        "kind": "line",
        "axis": "left",
        "color": COLORS[1],
        "unit": "%",
    }]
    return (
        summary
        + _time_chart(
            "innovation-share-chart",
            "创新药成交额占全A",
            dates,
            share_series,
            "成交额占全部A股",
            "%",
            marker='data-area-chart="innovation-share"',
        )
        + _time_chart(
            "innovation-turnover-chart",
            "创新药换手率",
            dates,
            turnover_series,
            "换手率",
            "%",
            marker='data-direct-turnover="innovation"',
        )
    )


def _quality(report):
    quality = report.get("quality", {})
    label_map = {
        "market": "市场核心",
        "indices": "三项指数",
        "sw_industry": "申万行业",
        "sw_crowding": "四行业拥挤度",
        "innovation": "创新药",
    }
    latest_rows = [
        [escape(label_map.get(key, key)), escape(str(value or "—"))]
        for key, value in quality.get("module_latest_dates", {}).items()
    ]
    html = _table(["模块", "最新有效日"], latest_rows)
    canonical = quality.get("canonical_validation") or {}
    html += (
        f'<div class="quality-meta">Canonical：<b>'
        f'{escape(str(canonical.get("status") or "UNKNOWN"))}</b></div>'
    )
    unresolved = quality.get("unresolved", [])
    if unresolved:
        items = "".join(
            f'<li><strong>{escape(str(item.get("module")))}</strong>：'
            f'{escape(json.dumps(item.get("detail"), ensure_ascii=False))}</li>'
            for item in unresolved
        )
        return html + f'<div class="quality-warn"><b>未解决事项</b><ul>{items}</ul></div>'
    return html + '<div class="quality-pass">Canonical 与历史预检未发现未解决关键缺口。</div>'


TABLE_JS = r'''
(function(){
function applySw(){
  const table=document.querySelector('.sw-table table'); if(!table)return;
  const body=table.querySelector('tbody');
  const search=(document.querySelector('#swSearch')?.value||'').trim().toLowerCase();
  const level=document.querySelector('#swLevel')?.value||'';
  let rows=Array.from(body.querySelectorAll('tr'));
  const active=table.querySelector('th.sortable[data-sort-state="desc"],th.sortable[data-sort-state="asc"]');
  if(active){
    const field=active.dataset.sortField,state=active.dataset.sortState;
    const key='sort'+field.charAt(0).toUpperCase()+field.slice(1);
    rows.sort((a,b)=>{
      const av=Number(a.dataset[key]),bv=Number(b.dataset[key]);
      const aok=a.dataset[key]!==''&&Number.isFinite(av),bok=b.dataset[key]!==''&&Number.isFinite(bv);
      if(!aok&&!bok)return Number(a.dataset.originalIndex)-Number(b.dataset.originalIndex);
      if(!aok)return 1;if(!bok)return -1;
      return state==='desc'?bv-av:av-bv;
    });
  }else{
    rows.sort((a,b)=>Number(a.dataset.originalIndex)-Number(b.dataset.originalIndex));
  }
  rows.forEach(row=>{
    body.appendChild(row);
    row.style.display=(!search||row.dataset.search.includes(search))&&(!level||row.dataset.level===level)?'':'none';
  });
}
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelector('#swSearch')?.addEventListener('input',applySw);
  document.querySelector('#swLevel')?.addEventListener('change',applySw);
  document.querySelectorAll('.sw-table th.sortable').forEach(th=>th.addEventListener('click',()=>{
    const order=['original','desc','asc'];
    const next=order[(order.indexOf(th.dataset.sortState)+1)%3];
    document.querySelectorAll('.sw-table th.sortable').forEach(other=>{
      if(other!==th){other.dataset.sortState='original';other.querySelector('.sort-ind').textContent='↕';}
    });
    th.dataset.sortState=next;
    th.querySelector('.sort-ind').textContent=next==='desc'?'↓':next==='asc'?'↑':'↕';
    applySw();
  }));
});
})();
'''


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
    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-label">{escape(label)}</div>'
        f'<div class="kpi-value {css_class}">{escape(value)}</div></div>'
        for label, value, css_class in kpis
    )
    sw_latest = report.get("quality", {}).get("module_latest_dates", {}).get("sw_industry") or "—"
    hot_count = len(report.get("hot_stocks_latest", []))
    market_structure, market_breadth = _market_charts(report)
    chart_runtime = CHART_RUNTIME_PATH.read_text(encoding="utf-8")
    style = f'''
:root{{--navy:{NAVY};--text:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#f4f7fb;--up:{UP};--down:{DOWN}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",Arial,sans-serif;font-size:14px}}
.page{{max-width:1500px;margin:auto;padding:18px 22px 56px}}.hero{{background:linear-gradient(135deg,#123d68,#174f82);color:#fff;padding:24px 28px;border-radius:12px}}.hero-top{{display:flex;justify-content:space-between;gap:20px}}h1{{margin:0;font-size:26px}}.meta{{margin-top:8px;color:#dbeafe}}.status{{padding:7px 12px;border-radius:999px;font-weight:700;background:#ffffff1c;border:1px solid #ffffff40;height:max-content}}
.kpis{{display:grid;grid-template-columns:repeat(6,minmax(140px,1fr));gap:12px;margin:16px 0}}.kpi,.card{{background:#fff;border:1px solid var(--line)}}.kpi{{padding:14px 16px;border-radius:10px}}.kpi-label{{font-size:12px;color:var(--muted)}}.kpi-value{{font-size:23px;font-weight:750;margin-top:5px}}.up{{color:var(--up)}}.down{{color:var(--down)}}.neutral{{color:#0f172a}}
.section{{margin-top:18px}}.section-title{{background:var(--navy);color:#fff;border-radius:9px 9px 0 0;padding:10px 14px;font-size:17px;font-weight:700}}.card{{border-radius:0 0 10px 10px;padding:14px 16px}}.time-chart{{background:#fff;border:1px solid var(--line);border-radius:9px;padding:12px;margin-top:12px}}.chart-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}.chart-head h3{{margin:2px 4px;font-size:15px}}.time-chart-legend{{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}}.chart-legend-item{{border:0;background:#f8fafc;padding:4px 7px;border-radius:5px;cursor:pointer;color:#334155}}.chart-legend-item.muted{{opacity:.35;text-decoration:line-through}}.legend-swatch{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}}.chart-axis-note,.subnote,.hint{{font-size:12px;color:var(--muted)}}.time-chart-canvas{{overflow:auto;margin-top:4px}}.chart-svg{{width:100%;height:auto;display:block;min-width:720px}}.chart-grid-two .chart-svg{{min-width:0;width:100%}}.axis-label{{font-size:11px;fill:#64748b}}.axis-title{{font-size:11px;fill:#475569;font-weight:600}}.chart-empty{{padding:36px;text-align:center;color:var(--muted)}}
.time-range{{display:grid;grid-template-columns:1fr 1fr auto auto;gap:8px;align-items:center;padding:5px 8px 2px}}.time-range input[type=range]{{width:100%;accent-color:#2563eb}}.time-range-label{{min-width:190px;text-align:right;color:#64748b;font-size:12px}}.time-range-all{{border:1px solid #cbd5e1;background:#fff;border-radius:5px;padding:4px 9px;cursor:pointer}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:8px;margin-top:10px;background:#fff}}.sw-table{{max-height:900px;overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:760px}}th{{background:#f1f5f9;color:#334155;font-weight:650;position:sticky;top:0;z-index:1}}th,td{{padding:8px 10px;border-bottom:1px solid #e8edf3;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}tbody tr:hover{{background:#f8fafc}}th.sortable{{cursor:pointer}}.sort-ind{{margin-left:4px;color:#64748b}}.code{{font-family:Consolas,monospace}}.toolbar{{display:flex;gap:8px;align-items:center;margin:6px 0 9px;flex-wrap:wrap}}.toolbar input,.toolbar select{{border:1px solid #cbd5e1;border-radius:6px;padding:7px 9px;background:#fff}}
.quality-warn{{margin-top:12px;padding:12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px}}.quality-pass{{margin-top:12px;padding:12px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px}}.quality-meta{{margin-top:10px}}.empty{{padding:22px;text-align:center;color:var(--muted)}}
@media(max-width:1100px){{.kpis{{grid-template-columns:repeat(3,1fr)}}}}@media(max-width:650px){{.page{{padding:10px}}.kpis{{grid-template-columns:repeat(2,1fr)}}.hero-top{{display:block}}.time-range{{grid-template-columns:1fr 1fr auto}}.time-range-label{{display:none}}}}
'''
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股每日市场监控 {escape(target)}</title><style>{style}</style></head><body><div class="page">
<header class="hero"><div class="hero-top"><div><h1>A股每日市场监控</h1><div class="meta">报告日期 {escape(target)} ｜ 申万行业最新有效日 {escape(str(sw_latest))} ｜ 单文件离线报告</div></div><div class="status {status_class}">数据状态 {escape(status)}</div></div></header><div class="kpis">{kpi_html}</div>
<section class="section"><div class="section-title">00｜市场总览 · 市场涨跌结构</div><div class="card"><div class="subnote">默认展示全历史；每张时间图底部均可独立拖动起止时间，点击“全部”恢复全历史。</div>{market_structure}</div></section>
<section class="section"><div class="section-title">00｜市场总览 · 市场宽度</div><div class="card">{market_breadth}</div></section>
<section class="section"><div class="section-title">00｜市场总览 · 最近交易日指数与成交</div><div class="card">{_recent_indices(report)}</div></section>
<section class="section"><div class="section-title">01｜申万行业</div><div class="card"><div class="subnote">完整展示最新快照；成交额、日收益率、20日年化波动率支持三态排序。</div>{_sw_industry(report)}</div></section>
<section class="section"><div class="section-title">04｜百亿成交</div><div class="card"><h3>最近10个有记录交易日｜最新日期在左</h3>{_hot_matrix(report)}<h3 style="margin-top:18px">{escape(target)} 成交额超过100亿元个股｜完整明细 {hot_count} 只</h3>{_hot_detail(report)}</div></section>
<section class="section"><div class="section-title">05｜申万四行业资金拥挤度</div><div class="card">{_crowding(report)}</div></section>
<section class="section"><div class="section-title">06｜创新药交易拥挤度</div><div class="card"><div class="subnote">成交额占全A使用面积图；换手率只使用供应商直接板块换手率。</div>{_innovation(report)}</div></section>
<section class="section"><div class="section-title">99｜数据质量</div><div class="card">{_quality(report)}</div></section></div><script>{chart_runtime}</script><script>{TABLE_JS}</script></body></html>'''


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
