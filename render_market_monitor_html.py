#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_monitor.html_renderer_v11 import render_html

HTML_RENDERER_VERSION = "1.1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render self-contained A-share market monitor HTML")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    html = render_html(report)
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"html={args.output} version={HTML_RENDERER_VERSION} bytes={len(html.encode('utf-8'))}")


if __name__ == "__main__":
    main()
