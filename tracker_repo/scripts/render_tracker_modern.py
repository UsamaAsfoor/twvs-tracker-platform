#!/usr/bin/env python3
"""Bundle tracker data + modern UI into a single self-contained HTML file.

Reads:
  data/tracker_allmonths_engine.json
  tracker/styles.css
  tracker/app.js
  tracker/index.html

Writes:
  tracker/tracker_standalone.html  — paste-ready, no external dependencies except Google Fonts
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "tracker_allmonths_engine.json"
TRACKER = ROOT / "tracker"
OUT = TRACKER / "tracker_standalone.html"


def main() -> None:
    eng = json.loads(DATA.read_text(encoding="utf-8"))
    css = (TRACKER / "styles.css").read_text(encoding="utf-8")
    js = (TRACKER / "app.js").read_text(encoding="utf-8")
    html = (TRACKER / "index.html").read_text(encoding="utf-8")

    data_blob = json.dumps(eng, ensure_ascii=False, separators=(",", ":"))
    inject = f"window.__TRACKER_DATA__ = {data_blob};"

    html = re.sub(r'<link rel="stylesheet" href="styles\.css">', f"<style>\n{css}\n</style>", html)
    html = html.replace('<script src="app.js"></script>', f"<script>\n{inject}\n{js}\n</script>")

    months = eng.get("months") or []
    current = months[-1] if months else eng.get("current_month", "")
    today = date.today().strftime("%B %-d, %Y")
    html = html.replace(
        "<p id=\"subtitle\" class=\"subtitle\">Loading tracker data…</p>",
        f"<p id=\"subtitle\" class=\"subtitle\">Updated {today} · standalone build</p>",
    )

    OUT.write_text(html, encoding="utf-8")
    print(f"✅ Wrote {OUT}")
    print(f"   {len(eng.get('cumulative', []))} cumulative rows")
    print(f"   {len(eng.get('current_month_rows', []))} current-month rows")
    if current:
        print(f"   Current month: {current}")


if __name__ == "__main__":
    main()
