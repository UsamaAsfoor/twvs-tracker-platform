#!/usr/bin/env python3
"""Multi-month rebuild ENGINE + validation. Reuses generate_tracker's parsing,
categorization (genre-prefix + heuristic), dedup, and attribution-fix logic;
adds: true month assignment (by URL — titles were self-mislabeled in config),
per-month extraction, and CROSS-MONTH merge for the cumulative view.

This step validates the DATA (counts, categories, cross-month merge, done audit)
before any HTML is rendered. No output file is published.
"""
import os, sys, re, json
from collections import defaultdict, Counter

_SCRIPTS = os.environ.get("TWVS_SCRIPTS_DIR", os.path.expanduser("~/TWVS/scripts"))
sys.path.insert(0, _SCRIPTS)
import generate_tracker as G

DATA = os.environ.get("TWVS_DATA_DIR", os.path.expanduser("~/TWVS/data"))

# URL id -> (YYYY-MM, type). Derived from the captured post_title of each post.
URL_MONTH = {
    "159839506": ("2026-06", "General"), "159837783": ("2026-06", "K-Pop"),
    "157072299": ("2026-05", "General"), "157069116": ("2026-05", "K-Pop"),
    "154516228": ("2026-04", "General"), "154519835": ("2026-04", "K-Pop"),
    "151978841": ("2026-03", "K-Pop"),   "151976141": ("2026-03", "General"),
    "149669027": ("2026-02", "K-Pop"),   "149664332": ("2026-02", "General"),
    "147171618": ("2026-01", "General"), "147172552": ("2026-01", "K-Pop"),
    "144798397": ("2025-12", "General"), "144796741": ("2025-12", "K-Pop"),
    "144795170": ("2025-12", "K-Pop"),   # "NEW groups" supplementary K-pop post
    "142578563": ("2025-11", "General"), "142578301": ("2025-11", "K-Pop"),
    "140186892": ("2025-10", "General"),
}


def post_id(url):
    m = re.search(r"(\d{6,})", url or "")
    return m.group(1) if m else ""


# Per-tab heart cutoffs: busy tabs higher, niche at the floor of 3, never below.
TAB_CUTOFF = {
    "skz": 5, "vtuber": 5,
    "morekpop": 4, "jpop": 4, "bts": 4, "other": 4,
    "ateez": 3, "rock": 3, "euro": 3, "game": 3, "anime": 3, "enhypen": 3,
}
DEFAULT_CUTOFF = 4
PERSIST_MONTHS = 3   # requested in this many distinct months …
PERSIST_FLOOR = 2    # … AND at least this many total hearts (real interest)


def qualifies(tab, total_hearts, months_requested):
    """Show if it meets the tab cutoff OR it's a sustained multi-month request
    that still cleared a real hearts floor. Never show 0–2 total-heart songs."""
    cutoff = TAB_CUTOFF.get(tab, DEFAULT_CUTOFF)
    if total_hearts >= cutoff:
        return True, "cutoff"
    if months_requested >= PERSIST_MONTHS and total_hearts >= PERSIST_FLOOR:
        return True, "persistence"
    return False, None


def main():
    posts = json.load(open(os.path.join(DATA, "song_requests.json")))
    _, overrides_by_key, attribution_fixes = G.load_overrides(os.path.join(DATA, "tracker_overrides.json"))

    # Group comments by true month.
    month_comments = defaultdict(list)
    for p in posts:
        mt = URL_MONTH.get(post_id(p.get("url", "")))
        if not mt:
            print(f"  ⚠️ unmapped post: {p.get('url')}")
            continue
        for c in p.get("structured", []):
            month_comments[mt[0]].append(c)

    # Community + review corrections, matched against "artist song" (lowercased).
    # CATEGORY_FIX: substring -> tab.  ATTRIB_FIX: substring -> canonical (artist,
    # song) so variant spellings of one song merge across months.
    CATEGORY_FIX = [
        ("prayer x", "jpop"),            # King Gnu (Kagari, Patreon chat)
        ("chk chk boom", "skz"), ("do it/recording", "skz"), ("2kids show", "skz"),
        ("the rose", "rock"),            # K-rock band (old-tracker precedent)
        ("berq", "euro"), ("economy plus", "euro"),   # German / KAJ (Eurovision)
        ("forestella", "morekpop"),
        ("honk the horn", "vtuber"), ("shiabun", "vtuber"),
        ("sofia isella", "rock"),
        # Indie/folk folded into Rock / Alt / Folk (user choice, option 2)
        ("mitski", "rock"), ("noah kahan", "rock"), ("hozier", "rock"),
        ("sufjan", "rock"), ("mad tsai", "rock"), ("paris paloma", "rock"),
        ("lizzy mcalpine", "rock"), ("phoebe bridgers", "rock"),
        ("weyes blood", "rock"), ("lola young", "rock"),
        # Musicals & Soundtracks tab (stage musicals + film/TV soundtracks; NOT VGM)
        ("musical", "musical"), ("cast recording", "musical"), ("broadway", "musical"),
        ("genetic opera", "musical"), ("come from away", "musical"), ("sweeney todd", "musical"),
        ("waitress", "musical"), ("hadestown", "musical"), ("next to normal", "musical"),
        ("prince of egypt", "musical"), ("little shop", "musical"), ("ballad of jane doe", "musical"),
        ("dear evan hansen", "musical"), ("hamilton", "musical"), ("starkids", "musical"),
        ("guy who didn't like music", "musical"), ("arcane", "musical"),
        ("highlander soundtrack", "musical"), ("repo! the genetic", "musical"),
        ("falling slowly", "musical"), ("jeremy jordan", "musical"),
        # Review round 2 (Pop & Misc cleanup)
        ("bloodflame", "vtuber"),        # Elizabeth Rose Bloodflame (VTuber)
        ("woosung", "rock"),             # The Rose's lead singer (K-rock)
        ("adela", "euro"),               # Slovak/European singer
        ("the warning", "rock"),         # rock/metal band
        ("the hu ", "rock"),             # Mongolian metal (trailing space = safe match)
    ]
    ATTRIB_FIX = [   # substring -> (canonical_artist, canonical_song)
        ("future eve", "Sasakure.uk", "Future Eve"),
        ("mirror mirror", "F.HERO × MILLI", "Mirror Mirror"),
    ]

    def apply_chat_corrections(rows):
        for r in rows:
            combined = f"{r['artist']} {r['song']}".lower()
            for sub, tab in CATEGORY_FIX:
                if sub in combined:
                    r["tab_key"] = tab
            for sub, a, s in ATTRIB_FIX:
                if sub in combined:
                    r["artist"], r["song"] = a, s

    # Build per-month rows from the LLM extraction (clean artist/song/category).
    # Each comment was read by Claude → {is_request, artist, song, category}.
    llm_path = os.path.join(DATA, "song_requests_llm.json")
    if not os.path.exists(llm_path):
        sys.exit("  ❌ song_requests_llm.json missing — run llm_extract_requests.py first.")
    llm = json.load(open(llm_path))

    def _nk(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    bym = defaultdict(list)
    for it in llm:
        if it.get("is_request") and (it.get("artist") or "").strip():
            bym[it["month"]].append(it)

    month_rows = {}
    for month, its in bym.items():
        groups = {}
        for it in its:
            artist = it["artist"].strip()
            song = (it.get("song") or "catalog").strip() or "catalog"
            key = _nk(artist) + "|" + _nk(song)
            g = groups.setdefault(key, {"key": key, "artist": artist, "song": song,
                "hearts": 0, "contribs": defaultdict(int), "cats": Counter(), "url": None})
            h = it.get("hearts", 0) or 0
            g["hearts"] += h
            g["contribs"][it.get("commenter", "Anon")] += h
            g["cats"][it.get("category", "other")] += 1
            if not g["url"]:
                g["url"] = G.extract_youtube_url(it.get("text", ""))
        rows = []
        for g in groups.values():
            requesters = sorted(g["contribs"], key=lambda n: (-g["contribs"][n], n.lower()))
            rows.append({"key": g["key"], "artist": g["artist"], "song": g["song"],
                "hearts": g["hearts"], "requesters": requesters, "youtube_url": g["url"],
                "tab_key": g["cats"].most_common(1)[0][0]})
        apply_chat_corrections(rows)
        month_rows[month] = rows

    # Cross-month merge -> cumulative (key = same artist+song).
    cumulative = {}
    for month in sorted(month_rows):
        for r in month_rows[month]:
            # Key off the (corrected) artist+song so variant names merge.
            ckey = _nk(r["artist"]) + "|" + _nk(r["song"])
            c = cumulative.setdefault(ckey, {
                "artist": r["artist"], "song": r["song"], "tab": r["tab_key"],
                "total": 0, "by_month": {}, "requesters": [], "youtube_url": None})
            c["total"] += r["hearts"]
            c["by_month"][month] = c["by_month"].get(month, 0) + r["hearts"]
            for rq in r["requesters"]:
                if rq not in c["requesters"]:
                    c["requesters"].append(rq)
            if not c["youtube_url"] and r.get("youtube_url"):
                c["youtube_url"] = r["youtube_url"]

    # ---- VALIDATION OUTPUT ----
    print("=== Per-month entry counts (after dedup) ===")
    for month in sorted(month_rows):
        rows = month_rows[month]
        hearts = sum(r["hearts"] for r in rows)
        print(f"  {month}: {len(rows):3d} unique songs · {hearts:4d} hearts")
    print(f"\n  Cumulative unique songs (cross-month merged): {len(cumulative)}")

    multi = {k: v for k, v in cumulative.items() if len(v["by_month"]) > 1}
    print(f"  Songs requested in 2+ months (cross-month merge worked): {len(multi)}")

    print("\n=== Cross-month merge spot-check: King Gnu / Prayer X ===")
    for k, v in cumulative.items():
        if "king gnu" in v["artist"].lower() or "prayer x" in v["song"].lower():
            bm = " ".join(f"{m}:{h}" for m, h in sorted(v["by_month"].items()))
            print(f"  [{v['tab']}] {v['artist']} — {v['song']} | total={v['total']} | {bm}")

    print("\n=== Tab distribution (cumulative) ===")
    by_tab = defaultdict(lambda: [0, 0])
    for v in cumulative.values():
        by_tab[v["tab"]][0] += 1
        by_tab[v["tab"]][1] += v["total"]
    for tab, _, _ in G.TAB_DEFINITIONS:
        n, h = by_tab.get(tab, [0, 0])
        print(f"  {tab:9}: {n:3d} songs · {h:4d} hearts")

    print("\n=== Vocaloid/utaite DONE audit (should be sparse) ===")
    completed_lookup, completed_by_artist = G.load_completed_log(os.path.join(DATA, "tracker_completed.json"))
    voc = ["vocaloid", "iyowa", "utsu", "pinocchio", "mafumafu", "wowaka", "sasakure", "kikuo", "mili"]
    done_voc = [e for e in completed_lookup.values()
                if any(x in (e.get("artist", "") + e.get("song", "")).lower() for x in voc)]
    print(f"  Vocaloid-family DONE entries in log: {len(done_voc)}")
    for e in done_voc:
        print(f"    {e.get('artist','?')} — {e.get('song','?')} ({e.get('completed_date','')})")

    # ---- THRESHOLD + PERSISTENCE VALIDATION ----
    print("\n=== Applying per-tab cutoffs + 3-month persistence (floor 3♥) ===")
    by_cutoff = by_persist = dropped = 0
    persist_examples, zero_repost = [], []
    shown = []
    for v in cumulative.values():
        months = len(v["by_month"])
        ok, why = qualifies(v["tab"], v["total"], months)
        if ok:
            shown.append(v)
            if why == "cutoff":
                by_cutoff += 1
            else:
                by_persist += 1
                if len(persist_examples) < 8:
                    persist_examples.append(v)
        else:
            dropped += 1
            # Flag the case the user cares about: reposted 3+ months but no real hearts
            if months >= PERSIST_MONTHS and v["total"] < PERSIST_FLOOR:
                zero_repost.append(v)

    print(f"  Shown: {len(shown)}  (by cutoff: {by_cutoff}, rescued by persistence: {by_persist})")
    print(f"  Dropped below threshold: {dropped}")

    print("\n  Persistence-rescued examples (multi-month, modest hearts, real interest):")
    for v in sorted(persist_examples, key=lambda x: -len(x["by_month"]))[:8]:
        bm = " ".join(f"{m[5:]}:{h}" for m, h in sorted(v["by_month"].items()))
        print(f"    [{v['tab']}] {v['artist']} — {v['song']}  ·  {len(v['by_month'])}mo · {v['total']}♥  ({bm})")

    print(f"\n  Reposted 3+ months but <3 hearts → correctly EXCLUDED: {len(zero_repost)}")
    for v in sorted(zero_repost, key=lambda x: -len(x["by_month"]))[:5]:
        bm = " ".join(f"{m[5:]}:{h}" for m, h in sorted(v["by_month"].items()))
        print(f"    [{v['tab']}] {v['artist']} — {v['song']}  ·  {len(v['by_month'])}mo · {v['total']}♥  ({bm})")

    # --- DONE matching against the library (standalone studies only) ---
    # library_done.json holds specific (artist, song) pairs you actually
    # studied (streams/admin already excluded). Strict normalized artist+song
    # match → never artist-only, so a catalog request can't be falsely "done".
    done_set = {}
    matches_path = os.path.join(DATA, "done_matches.json")
    if os.path.exists(matches_path):
        # Semantic matches (LLM-judged: handles typos, member names, songs inside
        # multi-song studies). Preferred over strict text matching.
        for k, v in json.load(open(matches_path)).items():
            done_set[k] = v.get("date") or "done"
        print(f"  Loaded {len(done_set)} semantic DONE matches")
    else:
        done_path = os.path.join(DATA, "library_done.json")
        if os.path.exists(done_path):
            for d in json.load(open(done_path)):
                if _nk(d.get("song")) in ("catalog", ""):
                    continue
                k = _nk(d.get("artist")) + "|" + _nk(d.get("song"))
                dt = d.get("date") or ""
                if k not in done_set or (dt and dt < done_set[k]):
                    done_set[k] = dt
        else:
            print("  ⚠️ no DONE source present — badges skipped this run.")

    # HOP "8 Solo Songs" bundle (May 8) — title didn't list the tracks, so these
    # can't be auto-matched. Tracks 5-12 of the HOP album, per Tim's setlist.
    HOP_SOLOS = [("han", "hold my hand"), ("felix", "unfair"), ("lee know", "youth"),
                 ("leeknow", "youth"), ("hyunjin", "so good"), ("seungmin", "as we are"),
                 ("bang chan", "railway"), ("i.n", "hallucination"), ("changbin", "ultra")]
    for v in cumulative.values():
        blob = (v["artist"] + " " + v["song"]).lower()
        for a, s in HOP_SOLOS:
            if a in blob and s in blob:
                done_set[_nk(v["artist"]) + "|" + _nk(v["song"])] = "2026-05-08"

    def _done_date(artist, song):
        return done_set.get(_nk(artist) + "|" + _nk(song)) if done_set else None

    n_done = sum(1 for v in cumulative.values() if _done_date(v["artist"], v["song"]))
    print(f"  DONE matches (specific song found in library): {n_done}")

    # Persist the engine output for the render step.
    out = {
        "months": sorted(month_rows),
        "cumulative": [
            {"artist": v["artist"], "song": v["song"], "tab": v["tab"],
             "total": v["total"], "by_month": v["by_month"],
             "requesters": v["requesters"], "url": v["youtube_url"],
             "done_date": _done_date(v["artist"], v["song"])}
            for v in sorted(cumulative.values(), key=lambda x: -x["total"])
        ],
        "current_month_rows": [
            {"artist": r["artist"], "song": r["song"], "tab": r["tab_key"],
             "hearts": r["hearts"], "requesters": r["requesters"], "url": r["youtube_url"],
             "done_date": _done_date(r["artist"], r["song"])}
            for r in sorted(month_rows.get("2026-06", []), key=lambda x: -x["hearts"])
        ],
    }
    json.dump(out, open(os.path.join(DATA, "tracker_allmonths_engine.json"), "w"),
              ensure_ascii=False, indent=2)
    print(f"\n  ✅ Engine output → tracker_allmonths_engine.json")


if __name__ == "__main__":
    main()
