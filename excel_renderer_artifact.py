#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from artifact_tool import Blob, SpreadsheetFile

VERSION = "1.0"


def jload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def serial(text: str) -> int:
    return (datetime.strptime(text, "%Y-%m-%d").date() - date(1899, 12, 30)).days


def as_date(value) -> date:
    return date(1899, 12, 30) + timedelta(days=int(value))


def nrows(sheet, start: int, maximum: int = 2000) -> int:
    n = 0
    for row in sheet.get_range(f"A{start}:A{maximum}").values:
        if row[0] in (None, ""):
            break
        n += 1
    return n


def grow_style(sheet, start: int, old_n: int, new_n: int, end_col: str) -> None:
    if new_n <= old_n or old_n <= 0:
        return
    source_row = start + old_n - 1
    source = sheet.get_range(f"A{source_row}:{end_col}{source_row}")
    for row in range(start + old_n, start + new_n):
        sheet.get_range(f"A{row}:{end_col}{row}").copy_from(source, "all")


def clear_tail(sheet, start: int, old_n: int, new_n: int, end_col: str, cols: int) -> None:
    if new_n >= old_n:
        return
    r0, r1 = start + new_n, start + old_n - 1
    sheet.get_range(f"A{r0}:{end_col}{r1}").values = [[None] * cols for _ in range(r1 - r0 + 1)]


def template_check(path: Path, cfg: dict):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != cfg["template"]["sha256"]:
        raise RuntimeError(f"template sha256 mismatch: {digest}")
    wb = SpreadsheetFile.import_xlsx(Blob.load(str(path)))
    actual = []
    for line in wb.inspect({"kind": "sheet", "include": "id,name"}).ndjson.splitlines():
        if line.strip():
            actual.append(json.loads(line)["name"])
    missing = [x for x in cfg["template"]["required_sheets"] if x not in actual]
    if missing:
        raise RuntimeError(f"template missing sheets: {missing}")
    return wb, digest


def status_text(payload: dict, validation: dict, manifest: dict) -> str:
    warns = [x["name"] for x in validation.get("checks", []) if not x.get("ok")]
    src = (manifest.get("sources") or {}).get("a_share_snapshot", "")
    return f"{payload['date']} GitHub生产包；核心市场={validation.get('status')}; A股={src}; WARN={','.join(warns) if warns else '无'}"


def upsert_02(wb, payload: dict, validation: dict, manifest: dict) -> None:
    sh = wb.worksheets.get_item("02_统一历史数据")
    old_n = nrows(sh, 6, 1000)
    raw = sh.get_range(f"A6:O{5 + old_n}").values
    states = [[x[0]] for x in sh.get_range(f"T6:T{5 + old_n}").values]
    target = serial(payload["date"])
    idx = next((i for i, row in enumerate(raw) if row[0] == target), None)
    oldrow = raw[idx] if idx is not None else [None] * 15
    indices = payload.get("indices") or {}

    def iv(name: str, key: str, pos: int):
        value = (indices.get(name) or {}).get(key)
        return oldrow[pos] if value is None and idx is not None else value

    m = payload["market"]
    row = [
        target,
        iv("上证50", "return", 1), iv("Choice微盘", "return", 2), iv("中证全指", "return", 3),
        iv("上证50", "amount_100m", 4), iv("Choice微盘", "amount_100m", 5), iv("中证全指", "amount_100m", 6),
        m.get("total_amount_100m"), m.get("advance"), m.get("decline"), m.get("flat"),
        m.get("limit_up"), m.get("limit_down"), m.get("hot_count"), m.get("hot_amount_100m"),
    ]
    state = status_text(payload, validation, manifest)
    if idx is None:
        raw, states = [row] + raw, [[state]] + states
    else:
        raw[idx], states[idx] = row, [state]
    packed = sorted(zip(raw, states), key=lambda pair: -(pair[0][0] or 0))
    raw, states = [x[0] for x in packed], [x[1] for x in packed]
    new_n = len(raw)
    grow_style(sh, 6, old_n, new_n, "T")
    sh.get_range(f"A6:O{5 + new_n}").values = raw
    sh.get_range(f"T6:T{5 + new_n}").values = states
    formulas = []
    for r in range(6, 6 + new_n):
        formulas.append([
            f'=IF(J{r}="","",-J{r})',
            f'=IF(M{r}="","",-M{r})',
            f'=IF(OR(I{r}="",J{r}="",I{r}+J{r}=0),"",(I{r}-J{r})/(I{r}+J{r}))',
            f'=IF(OR(O{r}="",H{r}="",H{r}=0),"",O{r}/H{r})',
        ])
    sh.get_range(f"P6:S{5 + new_n}").formulas = formulas
    clear_tail(sh, 6, old_n, new_n, "T", 20)
    sh.get_range("A1").values = [[f"每日统一历史数据｜市场宽度、权威指数、成交与百亿成交｜最新{payload['date']}"]]


def history02(wb) -> list[dict]:
    sh = wb.worksheets.get_item("02_统一历史数据")
    n = nrows(sh, 6, 1000)
    out = []
    for r in sh.get_range(f"A6:T{5 + n}").values:
        if r[0] is None:
            continue
        width = None
        if r[8] is not None and r[9] is not None and r[8] + r[9]:
            width = (r[8] - r[9]) / (r[8] + r[9])
        out.append({"date": int(r[0]), "up": r[8], "down": r[9], "flat": r[10], "lu": r[11], "ld": r[12], "width": width, "hot_count": r[13], "hot_amount": r[14], "market_amount": r[7]})
    return out


def update_03(wb) -> list[dict]:
    rows = sorted(history02(wb), key=lambda x: x["date"])
    sh = wb.worksheets.get_item("03_市场宽度图")
    n = len(rows)
    sh.get_range(f"R6:T{5+n}").values = [[x["date"], x["up"], -x["down"] if x["down"] is not None else None] for x in rows]
    sh.get_range(f"V6:X{5+n}").values = [[x["date"], x["lu"], -x["ld"] if x["ld"] is not None else None] for x in rows]
    sh.get_range(f"Z6:AA{5+n}").values = [[x["date"], x["width"]] for x in rows]
    cats = [as_date(x["date"]).strftime("%m-%d") for x in rows]
    charts = sh.charts.items
    for series, values in [
        (charts[0].series.items[0], [x["up"] for x in rows]),
        (charts[0].series.items[1], [-x["down"] if x["down"] is not None else None for x in rows]),
        (charts[1].series.items[0], [x["lu"] for x in rows]),
        (charts[1].series.items[1], [-x["ld"] if x["ld"] is not None else None for x in rows]),
        (charts[2].series.items[0], [x["width"] for x in rows]),
    ]:
        series.categories, series.values = cats, values
    charts[2].title_text = f"市场宽度｜至{as_date(rows[-1]['date']).isoformat()}"
    return rows


def hot_rows(wb) -> list[list]:
    sh = wb.worksheets.get_item("04_百亿成交历史")
    n = nrows(sh, 23, 1000)
    return sh.get_range(f"A23:J{22+n}").values if n else []


def update_04(wb, payload: dict) -> dict:
    sh = wb.worksheets.get_item("04_百亿成交历史")
    old = hot_rows(wb)
    target = serial(payload["date"])
    prior = {str(r[2]): r for r in old if r[0] == target}
    rest = [r for r in old if r[0] != target]
    new = []
    for item in payload.get("hot_stocks", []):
        code = str(item.get("stock_code") or "")
        sw1, sw2 = item.get("sw_level1") or "未匹配", item.get("sw_level2") or "未匹配"
        state = "已匹配" if sw1 != "未匹配" and sw2 != "未匹配" else "待申万映射"
        if (sw1 == "未匹配" or sw2 == "未匹配") and code in prior:
            p = prior[code]
            if p[7] not in (None, "未匹配") and p[8] not in (None, "未匹配"):
                sw1, sw2, state = p[7], p[8], p[9]
        new.append([target, item.get("rank"), code, item.get("stock_name"), item.get("close"), item.get("return"), item.get("amount_100m"), sw1, sw2, state])
    rows = new + rest
    rows.sort(key=lambda r: (-int(r[0]), int(r[1] or 9999)))
    grow_style(sh, 23, len(old), len(rows), "J")
    if rows:
        sh.get_range(f"A23:J{22+len(rows)}").values = rows
    clear_tail(sh, 23, len(old), len(rows), "J", 10)

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
    inds = list(counts)
    current_order = [str(x[0]) for x in sh.get_range("A6:A19").values if x[0]]
    inds.sort(key=lambda x: (current_order.index(x) if x in current_order else 999, -cumulative.get(x, 0), x))
    unique_count = len(inds)
    if unique_count > 14:
        inds = sorted(inds, key=lambda x: (-cumulative.get(x, 0), x))[:14]
    sh.get_range("A6:H19").values = [[None] * 8 for _ in range(14)]
    sh.get_range("B5:G5").values = [dates + [None] * (6-len(dates))]
    matrix = [[ind] + [counts[ind].get(d, 0) for d in dates] + [0] * (6-len(dates)) + [cumulative.get(ind, 0)] for ind in inds]
    if matrix:
        sh.get_range(f"A6:H{5+len(matrix)}").values = matrix
    sh.get_range("A21").values = [[f"百亿成交个股明细｜最新{payload['date']}共{len(new)}只"]]
    return {"target_rows": len(new), "target_matrix_sum": sum(counts[i].get(target, 0) for i in inds), "recent_unique_industries": unique_count, "matrix_capacity": 14}


def update_05(wb, payload: dict) -> dict:
    block = payload.get("sw_crowding") or {}
    sw_date, targets = block.get("date"), block.get("targets") or {}
    required = ["通信设备", "计算机设备", "元件", "半导体"]
    if not sw_date or any(name not in targets for name in required):
        return {"updated": False, "date": sw_date, "reason": "incomplete_official_payload"}
    row = [serial(sw_date)]
    for name in required:
        item = targets[name]
        if item.get("date") not in (None, sw_date):
            return {"updated": False, "date": sw_date, "reason": f"mixed_date:{name}"}
        row += [item.get("amount_100m"), item.get("turnover"), item.get("amount_share_of_a")]
    combined = block.get("combined") or {}
    row += [combined.get("amount_100m"), combined.get("amount_share_of_a"), "GitHub申万官方生产包"]
    sh = wb.worksheets.get_item("05_申万行业资金拥挤度")
    old_n = nrows(sh, 63, 1000)
    rows = sh.get_range(f"A63:P{62+old_n}").values if old_n else []
    key = serial(sw_date)
    idx = next((i for i, r in enumerate(rows) if r[0] == key), None)
    if idx is None:
        rows.append(row)
    else:
        old = rows[idx]
        rows[idx] = [old[i] if value is None else value for i, value in enumerate(row)]
    rows.sort(key=lambda r: -(r[0] or 0))
    grow_style(sh, 63, old_n, len(rows), "P")
    sh.get_range(f"A63:P{62+len(rows)}").values = rows
    clear_tail(sh, 63, old_n, len(rows), "P", 16)
    latest = as_date(rows[0][0]).isoformat()
    sh.get_range("A60").values = [[f"申万四行业主表｜最新有效{latest}"]]
    asc = sorted(rows, key=lambda r: r[0])
    cats = [as_date(r[0]).strftime("%m-%d") for r in asc]
    specs = [(0, 3, "通信设备成交额占全A"), (1, 2, "通信设备换手率"), (2, 13, "申万四行业成交额合计"), (3, 14, "申万四行业成交额占全A")]
    for chart_idx, col_idx, name in specs:
        s = sh.charts.items[chart_idx].series.items[0]
        s.name, s.categories, s.values = name, cats, [r[col_idx] for r in asc]
    return {"updated": True, "date": latest, "rows": len(rows)}


def innovation_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for r in csv.DictReader(handle):
            def num(key):
                value = (r.get(key) or "").strip()
                return None if not value else float(value)
            out.append({"date": r["date"], "amount": num("amount_100m"), "share": num("amount_share_of_a"), "turnover": num("turnover"), "activity": num("volume_activity_20d"), "return": num("return"), "volume": num("volume"), "source": r.get("source", ""), "mode": r.get("history_source_mode", "")})
    return out


def update_07(wb, rows: list[dict], payload: dict):
    rows = [r for r in rows if r["date"] <= payload["date"]]
    if not rows:
        return None
    rows.sort(key=lambda r: r["date"], reverse=True)
    mode = rows[0]["mode"]
    if any(r["mode"] != mode for r in rows):
        raise RuntimeError("innovation selected history mixes source modes")
    sh = wb.worksheets.get_item("07_创新药交易拥挤度")
    old_n = nrows(sh, 33, 1000)
    grow_style(sh, 33, old_n, len(rows), "H")
    values = [[serial(r["date"]), r["amount"], r["share"], r["turnover"], r["activity"], r["return"], r["volume"], f"{r['source']}；历史源={mode}"] for r in rows]
    sh.get_range(f"A33:H{32+len(rows)}").values = values
    clear_tail(sh, 33, old_n, len(rows), "H", 8)
    has_turnover = any(r["turnover"] is not None for r in rows)
    sh.get_range("A3").values = [["独立主题数据，不属于申万行业，不并入05。当前历史采用东方财富创新药BK1106单一口径；成交额、收益与换手率均来自同一历史源，换手率为供应商直接字段。" if mode == "eastmoney" else "独立主题数据，不属于申万行业，不并入05。当前使用同花顺创新药备用历史；成交额与收益可用，板块总换手率无可靠字段，因此换手率保持空白。"]]
    sh.get_range("A30").values = [[f"创新药历史明细｜最新{rows[0]['date']}｜历史源={mode}"]]
    asc = sorted(rows, key=lambda r: r["date"])
    cats = [datetime.strptime(r["date"], "%Y-%m-%d").strftime("%m-%d") for r in asc]
    c0, c1 = sh.charts.items[0], sh.charts.items[1]
    c0.series.items[0].categories, c0.series.items[0].values = cats, [r["share"] for r in asc]
    c1.series.items[0].categories = cats
    if has_turnover:
        c1.series.items[0].name, c1.series.items[0].values = "创新药换手率", [r["turnover"] for r in asc]
        c0.title_text = "创新药｜成交额占全A与换手率"
    else:
        c1.series.items[0].name, c1.series.items[0].values = "20日成交量活跃度代理", [r["activity"] for r in asc]
        c0.title_text = "创新药｜成交额占全A与20日成交量活跃度代理（非官方换手率）"
    return {"mode": mode, "has_turnover": has_turnover, "rows": rows}


def sync_00(wb, payload: dict, market_rows: list[dict], innovation) -> None:
    sh = wb.worksheets.get_item("00_市场总览")
    sw_date = (payload.get("sw_crowding") or {}).get("date")
    sh.get_range("A1").values = [[f"A股每日市场监控｜{payload['date']}"]]
    sh.get_range("A3").values = [[f"市场宽度/成交/百亿个股更新至{payload['date']}；" + (f"申万行业最新有效日{sw_date}" if sw_date else "申万模块沿用最近有效官方日") + f"；创新药历史源={innovation['mode'] if innovation else '未更新'}，独立07页，不并入05。"]]
    target_rows = {str(r[2]): r for r in hot_rows(wb) if r[0] == serial(payload["date"])}
    top = []
    for item in payload.get("hot_stocks", [])[:7]:
        code = str(item.get("stock_code") or "")
        old = target_rows.get(code)
        sw1 = item.get("sw_level1") or (old[7] if old else "未匹配")
        sw2 = item.get("sw_level2") or (old[8] if old else "未匹配")
        if old and sw1 == "未匹配" and old[7] != "未匹配": sw1 = old[7]
        if old and sw2 == "未匹配" and old[8] != "未匹配": sw2 = old[8]
        top.append([item.get("rank"), code, item.get("stock_name"), item.get("return"), item.get("amount_100m"), sw2, sw1, "已匹配" if sw1 != "未匹配" and sw2 != "未匹配" else "待申万映射"])
    top += [[None] * 8 for _ in range(7-len(top))]
    sh.get_range("H17:O23").values = top
    sh.get_range("H15").values = [[f"04｜{payload['date']}成交额超过100亿元个股（共{payload['market']['hot_count']}只）"]]
    asc = sorted(market_rows, key=lambda x: x["date"])
    cats = [as_date(x["date"]).strftime("%m-%d") for x in asc]
    sh.charts.items[0].series.items[0].categories, sh.charts.items[0].series.items[0].values = cats, [x["width"] for x in asc]
    sh.charts.items[0].title_text = f"市场宽度｜至{payload['date']}"
    s05 = wb.worksheets.get_item("05_申万行业资金拥挤度")
    for src_idx, dst_idx in [(0,1),(1,2),(2,3),(3,4)]:
        src, dst = s05.charts.items[src_idx].series.items[0], sh.charts.items[dst_idx].series.items[0]
        dst.name, dst.categories, dst.values = src.name, src.categories, src.values
    if innovation:
        s07 = wb.worksheets.get_item("07_创新药交易拥挤度")
        for src_idx, dst_idx in [(0,5),(1,6)]:
            src, dst = s07.charts.items[src_idx].series.items[0], sh.charts.items[dst_idx].series.items[0]
            dst.name, dst.categories, dst.values = src.name, src.categories, src.values
        sh.charts.items[5].title_text = s07.charts.items[0].title_text
        sh.get_range("H30").values = [[f"创新药历史源：{innovation['mode']}"]]


def update_99(wb, payload: dict, validation: dict, innovation, template_sha: str) -> None:
    sh, d, m = wb.worksheets.get_item("99_口径与质量"), payload["date"], payload["market"]
    sh.get_range("A1").values = [[f"A股每日市场监控｜数据口径、来源与质量检查｜{d}"]]
    sh.get_range("A3").values = [[f"截至{d}。缺失保持空白，不以0或跨口径数据替代；Renderer v{VERSION}；payload validation={validation.get('status')}。"]]
    sh.get_range("B6").values, sh.get_range("E6").values, sh.get_range("F6").values = [[f"2026-01-05—{d}"]], [[validation.get("status")]], [["GitHub render bundle + 冻结母表增量渲染"]]
    sh.get_range("B9").values, sh.get_range("F9").values = [[f"至{d}"]], [[f"{d}上涨{m['advance']}、下跌{m['decline']}、平盘{m['flat']}"]]
    sh.get_range("B10").values, sh.get_range("F10").values = [[f"至{d}"]], [[f"{d}涨停{m['limit_up']}、跌停{m['limit_down']}"]]
    sh.get_range("B11").values, sh.get_range("F11").values = [[f"至{d}"]], [[f"{d}{m['hot_count']}只，合计{m['hot_amount_100m']:.2f}亿元"]]
    if innovation:
        mode = innovation["mode"]
        source = "东方财富创新药BK1106" if mode == "eastmoney" else "同花顺创新药备用历史"
        latest = innovation["rows"][0]
        sh.get_range("A14:F16").values = [
            ["创新药成交额", f"历史至{d}", source, "独立07页，不并入05", "已更新", f"历史源={mode}"],
            ["创新药成交占比", f"历史至{d}", source+" + 02全A成交额", "创新药成交额/全部A股成交额", "已更新", "同日分母缺失则留空"],
            ["创新药换手率", f"历史至{d}", source, "供应商板块换手率", "已更新" if innovation["has_turnover"] else "不可可靠回填", "供应商直接字段" if innovation["has_turnover"] else "备用历史无可靠换手率字段"],
        ]
        sh.get_range("A23:D25").values = [["创新药历史/当日行数", len(innovation["rows"]), "通过", f"历史源={mode}"], [f"创新药{d}成交占比", latest["share"], "通过" if latest["share"] is not None else "提示", "同日全A分母"], ["创新药总换手率", latest["turnover"] if latest["turnover"] is not None else "空白", "通过" if latest["turnover"] is not None else "提示", "供应商直接字段" if latest["turnover"] is not None else "不以活跃度代理冒充换手率"]]
    sh.get_range("A40:F40").values = [["本轮更新", d, "GitHub bundle + Artifact Renderer", "00/02/03/04/05/07/99", "已完成", f"Renderer v{VERSION}; 模板SHA256={template_sha[:12]}…；冻结母表增量渲染"]]


def validate(wb, payload: dict, innovation, matrix: dict) -> dict:
    failures, warnings = [], []
    target = serial(payload["date"])
    r = wb.worksheets.get_item("02_统一历史数据").get_range("A6:T6").values[0]
    if r[0] != target: failures.append("02_latest_date")
    if r[8] is not None and r[9] is not None and r[8]+r[9] and abs((r[8]-r[9])/(r[8]+r[9])-payload["market"]["market_breadth"]) > 1e-10: failures.append("02_width")
    if r[14] is not None and r[7] and abs(r[14]/r[7]-payload["market"]["hot_concentration"]) > 1e-10: failures.append("02_concentration")
    if sum(1 for x in hot_rows(wb) if x[0] == target) != payload["market"]["hot_count"]: failures.append("04_hot_count")
    dates = wb.worksheets.get_item("04_百亿成交历史").get_range("B5:G5").values[0]
    if target not in dates: failures.append("04_target_missing_matrix")
    else:
        c = 1 + dates.index(target)
        total = sum((row[c] or 0) for row in wb.worksheets.get_item("04_百亿成交历史").get_range("A6:H19").values if row[0])
        if total != payload["market"]["hot_count"]: failures.append(f"04_matrix:{total}")
    if matrix["recent_unique_industries"] > matrix["matrix_capacity"]: failures.append(f"04_matrix_capacity:{matrix['recent_unique_industries']}")
    if abs((wb.worksheets.get_item("00_市场总览").get_range("J6").values[0][0] or 0)-payload["market"]["total_amount_100m"]) > 0.01: failures.append("00_market_amount")
    n = len(history02(wb))
    if wb.worksheets.get_item("03_市场宽度图").get_range(f"Z{5+n}").values[0][0] != target: failures.append("03_latest_date")
    if innovation and innovation["mode"] == "eastmoney" and innovation["rows"][0]["date"] == payload["date"] and innovation["rows"][0]["turnover"] is None: failures.append("07_turnover_missing")
    errors = wb.inspect({"kind": "match", "search_term": "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", "options": {"use_regex": True, "max_results": 300}, "summary": "renderer formula errors"}).ndjson
    if '"address"' in errors: failures.append("formula_errors")
    return {"renderer_version": VERSION, "date": payload["date"], "status": "FAIL" if failures else ("WARN" if warnings else "PASS"), "failures": failures, "warnings": warnings}


def render(template: Path, bundle: Path, output: Path, config: Path) -> dict:
    cfg = jload(config)
    wb, digest = template_check(template, cfg)
    for name in cfg["bundle"]["required_files"]:
        if not (bundle / name).exists(): raise RuntimeError(f"bundle missing required file: {name}")
    payload, payload_validation, manifest = jload(bundle/"daily_payload.json"), jload(bundle/"validation.json"), jload(bundle/"source_manifest.json")
    if payload_validation.get("status") == "FAIL": raise RuntimeError("payload validation is FAIL")
    upsert_02(wb, payload, payload_validation, manifest)
    market = update_03(wb)
    matrix = update_04(wb, payload)
    sw = update_05(wb, payload)
    ih = innovation_history(bundle/"innovation_history_selected.csv")
    innovation = update_07(wb, ih, payload) if ih else None
    sync_00(wb, payload, market, innovation)
    update_99(wb, payload, payload_validation, innovation, digest)
    result = validate(wb, payload, innovation, matrix)
    result.update({"sw_renderer": sw, "template_sha256": digest})
    if result["status"] == "FAIL": raise RuntimeError(f"workbook validation failed: {result}")
    output.parent.mkdir(parents=True, exist_ok=True)
    SpreadsheetFile.export_xlsx(wb).save(str(output))
    validation_path = output.with_suffix(".renderer_validation.json")
    validation_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(output), "renderer_validation": str(validation_path), "validation": result}


def main() -> None:
    p = argparse.ArgumentParser(description="A股每日监控 Artifact Excel Renderer")
    p.add_argument("--template", required=True); p.add_argument("--bundle-dir", required=True); p.add_argument("--output", required=True); p.add_argument("--config", default="config/excel_renderer.json")
    a = p.parse_args()
    print(json.dumps(render(Path(a.template), Path(a.bundle_dir), Path(a.output), Path(a.config)), ensure_ascii=False))


if __name__ == "__main__": main()
