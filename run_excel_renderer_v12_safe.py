#!/usr/bin/env python3
from __future__ import annotations

import run_excel_renderer_v12 as v12


def _safe_style_axis(chart, *, secondary: bool = False, percent: bool = False) -> None:
    """Renderer v1.2 safe chart-axis contract for artifact_tool."""
    for axis in (chart.x_axis, chart.y_axis):
        axis.major_gridlines.visible = False
        axis.minor_gridlines.visible = False
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


# artifact_tool currently cannot safely serialize an explicit axis.line style.
# Rebind the v1.2 helper so all existing chart builders use the stable contract.
v12._style_axis = _safe_style_axis


def main() -> None:
    v12.main()


if __name__ == "__main__":
    main()
