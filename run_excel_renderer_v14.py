#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from artifact_tool import Blob, SpreadsheetFile
import excel_renderer_artifact as core

VERSION = "1.4"
core.VERSION = VERSION

TARGET_SW = ["通信设备", "计算机设备", "元件", "半导体"]
TARGET_SW_CODES = {"通信设备": "801102", "计算机设备": "801101", "元件": "801083", "半导体": "801081"}
CHART_SHEETS = ("00_市场总览", "03_市场宽度图", "05_申万行业资金拥挤度", "07_创新药交易拥挤度")


def jload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def serial(text: str) -> int:
    return (datetime.strptime(text, "%Y-%m-%d").date() - date(1899, 12, 30)).days


def as_date(value) -> date:
    return date(1899, 12, 30) + timedelta(days=int(value))


def number(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mother_check(path: Path, cfg: dict):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    wb = SpreadsheetFile.import_xlsx(Blob.load(str(path)))
    actual = []
    for line in wb.inspect({"kind": "sheet", "include": "id,name"}).ndjson.splitlines():
        if line.strip():
            actual.append(json.loads(line)["name"])
    missing = [x for x in cfg["mother_policy"]["required_sheets"] if x not in actual]
    if missing:
        raise RuntimeError(f"mother workbook missing sheets: {missing}")
    expected_counts = cfg.get("chart_invariants", {}).get("sheet_chart_counts", {})
    for sheet_name, expected in expected_counts.items():
        actual_count = len(wb.worksheets.get_item(sheet_name).charts.items)
        if actual_count != expected:
            raise RuntimeError(f"mother chart count mismatch: {sheet_name} expected={expected} actual={actual_count}")
    return wb, digest


def chart_structure(wb) -> dict:
    out = {}
    for sheet_name in CHART_SHEETS:
        sh = wb.worksheets.get_item(sheet_name)
        drawings = []
        for line in wb.inspect({"kind": "drawing", "sheet_id": sh.id}).ndjson.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("drawingType") != "chart":
                continue
            anchor = item.get("anchor") or {}
            fr, to = anchor.get("from") or {}, anchor.get("to") or {}
            drawings.append((fr.get("row"), fr.get("col"), to.get("row"), to.get("col")))
        charts = []
        for chart in sh.charts.items:
            charts.append(tuple(str(series.name or "") for series in chart.series.items))
        out[sheet_name] = {"anchors": drawings, "series_names": charts}
    return out


def update_01(wb, bundle: Path) -> dict:
    rows = csv_rows(bundle / "sw_industry_latest.csv")
    if not rows:
        return {"updated": False, "reason": "sw_industry_latest_missing"}
    latest = max(str(r.get("日期") or "")[:10] for r in rows if r.get("日期"))
    rows.sort(key=lambda r: (
        0 if r.get("行业层级") == "一级行业" else 1,
        str(r.get("一级行业代码") or ""),
        str(r.get("指数代码") or ""),
    ))
    sh = wb.worksheets.get_item("01_申万行业")
    old_n = core.nrows(sh, 7, 2000)
    values = []
    for r in rows:
        d = str(r.get("日期") or "")[:10]
        values.append([
            serial(d), r.get("行业层级"), r.get("一级行业代码"), r.get("一级行业"),
            r.get("指数代码"), r.get("指数名称"), number(r.get("收盘价")), number(r.get("成交额")),
            number(r.get("日收益率")), number(r.get("20日年化波动率")),
            "申万行业数据", "最新有效官方值" if d == latest else "最近有效值",
        ])
    core.grow_style(sh, 7, old_n, len(values), "L")
    sh.get_range(f"A7:L{6+len(values)}").values = values
    core.clear_tail(sh, 7, old_n, len(values), "L", 12)
    sh.get_range("A1").values = [[f"申万一级 / 二级行业｜最新官方快照 {latest}"]]
    sh.get_range("A3").values = [[f"申万行业按同一历史接口更新；最新有效日为{latest}。单个长期停更指数保留其最近有效值，不跨源替代。"]]
    return {"updated": True, "latest": latest, "rows": len(values)}


def update_04(wb, payload: dict) -> dict:
    sh = wb.worksheets.get_item("04_百亿成交历史")
    old = core.hot_rows(wb)
    target = serial(payload["date"])
    rest = [r for r in old if r[0] != target]
    prior_by_code = {str(r[2]).zfill(6): r for r in old}
    new = []
    for item in payload.get("hot_stocks", []):
        code = str(item.get("stock_code") or "").zfill(6)
        sw1 = item.get("sw_level1") or "未匹配"
        sw2 = item.get("sw_level2") or "未匹配"
        state = "已匹配" if sw1 != "未匹配" and sw2 != "未匹配" else "待申万映射"
        if state != "已匹配" and code in prior_by_code:
            p = prior_by_code[code]
            if p[7] not in (None, "", "未匹配") and p[8] not in (None, "", "未匹配"):
                sw1, sw2, state = p[7], p[8], p[9] or "已匹配"
        new.append([
            target, item.get("rank"), code, item.get("stock_name"), item.get("close"),
            item.get("return"), item.get("amount_100m"), sw1, sw2, state,
        ])
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
    counts = {d: {} for d in dates}
    cumulative = {}
    for r in rows:
        ind = r[8] if r[8] not in (None, "", "未匹配") else "待申万映射"
        cumulative[ind] = cumulative.get(ind, 0) + 1
        if r[0] in counts:
            counts[r[0]][ind] = counts[r[0]].get(ind, 0) + 1

    current_order = [str(x[0]) for x in sh.get_range("A6:A19").values if x[0] not in (None, "", "其他行业汇总")]
    industries = set(cumulative)
    named = [x for x in current_order if x in industries]
    remaining = sorted(industries - set(named), key=lambda x: (-cumulative.get(x, 0), x))
    named = (named + remaining)[:13]
    overflow = industries - set(named)

    matrix = []
    for ind in named:
        matrix.append([ind] + [counts[d].get(ind, 0) for d in dates] + [0] * (6-len(dates)) + [cumulative.get(ind, 0)])
    other = ["其他行业汇总"]
    other += [sum(counts[d].get(ind, 0) for ind in overflow) for d in dates]
    other += [0] * (6-len(dates))
    other += [sum(cumulative.get(ind, 0) for ind in overflow)]
    matrix.append(other)
    sh.get_range("A6:H19").values = [[None] * 8 for _ in range(14)]
    sh.get_range("B5:G5").values = [dates + [None] * (6-len(dates))]
    sh.get_range(f"A6:H{5+len(matrix)}").values = matrix
    sh.get_range("A21").values = [[f"百亿成交个股明细｜最新{payload['date']}共{len(new)}只"]]
    target_matrix_sum = 0
    if target in dates:
        idx = dates.index(target) + 1
        target_matrix_sum = sum((r[idx] or 0) for r in matrix)
    return {
        "target_rows": len(new), "target_matrix_sum": target_matrix_sum,
        "recent_unique_industries": len(industries), "matrix_capacity": 14,
        "overflow_aggregated": len(overflow),
    }


def update_05(wb, payload: dict) -> dict:
    block = payload.get("sw_crowding") or {}
    sw_date, targets = block.get("date"), block.get("targets") or {}
    if not sw_date or any(name not in targets for name in TARGET_SW):
        return {"updated": False, "date": sw_date, "reason": "incomplete_official_payload"}
    market_amounts = {as_date(x["date"]).isoformat(): x["market_amount"] for x in core.history02(wb)}
    denominator = market_amounts.get(sw_date)
    row = [serial(sw_date)]
    for name in TARGET_SW:
        item = targets[name]
        if item.get("date") not in (None, sw_date):
            return {"updated": False, "date": sw_date, "reason": f"mixed_date:{name}"}
        share = item.get("amount_share_of_a")
        amount = item.get("amount_100m")
        if amount is None and denominator is not None and share is not None:
            amount = denominator * share
        row += [amount, item.get("turnover"), share]
    combined = block.get("combined") or {}
    combined_share = combined.get("amount_share_of_a")
    combined_amount = combined.get("amount_100m")
    if combined_amount is None and denominator is not None and combined_share is not None:
        combined_amount = denominator * combined_share
    row += [combined_amount, combined_share, "申万官方成交额占比/换手率；成交额由同日占比×全A成交额推导"]

    sh = wb.worksheets.get_item("05_申万行业资金拥挤度")
    old_n = core.nrows(sh, 63, 1000)
    rows = sh.get_range(f"A63:P{62+old_n}").values if old_n else []
    key = serial(sw_date)
    idx = next((i for i, r in enumerate(rows) if r[0] == key), None)
    if idx is None:
        rows.append(row)
    else:
        old = rows[idx]
        rows[idx] = [old[i] if value is None else value for i, value in enumerate(row)]
    rows.sort(key=lambda r: -(r[0] or 0))
    core.grow_style(sh, 63, old_n, len(rows), "P")
    sh.get_range(f"A63:P{62+len(rows)}").values = rows
    core.clear_tail(sh, 63, old_n, len(rows), "P", 16)
    latest = as_date(rows[0][0]).isoformat()
    sh.get_range("A60").values = [[f"申万四行业主表｜最新官方有效{latest}"]]

    asc = sorted(rows, key=lambda r: r[0] or 0)
    specs = [
        (0, 3, "通信设备成交额占全A"), (1, 2, "通信设备换手率"),
        (2, 13, "四行业成交额合计"), (3, 14, "四行业成交额占全A"),
    ]
    for chart_idx, col_idx, name in specs:
        valid = [r for r in asc if r[col_idx] not in (None, "")]
        series = sh.charts.items[chart_idx].series.items[0]
        series.name = name
        series.categories = [as_date(r[0]).strftime("%m-%d") for r in valid]
        series.values = [r[col_idx] for r in valid]
    return {"updated": True, "date": latest, "rows": len(rows), "denominator": denominator}


def update_06(wb, bundle: Path) -> dict:
    rows = csv_rows(bundle / "sw_industry_latest.csv")
    by_code = {str(r.get("指数代码") or ""): r for r in rows}
    selected = {name: by_code.get(code) for name, code in TARGET_SW_CODES.items()}
    if any(v is None for v in selected.values()):
        return {"updated": False, "reason": "target_industry_missing"}
    dates = {str(v.get("日期") or "")[:10] for v in selected.values()}
    if len(dates) != 1:
        return {"updated": False, "reason": "target_industry_mixed_dates", "dates": sorted(dates)}
    d = next(iter(dates))
    market_amounts = {as_date(x["date"]).isoformat(): x["market_amount"] for x in core.history02(wb)}
    denominator = market_amounts.get(d)
    if denominator is None:
        return {"updated": False, "reason": "market_denominator_missing", "date": d}

    row = [serial(d)]
    for name in TARGET_SW:
        item = selected[name]
        amount = number(item.get("成交额"))
        row += [
            amount, amount / denominator if amount is not None else None,
            number(item.get("日收益率")), number(item.get("20日年化波动率")),
        ]
    sh = wb.worksheets.get_item("06_综合拥挤度_辅助")
    old_n = core.nrows(sh, 6, 1000)
    values = sh.get_range(f"A6:Q{5+old_n}").values if old_n else []
    key = serial(d)
    idx = next((i for i, r in enumerate(values) if r[0] == key), None)
    if idx is None:
        values.append(row)
    else:
        values[idx] = row
    values.sort(key=lambda r: -(r[0] or 0))
    core.grow_style(sh, 6, old_n, len(values), "Q")
    sh.get_range(f"A6:Q{5+len(values)}").values = values
    core.clear_tail(sh, 6, old_n, len(values), "Q", 17)
    sh.get_range("A1").values = [[f"综合交易拥挤度辅助表｜最新{d}｜暂不纳入核心监控"]]
    return {"updated": True, "date": d, "rows": len(values)}


def sync_00(wb, payload: dict, market_rows: list[dict], innovation) -> None:
    sh = wb.worksheets.get_item("00_市场总览")
    m = payload["market"]
    indices = payload.get("indices") or {}
    sw_block = payload.get("sw_crowding") or {}
    sw_date = sw_block.get("date")

    sh.get_range("A1").values = [[f"A股每日市场监控｜{payload['date']}"]]
    sh.get_range("A3").values = [[
        f"市场宽度、成交与百亿成交更新至{payload['date']}；01申万行业使用最新官方快照；"
        + (f"05申万资金拥挤度最新官方有效日{sw_date}；" if sw_date else "05申万资金拥挤度沿用最近官方有效日；")
        + "创新药独立统计，不并入申万行业。"
    ]]
    sh.get_range("A6").values = [[(indices.get("上证50") or {}).get("return")]]
    sh.get_range("D6").values = [[(indices.get("Choice微盘") or {}).get("return")]]
    sh.get_range("G6").values = [[(indices.get("中证全指") or {}).get("return")]]
    sh.get_range("J6").values = [[m.get("total_amount_100m")]]
    sh.get_range("M6").values = [[m.get("hot_count")]]

    sh.get_range("A10:F12").values = [
        ["上涨家数", m.get("advance"), "下跌家数", m.get("decline"), "平盘家数", m.get("flat")],
        ["涨停家数", m.get("limit_up"), "跌停家数", m.get("limit_down"), "市场宽度", m.get("market_breadth")],
        ["百亿成交额", m.get("hot_amount_100m"), "成交集中度", m.get("hot_concentration"), "有效状态", "已更新"],
    ]
    sh02 = wb.worksheets.get_item("02_统一历史数据")
    recent = sh02.get_range("A6:T10").values
    sh.get_range("H10:O14").values = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[19]] for r in recent]

    target = serial(payload["date"])
    target_rows = [r for r in core.hot_rows(wb) if r[0] == target]
    top = [[r[1], str(r[2]).zfill(6), r[3], r[5], r[6], r[8], r[7], r[9]] for r in target_rows[:7]]
    top += [[None] * 8 for _ in range(7-len(top))]
    sh.get_range("H17:O23").values = top
    sh.get_range("H15").values = [[f"04｜{payload['date']}成交额超过100亿元个股（共{m.get('hot_count')}只）"]]

    s05 = wb.worksheets.get_item("05_申万行业资金拥挤度")
    n05 = core.nrows(s05, 63, 1000)
    if n05:
        latest05 = s05.get_range("A63:P63").values[0]
        sh.get_range("A24").values = [[f"05｜申万四行业资金拥挤度（最新官方有效{as_date(latest05[0]).isoformat()}）"]]
        sh.get_range("A26:O26").values = [[
            latest05[0], latest05[1], latest05[2], latest05[3], latest05[4], latest05[5],
            latest05[7], latest05[8], latest05[10], latest05[11], latest05[13], latest05[14],
            None, None, latest05[15],
        ]]

    if innovation:
        latest = innovation["rows"][0]
        sh.get_range("A30:H30").values = [[
            serial(latest["date"]), latest["amount"], latest["share"], latest["turnover"],
            latest["activity"], latest["return"], "已同步",
            "东方财富创新药BK1106" if innovation["mode"] == "eastmoney" else "同花顺创新药备用历史",
        ]]

    asc = sorted(market_rows, key=lambda x: x["date"])
    cats = [as_date(x["date"]).strftime("%m-%d") for x in asc]
    charts = sh.charts.items
    charts[0].series.items[0].categories, charts[0].series.items[0].values = cats, [x["up"] for x in asc]
    charts[0].series.items[1].categories, charts[0].series.items[1].values = cats, [-x["down"] if x["down"] is not None else None for x in asc]
    charts[1].series.items[0].categories, charts[1].series.items[0].values = cats, [x["lu"] for x in asc]
    charts[1].series.items[1].categories, charts[1].series.items[1].values = cats, [-x["ld"] if x["ld"] is not None else None for x in asc]
    charts[2].series.items[0].categories, charts[2].series.items[0].values = cats, [x["width"] for x in asc]
    charts[2].title_text = f"市场宽度｜至{payload['date']}"
    sh.get_range("Q23").values = [[f"市场宽度｜至{payload['date']}"]]

    for src_idx, dst_idx in [(0,3),(1,4),(2,5),(3,6)]:
        src = s05.charts.items[src_idx].series.items[0]
        dst = charts[dst_idx].series.items[0]
        dst.name, dst.categories, dst.values = src.name, src.categories, src.values

    if innovation:
        s07 = wb.worksheets.get_item("07_创新药交易拥挤度")
        for src_idx, dst_idx in [(0,7),(1,8)]:
            src = s07.charts.items[src_idx].series.items[0]
            dst = charts[dst_idx].series.items[0]
            dst.name, dst.categories, dst.values = src.name, src.categories, src.values

    sh.get_range("A34:E38").values = [
        ["01申万行业", "见01最新官方快照", "已同步", "申万行业历史", "按最新有效值展示"],
        ["02统一历史", f"2026-01-05—{payload['date']}", "已更新/有缺口", "多源校验", "缺失保持空白"],
        ["04百亿成交", f"最新{payload['date']}", "已更新", "A股收盘快照", f"{payload['date']}共{m.get('hot_count')}只"],
        ["05四行业", f"最新官方{sw_date}" if sw_date else "沿用最近官方日", "最新有效", "申万日度分析", "同日同源"],
        ["07创新药", f"历史至{payload['date']}", "已更新", "东方财富BK1106/备用同花顺", "单一历史源"],
    ]


def update_99(wb, payload: dict, validation: dict, innovation, mother_sha: str, extra: dict) -> None:
    core.update_99(wb, payload, validation, innovation, mother_sha)
    sh = wb.worksheets.get_item("99_口径与质量")
    sh.get_range("A3").values = [[
        f"截至{payload['date']}。缺失数据保持空白，不以0或跨口径数据替代；Renderer v{VERSION}；"
        f"payload validation={validation.get('status')}；滚动母表增量更新。"
    ]]
    sh.get_range("A40:F42").values = [
        ["当日数据更新", payload["date"], "市场监控", "00/01/02/03/04/05/06/07/99", "已完成", "原表增量更新；不重建图表对象"],
        ["Renderer", VERSION, "existing-chart update only", "图表对象/锚点/序列身份", "硬校验", "前后结构必须一致"],
        ["输入母表SHA256", mother_sha, "rolling mother", "上一正式验证工作簿", "已记录", json.dumps(extra, ensure_ascii=False)],
    ]


def validate(wb, payload: dict, innovation, matrix: dict, before_structure: dict, extra: dict) -> dict:
    failures, warnings = [], []
    target = serial(payload["date"])
    r = wb.worksheets.get_item("02_统一历史数据").get_range("A6:T6").values[0]
    if r[0] != target:
        failures.append("02_latest_date")
    if r[8] is not None and r[9] is not None and r[8] + r[9]:
        actual = (r[8] - r[9]) / (r[8] + r[9])
        if abs(actual - payload["market"]["market_breadth"]) > 1e-10:
            failures.append("02_width")
    if r[14] is not None and r[7]:
        if abs(r[14] / r[7] - payload["market"]["hot_concentration"]) > 1e-10:
            failures.append("02_concentration")
    if sum(1 for x in core.hot_rows(wb) if x[0] == target) != payload["market"]["hot_count"]:
        failures.append("04_hot_count")
    dates = wb.worksheets.get_item("04_百亿成交历史").get_range("B5:G5").values[0]
    if target not in dates:
        failures.append("04_target_missing_matrix")
    else:
        c = 1 + dates.index(target)
        total = sum((row[c] or 0) for row in wb.worksheets.get_item("04_百亿成交历史").get_range("A6:H19").values if row[0])
        if total != payload["market"]["hot_count"]:
            failures.append(f"04_matrix:{total}")
    if matrix["target_matrix_sum"] != payload["market"]["hot_count"]:
        failures.append("04_matrix_return")
    if abs((wb.worksheets.get_item("00_市场总览").get_range("J6").values[0][0] or 0)-payload["market"]["total_amount_100m"]) > 0.01:
        failures.append("00_market_amount")
    n = len(core.history02(wb))
    if wb.worksheets.get_item("03_市场宽度图").get_range(f"Z{5+n}").values[0][0] != target:
        failures.append("03_latest_date")
    if innovation and innovation["mode"] == "eastmoney" and innovation["rows"][0]["date"] == payload["date"] and innovation["rows"][0]["turnover"] is None:
        failures.append("07_turnover_missing")
    if chart_structure(wb) != before_structure:
        failures.append("chart_structure_changed")
    if not extra.get("sw01", {}).get("updated"):
        warnings.append("01_not_updated")
    if not extra.get("sw06", {}).get("updated"):
        warnings.append("06_not_updated")
    errors = wb.inspect({
        "kind": "match", "search_term": "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
        "options": {"use_regex": True, "max_results": 300}, "summary": "renderer formula errors",
    }).ndjson
    if '"address"' in errors:
        failures.append("formula_errors")
    return {
        "renderer_version": VERSION, "date": payload["date"],
        "status": "FAIL" if failures else ("WARN" if warnings else "PASS"),
        "failures": failures, "warnings": warnings,
        "chart_structure_preserved": "chart_structure_changed" not in failures,
    }


def render(mother: Path, bundle: Path, output: Path, config: Path) -> dict:
    cfg = jload(config)
    wb, digest = mother_check(mother, cfg)
    before_structure = chart_structure(wb)
    for name in cfg["bundle"]["required_files"]:
        if not (bundle / name).exists():
            raise RuntimeError(f"bundle missing required file: {name}")
    payload = jload(bundle / "daily_payload.json")
    payload_validation = jload(bundle / "validation.json")
    if payload_validation.get("status") == "FAIL":
        raise RuntimeError("payload validation is FAIL")

    sw01 = update_01(wb, bundle)
    core.upsert_02(wb, payload, payload_validation, jload(bundle / "source_manifest.json"))
    market = core.update_03(wb)
    matrix = update_04(wb, payload)
    sw05 = update_05(wb, payload)
    sw06 = update_06(wb, bundle)
    history = core.innovation_history(bundle / "innovation_history_selected.csv")
    innovation = core.update_07(wb, history, payload) if history else None
    sync_00(wb, payload, market, innovation)
    extra = {"sw01": sw01, "sw05": sw05, "sw06": sw06, "matrix": matrix}
    update_99(wb, payload, payload_validation, innovation, digest, extra)
    result = validate(wb, payload, innovation, matrix, before_structure, extra)
    result.update({"mother_sha256": digest, "modules": extra})
    if result["status"] == "FAIL":
        raise RuntimeError(f"workbook validation failed: {result}")
    output.parent.mkdir(parents=True, exist_ok=True)
    SpreadsheetFile.export_xlsx(wb).save(str(output))
    validation_path = output.with_suffix(".renderer_validation.json")
    validation_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(output), "renderer_validation": str(validation_path), "validation": result}


def main() -> None:
    parser = argparse.ArgumentParser(description="A股每日市场监控 Renderer v1.4")
    parser.add_argument("--template", required=True, help="上一交易日正式验证工作簿（滚动母表）")
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/excel_renderer.json")
    args = parser.parse_args()
    print(json.dumps(render(Path(args.template), Path(args.bundle_dir), Path(args.output), Path(args.config)), ensure_ascii=False))


if __name__ == "__main__":
    main()
