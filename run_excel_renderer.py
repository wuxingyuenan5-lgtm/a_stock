#!/usr/bin/env python3
from __future__ import annotations

import excel_renderer_artifact as core


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


core.update_04 = update_04_fixed


if __name__ == "__main__":
    core.main()
