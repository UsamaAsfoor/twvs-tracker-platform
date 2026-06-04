#!/usr/bin/env python3
"""Render the full Oct→June tracker HTML from the multi-month engine output.
Both views are computed from real source data:
  - Cumulative: cross-month-merged totals with per-month breakdown + persistence
  - Current month (June): single-month, with an "also requested" history note
Reuses the live template's CSS + JS so the page looks/behaves identically.
Output: tracker_REBUILD_preview.html (NOT published).
"""
import json
import os

import generate_tracker as G
import rebuild_tracker_allmonths as E

DATA = os.path.expanduser("~/TWVS/data")
MONTH_ABBR = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May",
              "06": "Jun", "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct",
              "11": "Nov", "12": "Dec"}


def fmt_months(by_month):
    return " ".join(f"{MONTH_ABBR[m[5:]]}:{h}" for m, h in sorted(by_month.items()) if h)


def persist_badge(by_month):
    n = sum(1 for h in by_month.values() if h)
    return f'<span class="persistent">🔥 {n} MO</span>' if n >= 2 else ""


def done_badge(done_date):
    if not done_date:
        return ""
    try:
        from datetime import datetime
        d = datetime.strptime(done_date, "%Y-%m-%d")
        return f'<span class="done-badge">✅ DONE {d.strftime("%b %Y")}</span>'
    except (ValueError, TypeError):
        return '<span class="done-badge">✅ DONE</span>'


def render_entry(hearts, artist, song, meta_html, url, is_top, badge=""):
    cls = "hearts top" if is_top else "hearts"
    title = G.esc(f"{artist} — {song}")
    yt = G.render_yt(url)
    return (f'<div class="req"><span class="{cls}">{hearts}</span>'
            f'<div class="content"><div class="song">{title}{yt}{badge}</div>'
            f'<div class="meta">{meta_html}</div></div></div>')


def section(tab_key, h2, rows_html, count_line, mode):
    return (f'<div class="genre-section" data-tab="all {tab_key}" data-mode="{mode}">\n'
            f'<div class="genre-header"><h2>{G.esc(h2)}</h2>'
            f'<span class="genre-count">{count_line}</span></div>\n{rows_html}\n</div>')


def main():
    eng = json.load(open(os.path.join(DATA, "tracker_allmonths_engine.json")))
    cumulative = eng["cumulative"]
    june = eng["current_month_rows"]

    # Lookup June songs -> their full cross-month history (for persistence + note).
    hist = {(c["artist"].lower(), c["song"].lower()): c for c in cumulative}

    tmpl = G.load_template(os.path.join(DATA, "tracker_FINAL.html"))

    # ---- Select + render CUMULATIVE per tab ----
    cum_by_tab = {}
    for c in cumulative:
        months = sum(1 for h in c["by_month"].values() if h)
        ok, _ = E.qualifies(c["tab"], c["total"], months)
        if ok:
            cum_by_tab.setdefault(c["tab"], []).append(c)
    for rows in cum_by_tab.values():
        rows.sort(key=lambda x: -x["total"])

    cum_sections, cum_counts = [], {}
    for tab_key, _, h2 in G.TAB_DEFINITIONS:
        rows = cum_by_tab.get(tab_key, [])
        if not rows:
            continue
        total_h = sum(r["total"] for r in rows)
        cum_counts[tab_key] = f"{total_h} ❤️"
        n_top = max(1, len(rows) * 15 // 100)
        html_rows = []
        for i, r in enumerate(rows):
            meta = G.render_requesters(r["requesters"])
            bm = fmt_months(r["by_month"])
            if bm:
                meta += f' · <span class="ctx">{bm}</span>'
            badge = done_badge(r.get("done_date")) + persist_badge(r["by_month"])
            html_rows.append(render_entry(r["total"], r["artist"], r["song"], meta,
                                          r.get("url"), i < n_top, badge))
        cum_sections.append(section(tab_key, h2, "\n".join(html_rows),
                                    f"Oct'25–Jun'26 · {len(rows)} requests · {total_h} ❤️", "cumulative"))

    # ---- Select + render CURRENT (June) per tab ----
    # Current month shows EVERY request (even 0 hearts) — people should see
    # their post the moment they make it; the month is still filling up.
    cur_by_tab = {}
    for r in june:
        h = hist.get((r["artist"].lower(), r["song"].lower()))
        months = sum(1 for v in (h["by_month"].values() if h else []) if v)
        cur_by_tab.setdefault(r["tab"], []).append((r, h, months))
    for rows in cur_by_tab.values():
        rows.sort(key=lambda x: -x[0]["hearts"])

    cur_sections, cur_counts = [], {}
    for tab_key, _, h2 in G.TAB_DEFINITIONS:
        rows = cur_by_tab.get(tab_key, [])
        if not rows:
            continue
        total_h = sum(r["hearts"] for r, _, _ in rows)
        cur_counts[tab_key] = f"{total_h} ❤️"
        n_top = max(1, len(rows) * 15 // 100)
        html_rows = []
        for i, (r, h, months) in enumerate(rows):
            meta = G.render_requesters(r["requesters"])
            if months >= 2 and h:
                prior = [MONTH_ABBR[m[5:]] for m in sorted(h["by_month"]) if m != "2026-06" and h["by_month"][m]]
                if prior:
                    meta += f' · <span class="ctx">↩ also requested {", ".join(prior)}</span>'
            badge = done_badge(r.get("done_date")) + (persist_badge(h["by_month"]) if h else "")
            html_rows.append(render_entry(r["hearts"], r["artist"], r["song"], meta,
                                          r.get("url"), i < n_top, badge))
        cur_sections.append(section(tab_key, h2, "\n".join(html_rows),
                                    f"June 2026 · {len(rows)} requests · {total_h} ❤️", "current"))

    # ---- Tab bar ----
    tabs = ['<div class="tab active" data-tab="all" data-label="All" data-cumulative-count="" '
            'data-current-count="" onclick="showTab(\'all\')">All</div>']
    for tab_key, label, _ in G.TAB_DEFINITIONS:
        cum = cum_counts.get(tab_key, "")
        cur = cur_counts.get(tab_key, "")
        if not cum and not cur:
            continue
        vis = f"{label} ({cum})" if cum else label
        tabs.append(f'<div class="tab" data-tab="{tab_key}" data-label="{G.esc(label)}" '
                    f'data-cumulative-count="{cum}" data-current-count="{cur}" '
                    f'onclick="showTab(\'{tab_key}\')">{G.esc(vis)}</div>')

    cum_total = sum(sum(r["total"] for r in rows) for rows in cum_by_tab.values())
    cum_n = sum(len(rows) for rows in cum_by_tab.values())
    cur_total = sum(r["hearts"] for rows in cur_by_tab.values() for r, _, _ in rows)
    cur_n = sum(len(rows) for rows in cur_by_tab.values())

    toggle = ('<div class="mode-toggle">\n'
              '<button class="mode-btn active" data-mode="cumulative" onclick="showMode(\'cumulative\')">Cumulative · Oct\'25 – Jun\'26</button>\n'
              '<button class="mode-btn" data-mode="current" onclick="showMode(\'current\')">Current Month · June 2026</button>\n</div>')
    cum_content = (f'<div class="mode-content active" data-mode="cumulative">\n'
                   f'<div class="scope">Coverage: Oct 2025 → June 2026 (9 months), rebuilt from live source comments. '
                   f'Hearts summed across months; songs requested in 3+ months with ≥2♥ kept even below the per-tab cutoff.</div>\n'
                   f'<div class="stats"><div class="stat"><div class="num">{cum_n}</div><div class="lbl">Active Requests</div></div>'
                   f'<div class="stat"><div class="num">{cum_total:,}</div><div class="lbl">Total Hearts</div></div></div>\n</div>')
    cur_content = (f'<div class="mode-content" data-mode="current">\n'
                   f'<div class="scope">June 2026 · from the June General + K-Pop request posts. '
                   f'Shows <b>every</b> request this month (even with no hearts yet) so your post appears as soon '
                   f'as you make it — duplicate requests are merged. 🔥 badges / "↩ also requested" notes show '
                   f'sustained multi-month demand.</div>\n'
                   f'<div class="stats"><div class="stat"><div class="num">{cur_n}</div><div class="lbl">Songs This Month</div></div>'
                   f'<div class="stat"><div class="num">{cur_total:,}</div><div class="lbl">Total Hearts</div></div></div>\n</div>')

    parts = [
        '<meta charset="utf-8">', tmpl["style"],
        '<h1>TWVS Community Request Tracker</h1>',
        f'<div class="subtitle">Updated {__import__("datetime").date.today().strftime("%B %-d, %Y")} · Coverage: Oct 2025 → June 2026 · toggle Cumulative ↔ Current Month.</div>',
        toggle, "", cum_content, "", cur_content, "",
        tmpl["search_input"],
        '<div class="tabs">\n' + "\n".join(tabs) + "\n</div>",
        *cum_sections, *cur_sections, "",
        tmpl["script"],
    ]
    out = os.path.join(DATA, "tracker_REBUILD_preview.html")
    open(out, "w", encoding="utf-8").write("\n".join(p for p in parts if p))
    print(f"✅ Wrote {out}")
    print(f"   Cumulative: {cum_n} songs / {cum_total:,}♥   Current(June): {cur_n} songs / {cur_total:,}♥")


if __name__ == "__main__":
    main()
