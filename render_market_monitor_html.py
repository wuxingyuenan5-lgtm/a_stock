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
    for i, h in enumerate(headers):
        if i in sortable:
            field = sortable[i]
            head.append(f'<th class="sortable" data-sort-field="{escape(field)}" data-sort-state="original">{escape(str(h))}<span class="sort-ind">↕</span></th>')
        else:
            head.append(f"<th>{escape(str(h))}</th>")
    body = []
    for idx, row in enumerate(rows):
        attr = ""
        if row_attrs:
            attrs = row_attrs[idx]
            attr = " " + " ".join(f'{k}="{escape(str(v), quote=True)}"' for k, v in attrs.items())
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr{attr}>{cells}</tr>")
    return f'<div class="table-wrap {classes}"><table><thead><tr>{"".join(head)}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _chart(title, dates, series, y_label="", chart_type="series", right_label="", marker=""):
    payload = {"title": title, "dates": dates, "series": series, "yLabel": y_label, "rightLabel": right_label, "chartType": chart_type}
    n = max(0, len(dates) - 1)
    return f'''<div class="time-chart" data-time-chart="1" data-range-start="0" data-range-end="{n}" {marker}>
<div class="chart-head"><h3>{escape(title)}</h3><div class="chart-legend"></div></div>
<div class="chart-axis-note">{escape(y_label)}{(' ｜ 右轴：' + escape(right_label)) if right_label else ''}</div>
<div class="chart-stage"><svg class="chart-svg" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg><div class="chart-tooltip"></div></div>
<div class="range-wrap"><button type="button" class="range-reset">全部</button><div class="range-track"><div class="range-selection"></div><input class="range-input range-start" type="range" min="0" max="{n}" value="0"><input class="range-input range-end" type="range" min="0" max="{n}" value="{n}"></div><span class="range-label"></span></div>
<script type="application/json" class="chart-data">{escape(json.dumps(payload, ensure_ascii=False), quote=False)}</script></div>'''


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
    rows, attrs = [], []
    for idx, r in enumerate(report.get("sw_industry_latest", [])):
        amount, ret, vol = r.get("成交额"), r.get("日收益率"), r.get("20日年化波动率")
        rows.append([
            escape(str(r.get("行业层级") or "")), escape(str(r.get("一级行业") or "")),
            escape(str(r.get("指数代码") or "")), escape(str(r.get("指数名称") or "")),
            _fmt(r.get("收盘价")), _fmt(amount),
            f'<span class="{_cls(ret)}">{_pct(ret)}</span>', _pct(vol, signed=False),
        ])
        attrs.append({
            "data-original-index": idx,
            "data-level": str(r.get("行业层级") or ""),
            "data-search": " ".join(str(r.get(k) or "") for k in ("行业层级", "一级行业", "指数代码", "指数名称")).lower(),
            "data-sort-amount": "" if _num(amount) is None else _num(amount),
            "data-sort-return": "" if _num(ret) is None else _num(ret),
            "data-sort-volatility": "" if _num(vol) is None else _num(vol),
        })
    toolbar = '<div class="toolbar"><input id="swSearch" type="search" placeholder="搜索行业/指数代码…"><select id="swLevel"><option value="">全部层级</option><option>一级行业</option><option>二级行业</option></select><span class="hint">点击成交额 / 日收益率 / 20日年化波动率：原始→降序→升序→原始</span></div>'
    return toolbar + _table(
        ["层级", "一级行业", "指数代码", "指数名称", "收盘", "成交额", "日收益率", "20日年化波动率"],
        rows, classes="sw-table", row_attrs=attrs, sortable={5: "amount", 6: "return", 7: "volatility"}
    )


def _hot_matrix(report):
    matrix = report.get("hot_stock_matrix", {})
    dates = matrix.get("dates", [])
    rows = [[escape(str(r.get("industry") or ""))] + [str(int(x or 0)) for x in r.get("counts", [])] + [str(int(r.get("history_total") or 0))] for r in matrix.get("rows", [])]
    return _table(["行业"] + [d[5:] for d in dates] + ["历史累计"], rows)


def _hot_detail(report):
    rows, attrs = [], []
    for r in report.get("hot_stocks_latest", []):
        rows.append([
            str(r.get("rank") or ""), f'<span class="code">{escape(str(r.get("stock_code") or "").zfill(6))}</span>',
            escape(str(r.get("stock_name") or "")), _fmt(r.get("close")),
            f'<span class="{_cls(r.get("return"))}">{_pct(r.get("return"))}</span>', _fmt(r.get("amount_100m")),
            escape(str(r.get("sw_level1") or "")), escape(str(r.get("sw_level2") or "")),
        ])
        attrs.append({"data-hot-row": "1"})
    return _table(["排名", "代码", "名称", "收盘价", "涨跌幅", "成交额(亿元)", "申万一级", "申万二级"], rows, row_attrs=attrs)


def _market_charts(report):
    rows = [r for r in report.get("market_history", []) if r.get("date")]
    dates = [r["date"] for r in rows]
    marker = ""
    if rows:
        last = rows[-1]
        marker = f'data-chart-date="{escape(last["date"])}" data-advance="{last.get("advance")}" data-decline="{last.get("decline")}" data-limit-up="{last.get("limit_up")}" data-limit-down="{last.get("limit_down")}"'
    structure_series = [
        {"name": "上涨家数", "values": [r.get("advance") for r in rows], "type": "bar", "axis": "left", "color": UP, "sign": 1, "unit": "家"},
        {"name": "下跌家数", "values": [r.get("decline") for r in rows], "type": "bar", "axis": "left", "color": DOWN, "sign": -1, "unit": "家"},
        {"name": "涨停家数", "values": [r.get("limit_up") for r in rows], "type": "line", "axis": "right", "color": UP, "sign": 1, "unit": "家"},
        {"name": "跌停家数", "values": [r.get("limit_down") for r in rows], "type": "line", "axis": "right", "color": DOWN, "sign": -1, "unit": "家"},
    ]
    width_series = [{"name": "市场宽度", "values": [r.get("market_breadth") for r in rows], "type": "line", "axis": "left", "color": NAVY, "unit": "%", "percent": True}]
    return (
        _chart("市场涨跌结构", dates, structure_series, "上涨/下跌家数（家）", "market", "涨停/跌停家数（家）", marker),
        _chart("市场宽度", dates, width_series, "市场宽度（%）", "series")
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
        rows.append([escape(name), _fmt(item.get("amount_100m")), _pct(item.get("amount_share_of_a"), signed=False), _pct(item.get("turnover"), signed=False)])
    dates = [r["date"] for r in history]
    share_series, turnover_series = [], []
    for i, name in enumerate(names):
        color = COLORS[i]
        share_series.append({"name": name, "values": [r.get("targets", {}).get(name, {}).get("amount_share_of_a") for r in history], "type": "area", "axis": "left", "color": color, "unit": "%", "percent": True, "opacity": 0.16})
        turnover_series.append({"name": name, "values": [r.get("targets", {}).get(name, {}).get("turnover") for r in history], "type": "line", "axis": "left", "color": color, "unit": "%", "percent": True})
    charts = _chart("四行业成交额占全A", dates, share_series, "成交额占全部A股（%）", "series", marker='data-area-chart="crowding-share"')
    charts += _chart("四行业换手率", dates, turnover_series, "换手率（%）", "series", marker='data-line-chart="crowding-turnover"')
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
    dates = [r["date"] for r in history]
    share_series = [{"name": "创新药成交额占全A", "values": [r.get("amount_share_of_a") for r in history], "type": "area", "axis": "left", "color": COLORS[0], "unit": "%", "percent": True, "opacity": 0.2}]
    turnover_series = [{"name": "创新药换手率", "values": [r.get("turnover") for r in history], "type": "line", "axis": "left", "color": COLORS[1], "unit": "%", "percent": True}]
    return summary + _chart("创新药成交额占全A", dates, share_series, "成交额占全部A股（%）", "series", marker='data-area-chart="innovation-share"') + _chart("创新药换手率", dates, turnover_series, "换手率（%）", "series", marker='data-direct-turnover="innovation"')


def _quality(report):
    quality = report.get("quality", {})
    label_map = {"market": "市场核心", "indices": "三项指数", "sw_industry": "申万行业", "sw_crowding": "四行业拥挤度", "innovation": "创新药"}
    latest_rows = [[escape(label_map.get(k, k)), escape(str(v or "—"))] for k, v in quality.get("module_latest_dates", {}).items()]
    html = _table(["模块", "最新有效日"], latest_rows)
    canonical = quality.get("canonical_validation") or {}
    html += f'<div class="quality-meta">Canonical：<b>{escape(str(canonical.get("status") or "UNKNOWN"))}</b></div>'
    unresolved = quality.get("unresolved", [])
    if unresolved:
        items = "".join(f'<li><strong>{escape(str(x.get("module")))}</strong>：{escape(json.dumps(x.get("detail"), ensure_ascii=False))}</li>' for x in unresolved)
        return html + f'<div class="quality-warn"><b>未解决事项</b><ul>{items}</ul></div>'
    return html + '<div class="quality-pass">Canonical 与历史预检未发现未解决关键缺口。</div>'


CHART_JS = r'''
(function(){
const NS='http://www.w3.org/2000/svg';
const q=(e,s)=>e.querySelector(s), qa=(e,s)=>Array.from(e.querySelectorAll(s));
function fmt(v,s){if(v==null||Number.isNaN(Number(v)))return '—';const n=Number(v);if(s.percent)return (n*100).toFixed(2)+'%';return n.toLocaleString(undefined,{maximumFractionDigits:4})+(s.unit?' '+s.unit:'');}
function svgEl(name,attrs={}){const e=document.createElementNS(NS,name);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));return e;}
function initChart(root){
  const cfg=JSON.parse(q(root,'.chart-data').textContent); const svg=q(root,'svg'); const tip=q(root,'.chart-tooltip');
  const a=q(root,'.range-start'), b=q(root,'.range-end'), sel=q(root,'.range-selection'), label=q(root,'.range-label');
  const legends=q(root,'.chart-legend'); let hidden=new Set(); let drag=null;
  cfg.series.forEach((s,i)=>{const btn=document.createElement('button');btn.type='button';btn.className='legend-btn';btn.innerHTML='<span style="background:'+s.color+'"></span>'+s.name;btn.onclick=()=>{hidden.has(i)?hidden.delete(i):hidden.add(i);btn.classList.toggle('off',hidden.has(i));draw()};legends.appendChild(btn)});
  function clamp(){let x=+a.value,y=+b.value;if(x>y){if(document.activeElement===a)a.value=y;else b.value=x} root.dataset.rangeStart=a.value;root.dataset.rangeEnd=b.value;}
  function updateSel(){const max=Math.max(1,+a.max),l=+a.value/max*100,r=+b.value/max*100;sel.style.left=l+'%';sel.style.width=Math.max(0,r-l)+'%';label.textContent=(cfg.dates[+a.value]||'')+' — '+(cfg.dates[+b.value]||'');}
  function domain(series,start,end,axis){let vals=[];series.forEach((s,i)=>{if(hidden.has(i)||s.axis!==axis)return;(s.values||[]).slice(start,end+1).forEach(v=>{if(v!=null){let n=Number(v)*(s.sign||1);if(Number.isFinite(n))vals.push(n)}})});if(!vals.length)return [-1,1];let lo=Math.min(...vals),hi=Math.max(...vals);if(cfg.chartType==='market'||lo<0) {lo=Math.min(lo,0);hi=Math.max(hi,0)};if(lo===hi){lo-=1;hi+=1}const pad=(hi-lo)*.08;return[lo-pad,hi+pad]}
  function draw(){clamp();updateSel();svg.innerHTML='';const start=+a.value,end=+b.value,n=Math.max(1,end-start);const W=1200,H=360,ml=72,mr=cfg.rightLabel?92:38,mt=24,mb=48,x0=ml,x1=W-mr,y0=mt,y1=H-mb;
    const dl=domain(cfg.series,start,end,'left'),dr=domain(cfg.series,start,end,'right'); const X=i=>x0+(x1-x0)*(i-start)/n; const Y=(v,d)=>y1-(v-d[0])/(d[1]-d[0])*(y1-y0);
    for(let k=0;k<5;k++){let yy=y0+(y1-y0)*k/4;svg.appendChild(svgEl('line',{x1:x0,y1:yy,x2:x1,y2:yy,stroke:'#e2e8f0'}));let lv=dl[1]-(dl[1]-dl[0])*k/4;let t=svgEl('text',{x:x0-8,y:yy+4,'text-anchor':'end',class:'axis-label'});t.textContent=(cfg.yLabel.includes('%')?(lv*100).toFixed(1)+'%':lv.toFixed(0));svg.appendChild(t);if(cfg.rightLabel){let rv=dr[1]-(dr[1]-dr[0])*k/4;let tr=svgEl('text',{x:x1+10,y:yy+4,class:'axis-label'});tr.textContent=rv.toFixed(0);svg.appendChild(tr)}}
    const labelIdx=[];for(let k=0;k<8;k++)labelIdx.push(Math.round(start+(end-start)*k/7));[...new Set(labelIdx)].forEach(i=>{let t=svgEl('text',{x:X(i),y:H-15,'text-anchor':i===start?'start':i===end?'end':'middle',class:'axis-label'});t.textContent=(cfg.dates[i]||'').slice(5);svg.appendChild(t)});
    cfg.series.forEach((s,si)=>{if(hidden.has(si))return;const d=s.axis==='right'?dr:dl;let pts=[];for(let i=start;i<=end;i++){let raw=s.values[i];if(raw==null)continue;let v=Number(raw)*(s.sign||1),x=X(i),y=Y(v,d);pts.push([x,y,i,raw]);if(s.type==='bar'){let z=Y(0,d),bw=Math.max(2,Math.min(10,(x1-x0)/(n+1)*.55));svg.appendChild(svgEl('rect',{x:x-bw/2,y:Math.min(y,z),width:bw,height:Math.max(1,Math.abs(z-y)),fill:s.color,opacity:.25,'data-point':i,'data-series':si}))}}
      if(s.type==='line'||s.type==='area'){if(!pts.length)return;let dstr=pts.map((p,j)=>(j?'L':'M')+p[0]+','+p[1]).join(' ');if(s.type==='area'){let base=Y(0>=d[0]&&0<=d[1]?0:d[0],d);let area=dstr+' L'+pts[pts.length-1][0]+','+base+' L'+pts[0][0]+','+base+' Z';svg.appendChild(svgEl('path',{d:area,fill:s.color,opacity:s.opacity||.16,'data-area-series':s.name}))}svg.appendChild(svgEl('path',{d:dstr,fill:'none',stroke:s.color,'stroke-width':2.2,'data-line-series':s.name}));pts.forEach(p=>svg.appendChild(svgEl('circle',{cx:p[0],cy:p[1],r:2.2,fill:s.color,'data-point':p[2],'data-series':si})))}
    });
    svg.onmousemove=(ev)=>{const rect=svg.getBoundingClientRect();let px=(ev.clientX-rect.left)/rect.width*W;let idx=Math.round(start+(px-x0)/(x1-x0)*(end-start));idx=Math.max(start,Math.min(end,idx));let lines=['<b>'+cfg.dates[idx]+'</b>'];cfg.series.forEach((s,i)=>{if(!hidden.has(i))lines.push('<span style="color:'+s.color+'">●</span> '+s.name+'：'+fmt(s.values[idx],s))});tip.innerHTML=lines.join('<br>');tip.style.display='block';tip.style.left=Math.min(rect.width-220,Math.max(8,ev.clientX-rect.left+12))+'px';tip.style.top='12px'};svg.onmouseleave=()=>tip.style.display='none';
  }
  a.oninput=b.oninput=draw; q(root,'.range-reset').onclick=()=>{a.value=0;b.value=b.max;draw()};
  sel.onpointerdown=e=>{drag={x:e.clientX,a:+a.value,b:+b.value};sel.setPointerCapture(e.pointerId)};sel.onpointermove=e=>{if(!drag)return;let width=q(root,'.range-track').getBoundingClientRect().width||1,max=+a.max,shift=Math.round((e.clientX-drag.x)/width*max),span=drag.b-drag.a,na=Math.max(0,Math.min(max-span,drag.a+shift));a.value=na;b.value=na+span;draw()};sel.onpointerup=()=>drag=null;sel.onpointercancel=()=>drag=null;draw();
}
qa(document,'[data-time-chart="1"]').forEach(initChart);
function applySw(){const table=q(document,'.sw-table table');if(!table)return;const body=q(table,'tbody'),search=(q(document,'#swSearch')?.value||'').trim().toLowerCase(),level=q(document,'#swLevel')?.value||'';let rows=qa(body,'tr');const active=q(table,'th.sortable[data-sort-state="desc"],th.sortable[data-sort-state="asc"]');if(active){let field=active.dataset.sortField,state=active.dataset.sortState;rows.sort((a,b)=>{let av=Number(a.dataset['sort'+field.charAt(0).toUpperCase()+field.slice(1)]),bv=Number(b.dataset['sort'+field.charAt(0).toUpperCase()+field.slice(1)]),an=Number.isFinite(av),bn=Number.isFinite(bv);if(!an&&!bn)return +a.dataset.originalIndex-+b.dataset.originalIndex;if(!an)return 1;if(!bn)return -1;return state==='desc'?bv-av:av-bv})}else rows.sort((a,b)=>+a.dataset.originalIndex-+b.dataset.originalIndex);rows.forEach(r=>{body.appendChild(r);r.style.display=(!search||r.dataset.search.includes(search))&&(!level||r.dataset.level===level)?'':'none'})}
q(document,'#swSearch')?.addEventListener('input',applySw);q(document,'#swLevel')?.addEventListener('change',applySw);qa(document,'.sw-table th.sortable').forEach(th=>th.addEventListener('click',()=>{const order=['original','desc','asc'];let next=order[(order.indexOf(th.dataset.sortState)+1)%3];qa(document,'.sw-table th.sortable').forEach(x=>{if(x!==th){x.dataset.sortState='original';q(x,'.sort-ind').textContent='↕'}});th.dataset.sortState=next;q(th,'.sort-ind').textContent=next==='desc'?'↓':next==='asc'?'↑':'↕';applySw()}));
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
    kpi_html = "".join(f'<div class="kpi"><div class="kpi-label">{escape(label)}</div><div class="kpi-value {css}">{escape(value)}</div></div>' for label, value, css in kpis)
    sw_latest = report.get("quality", {}).get("module_latest_dates", {}).get("sw_industry") or "—"
    hot_count = len(report.get("hot_stocks_latest", []))
    market_structure, market_width = _market_charts(report)
    style = f'''
:root{{--navy:{NAVY};--text:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#f4f7fb;--up:{UP};--down:{DOWN}}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",Arial,sans-serif;font-size:14px}}.page{{max-width:1500px;margin:auto;padding:18px 22px 56px}}.hero{{background:linear-gradient(135deg,#123d68,#174f82);color:#fff;padding:24px 28px;border-radius:12px}}.hero-top{{display:flex;justify-content:space-between;gap:20px}}h1{{margin:0;font-size:26px}}.meta{{margin-top:8px;color:#dbeafe}}.status{{padding:7px 12px;border-radius:999px;font-weight:700;background:#ffffff1c;border:1px solid #ffffff40;height:max-content}}.kpis{{display:grid;grid-template-columns:repeat(6,minmax(140px,1fr));gap:12px;margin:16px 0}}.kpi,.card{{background:#fff;border:1px solid var(--line)}}.kpi{{padding:14px 16px;border-radius:10px}}.kpi-label{{font-size:12px;color:var(--muted)}}.kpi-value{{font-size:23px;font-weight:750;margin-top:5px}}.up{{color:var(--up)}}.down{{color:var(--down)}}.neutral{{color:#0f172a}}.section{{margin-top:18px}}.section-title{{background:var(--navy);color:#fff;border-radius:9px 9px 0 0;padding:10px 14px;font-size:17px;font-weight:700}}.card{{border-radius:0 0 10px 10px;padding:14px 16px}}.time-chart{{background:#fff;border:1px solid var(--line);border-radius:9px;padding:10px;margin-top:12px}}.chart-head{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.chart-head h3{{margin:3px 4px;font-size:15px}}.chart-legend{{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}}.legend-btn{{border:0;background:#f8fafc;padding:4px 7px;border-radius:5px;cursor:pointer;color:#334155}}.legend-btn span{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}}.legend-btn.off{{opacity:.35;text-decoration:line-through}}.chart-axis-note,.subnote,.hint{{font-size:12px;color:var(--muted)}}.chart-stage{{position:relative;overflow:auto}}.chart-svg{{width:100%;height:auto;display:block;min-width:720px}}.axis-label{{font-size:11px;fill:#64748b}}.chart-tooltip{{display:none;position:absolute;z-index:4;min-width:180px;background:#0f172ae8;color:#fff;padding:8px 10px;border-radius:7px;pointer-events:none;font-size:12px;line-height:1.55}}.range-wrap{{display:flex;align-items:center;gap:10px;padding:2px 8px 5px}}.range-reset{{border:1px solid #cbd5e1;background:#fff;border-radius:5px;padding:4px 9px;cursor:pointer}}.range-track{{height:26px;position:relative;flex:1}}.range-selection{{position:absolute;left:0;top:8px;height:8px;background:#94a3b866;border-radius:5px;cursor:grab;z-index:2}}.range-input{{position:absolute;width:100%;left:0;top:0;background:transparent;pointer-events:none;appearance:none}}.range-input::-webkit-slider-thumb{{appearance:none;width:14px;height:20px;background:#2563eb;border-radius:4px;pointer-events:auto;cursor:ew-resize}}.range-input::-moz-range-thumb{{width:14px;height:20px;background:#2563eb;border:0;border-radius:4px;pointer-events:auto;cursor:ew-resize}}.range-label{{min-width:190px;text-align:right;color:#64748b;font-size:12px}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:8px;margin-top:10px;background:#fff}}.sw-table{{max-height:900px}}table{{border-collapse:collapse;width:100%;min-width:760px}}th{{background:#f1f5f9;color:#334155;font-weight:650;position:sticky;top:0;z-index:1}}th,td{{padding:8px 10px;border-bottom:1px solid #e8edf3;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}tbody tr:hover{{background:#f8fafc}}th.sortable{{cursor:pointer}}.sort-ind{{margin-left:4px;color:#64748b}}.code{{font-family:Consolas,monospace}}.toolbar{{display:flex;gap:8px;align-items:center;margin:6px 0 9px;flex-wrap:wrap}}.toolbar input,.toolbar select{{border:1px solid #cbd5e1;border-radius:6px;padding:7px 9px;background:#fff}}.quality-warn{{margin-top:12px;padding:12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px}}.quality-pass{{margin-top:12px;padding:12px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px}}.quality-meta{{margin-top:10px}}.empty{{padding:22px;text-align:center;color:var(--muted)}}@media(max-width:1100px){{.kpis{{grid-template-columns:repeat(3,1fr)}}}}@media(max-width:650px){{.page{{padding:10px}}.kpis{{grid-template-columns:repeat(2,1fr)}}.hero-top{{display:block}}.range-label{{display:none}}}}
'''
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股每日市场监控 {escape(target)}</title><style>{style}</style></head><body><div class="page">
<header class="hero"><div class="hero-top"><div><h1>A股每日市场监控</h1><div class="meta">报告日期 {escape(target)} ｜ 申万行业最新有效日 {escape(str(sw_latest))} ｜ 单文件离线报告</div></div><div class="status {status_class}">数据状态 {escape(status)}</div></div></header><div class="kpis">{kpi_html}</div>
<section class="section"><div class="section-title">00｜市场总览 · 市场涨跌结构</div><div class="card"><div class="subnote">默认展示全历史；底部滚轴可拖动左右边界或整体选区。上涨/下跌家数左轴，涨停/跌停家数右轴。</div>{market_structure}</div></section>
<section class="section"><div class="section-title">00｜市场总览 · 市场宽度</div><div class="card">{market_width}</div></section>
<section class="section"><div class="section-title">00｜市场总览 · 最近交易日指数与成交</div><div class="card">{_recent_indices(report)}</div></section>
<section class="section"><div class="section-title">01｜申万行业</div><div class="card"><div class="subnote">完整展示最新快照；成交额、日收益率、20日年化波动率支持三态排序。</div>{_sw_industry(report)}</div></section>
<section class="section"><div class="section-title">04｜百亿成交</div><div class="card"><h3>最近10个有记录交易日｜最新日期在左</h3>{_hot_matrix(report)}<h3 style="margin-top:18px">{escape(target)} 成交额超过100亿元个股｜完整明细 {hot_count} 只</h3>{_hot_detail(report)}</div></section>
<section class="section"><div class="section-title">05｜申万四行业资金拥挤度</div><div class="card">{_crowding(report)}</div></section>
<section class="section"><div class="section-title">06｜创新药交易拥挤度</div><div class="card"><div class="subnote">成交额占全A使用面积图；换手率只使用供应商直接板块换手率。</div>{_innovation(report)}</div></section>
<section class="section"><div class="section-title">99｜数据质量</div><div class="card">{_quality(report)}</div></section></div><script>{CHART_JS}</script></body></html>'''


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
