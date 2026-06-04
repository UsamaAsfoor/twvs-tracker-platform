#!/usr/bin/env python3
"""
Generate the TWVS Community Request Tracker HTML from a current-month scrape.

Reads:
  song_requests.json     — fresh scrape (current month, top-level comments only)
  tracker_overrides.json — per-tab thresholds + hand-curated badge overrides
  tracker_FINAL.html     — template: style, JS, cumulative side (verbatim), tab counts

Writes:
  tracker.html           — full tracker HTML for Squarespace paste
  tracker_keys.txt       — per-entry (tab|artist|song) key reference for authoring overrides

Couples to twvs_heart_count_aggregator helpers (underscore-prefixed; v1 decision).
"""

import argparse
import html
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from twvs_heart_count_aggregator import (  # noqa: E402
    CANONICAL_NAMES,
    _dedup_key,
    _extract_song_title,
    _find_canonical_artist,
    _resolve_song_alias,
)


# ============================================================
# CONFIG
# ============================================================

DEFAULT_THRESHOLDS = {"min_hearts": 2, "top_pct": 20}

# Tab definitions in display order: (tab_key, display_label, h2_heading)
TAB_DEFINITIONS = [
    ("skz",      "Stray Kids",          "Stray Kids"),
    ("vtuber",   "VTuber",              "VTuber"),
    ("bts",      "BTS",                 "BTS"),
    ("jpop",     "J-Pop",               "J-Pop"),
    ("ateez",    "ATEEZ",               "ATEEZ"),
    ("euro",     "Europe / Eurovision", "Europe / Eurovision"),
    ("morekpop", "More K-Pop / Korean", "More K-Pop / Korean"),
    ("enhypen",  "ENHYPEN",             "ENHYPEN"),
    ("rock",     "Rock / Alt / Folk",   "Rock / Alt / Folk"),
    ("anime",    "Anime",               "Anime"),
    ("game",     "Video Game",          "Video Game"),
    ("musical",  "Musicals & Soundtracks", "Musicals & Soundtracks"),
    ("other",    "Pop & Misc",          "Pop & Misc"),
]

# Canonical artist (value from CANONICAL_NAMES, or heuristic-extracted name)
# -> tab key. Lookups go through `categorize()` which lowercases both sides.
# Community-correction provenance noted inline.
ARTIST_TO_TAB = {
    # ============================================================
    # Stray Kids
    # ============================================================
    "Stray Kids": "skz",
    "Stray Kids (Bang Chan)": "skz",
    "Stray Kids (Lee Know)": "skz",
    "Stray Kids (Changbin)": "skz",
    "Stray Kids (Hyunjin)": "skz",
    "Stray Kids (Han)": "skz",
    "Stray Kids (Felix)": "skz",
    "Stray Kids (Seungmin)": "skz",
    "Stray Kids (I.N)": "skz",
    "3RACHA (Stray Kids)": "skz",
    # NOTE: xikers → morekpop (Dani correction 2026-05-13: not Stray Kids)
    # ============================================================
    # BTS
    # ============================================================
    "BTS": "bts",
    "RM (BTS)": "bts",
    "Jin (BTS)": "bts",
    "Suga (BTS)": "bts",
    "Agust D (BTS)": "bts",
    "J-Hope (BTS)": "bts",
    "Jimin (BTS)": "bts",
    "Jungkook (BTS)": "bts",
    # NOTE: Taeyang → morekpop (Dani correction 2026-05-13: BIGBANG soloist, not BTS)
    # ============================================================
    # ENHYPEN
    # ============================================================
    "ENHYPEN": "enhypen",
    # ============================================================
    # ATEEZ
    # ============================================================
    "ATEEZ": "ateez",
    "ATEEZ (Jongho)": "ateez",
    # ============================================================
    # VTubers
    # ============================================================
    "Ironmouse": "vtuber",
    "Gigi Murin (Hololive)": "vtuber",
    "Mori Calliope (Hololive)": "vtuber",
    "Hoshimachi Suisei (Hololive)": "vtuber",
    "Tokoyami Towa (Hololive)": "vtuber",
    "Nanashi Mumei (Hololive)": "vtuber",
    "Houshou Marine (Hololive)": "vtuber",
    "Omaru Polka (Hololive)": "vtuber",
    "Hakos Baelz (Hololive)": "vtuber",
    "Neuro-sama": "vtuber",
    "Michi Mochievee": "vtuber",
    # Additional Hololive / Holostars members (May data)
    "Banzoin Hakka (Hololive)": "vtuber",
    "Nerissa Ravencroft (Hololive)": "vtuber",
    "Moona Hoshinova (Hololive)": "vtuber",
    "Gawr Gura (Hololive)": "vtuber",
    "Ninomae Ina'nis (Hololive)": "vtuber",
    "Otonose Kanade (Holostars)": "vtuber",
    "Roboco-san (Hololive)": "vtuber",
    "Takanashi Kiara (Hololive)": "vtuber",
    "Jurard T Rexford (Holostars)": "vtuber",
    "Octavio (Holostars)": "vtuber",
    "Regis Altare (Holostars)": "vtuber",
    "Shiranui Flare (Hololive)": "vtuber",
    "Aki Rosenthal (Hololive)": "vtuber",
    "Amane Kanata (Hololive)": "vtuber",
    "Tsunomaki Watame (Hololive)": "vtuber",
    "Iofifteen (Hololive)": "vtuber",
    "Kobo Kanaeru (Hololive)": "vtuber",
    "Minase Rio (Holostars)": "vtuber",
    "Kanade Izuru (Holostars)": "vtuber",
    "Elizabeth Rose Bloodflame": "vtuber",
    "Hololive": "vtuber",
    # Indie VTubers
    "Akuma Nihmune": "vtuber",
    "Bajiru": "vtuber",
    "OBKATIEKAT": "vtuber",
    "CottontailVA": "vtuber",
    "ShiaBun": "vtuber",
    "Ellie Minibot": "vtuber",
    "Godish": "vtuber",
    # Community-corrected mappings:
    "Amalee": "vtuber",                      # User call: anime cover singer, VTuber-adjacency
    "Bao the Whale": "vtuber",               # Mr.UNAWARE_22 2026-05-05: VTuber Bao, not the J-rock band
    "Bao": "vtuber",
    # Name-order and casing variants seen in May 2026 heuristic-extracted data:
    "Hakka Banzoin": "vtuber",               # Western word order of "Banzoin Hakka"
    "Hakka Banzoin (Hololive)": "vtuber",
    "Banzoin Hakka": "vtuber",               # explicit (also reached via stripped lookup)
    "Ayunda Risu": "vtuber",                 # missing from CANONICAL_NAMES entirely
    "Ayunda Risu (Hololive)": "vtuber",
    "Aki Rosenthal (Aki for short)": "vtuber",  # heuristic-output compound
    # ============================================================
    # J-Pop (Japanese: artists, vocaloid producers, J-rock, J-metal)
    # ============================================================
    "Ado": "jpop",
    "YOASOBI": "jpop",
    "Yorushika": "jpop",
    "Fujii Kaze": "jpop",
    "Kikuo": "jpop",
    "Official HIGE DANdism": "jpop",
    "Eve": "jpop",
    "9lana": "jpop",
    # Japanese bands and singers (May data)
    "Mrs. GREEN APPLE": "jpop",              # J-pop, NOT K-pop (user flagged)
    "Hiroshi Kitadani": "jpop",
    "Aimer": "jpop",
    "Sheena Ringo": "jpop",
    "Bump of Chicken": "jpop",
    "Sokoninaru": "jpop",
    "Queen Bee": "jpop",                     # Japanese rock band (Avu-chan)
    "LiSA": "jpop",
    "Minami": "jpop",
    "Babymetal": "jpop",
    "BABYMETAL": "jpop",
    "Kenshi Yonezu": "jpop",
    "Tuki.": "jpop",
    "Zutomayo": "jpop",
    "ZUTOMAYO": "jpop",
    # Vocaloid producers and Utaite
    "MafuMafu": "jpop",
    "PinocchioP": "jpop",
    "Sasakure.UK": "jpop",
    "Sasakure .UK": "jpop",                  # space variant seen in May data
    "UKrampage": "jpop",
    "Utsu P": "jpop",                        # no-hyphen variant of "Utsu-P"
    "Wolpis Carter": "jpop",
    "iyowa": "jpop",
    "Utsu-P": "jpop",
    "Wowaka": "jpop",
    "MARETU": "jpop",
    "r-906": "jpop",
    "Sasuke Haraguchi": "jpop",
    "Azari": "jpop",
    "KikuoHana": "jpop",
    "Hatsune Miku": "jpop",                  # User call: vocaloid platform → jpop
    "KAF": "jpop",
    "理芽": "vtuber",                          # Mr.UNAWARE 2026-05-31: VTuber/V-singer, not jpop
    "Marinasu": "jpop",
    "Mili": "jpop",
    "FLAVOR FOLEY": "jpop",
    "Chanmina": "jpop",                      # Mr.UNAWARE_22 2026-05-05: jpop, not vtuber
    # ============================================================
    # More K-Pop / Korean (everything Korean not in dedicated tabs)
    # ============================================================
    "SEVENTEEN": "morekpop",
    "NMIXX": "morekpop",
    "TXT": "morekpop",
    "EXO": "morekpop",
    "SHINee": "morekpop",
    "Taemin (SHINee)": "morekpop",
    "IVE": "morekpop",
    "ITZY": "morekpop",
    "Red Velvet": "morekpop",
    "NewJeans": "morekpop",
    "Dreamcatcher": "morekpop",
    "BLACKPINK": "morekpop",
    "LE SSERAFIM": "morekpop",
    "BINI": "morekpop",
    "Forestella": "morekpop",
    "WOODZ": "morekpop",
    "Kim Jong Kook": "morekpop",
    "Rain": "morekpop",
    "CNBLUE": "morekpop",
    "JYP": "morekpop",
    "DAY6": "morekpop",
    "Xdinary Heroes": "morekpop",
    "PSY": "morekpop",
    # Additional K-pop groups (May data)
    "Taeyang": "morekpop",                   # Dani 2026-05-13: BIGBANG soloist, not BTS
    "MAMAMOO": "morekpop",
    "Mamamoo": "morekpop",
    "aespa": "morekpop",
    "Aespa": "morekpop",
    "Taeyeon": "morekpop",
    "NCT": "morekpop",
    "NCT DREAM": "morekpop",
    "NCT 127": "morekpop",
    "NCT U": "morekpop",
    "(G)I-DLE": "morekpop",
    "G-IDLE": "morekpop",
    "Ailee": "morekpop",
    "Girls' Generation": "morekpop",
    "SNSD": "morekpop",
    "TVXQ": "morekpop",
    "BIGBANG": "morekpop",
    "Big Bang": "morekpop",
    "P1 Harmony": "morekpop",
    "P1H": "morekpop",
    "Wonho": "morekpop",
    "KISS OF LIFE": "morekpop",
    "Babymonster": "morekpop",
    "BABYMONSTER": "morekpop",
    "Super Junior": "morekpop",
    "BTOB": "morekpop",
    "Sungjae": "morekpop",
    "Cortis": "morekpop",
    "CORTIS": "morekpop",
    "Xikers": "morekpop",
    "xikers": "morekpop",                    # Dani 2026-05-13: not Stray Kids
    "KATSEYE": "morekpop",
    "Monsta X": "morekpop",
    "Meovv": "morekpop",
    "MEOVV": "morekpop",
    "Jessi": "morekpop",
    "Hwasa": "morekpop",
    "FTISLAND": "morekpop",
    "AKMU": "morekpop",
    "XG": "morekpop",
    "IU": "morekpop",
    "MODYSSEY": "morekpop",                  # User call
    "Jun (SEVENTEEN)": "morekpop",
    "Tablo": "morekpop",                     # User call (Epik High)
    # ============================================================
    # Europe / Eurovision
    # ============================================================
    "Vesna": "euro",
    "Berq": "euro",
    "ok.danke.tschüss": "euro",
    "AnnenMayKantereit": "euro",
    "Bambi Thug": "euro",
    "SOFIA ISELLA": "euro",
    "Stromae": "euro",
    "Blumengarten": "euro",
    "Paula Hartmann": "euro",
    "Slimane": "euro",
    "Käärijä": "euro",
    "Baby Lasagna": "euro",
    "Kovacs": "euro",
    "Alexander Rybak": "euro",
    "Faouzia": "euro",                       # User call
    "Şebnem Ferah": "euro",
    "Maneskin": "euro",
    "Måneskin": "euro",
    "Provinz": "euro",
    "Florence": "euro",                      # User call
    # ============================================================
    # Rock / Metal (Western rock/metal/alt/indie/folk/comedy-musical)
    # ============================================================
    "My Chemical Romance": "rock",
    "The Warning": "rock",
    "AURORA": "rock",
    "Nightwish": "rock",
    "Tarja": "rock",
    "Fall Out Boy": "rock",
    "Band-Maid": "rock",
    "Tom Cardy": "rock",
    "Bo Burnham": "rock",
    "Paris Paloma": "rock",
    "Mitski": "rock",
    "Devin Townsend": "rock",
    "Ayreon": "rock",
    "Jessie J": "rock",
    "Melanie Martinez": "rock",
    "Nickelback": "rock",
    "Lizzy McAlpine": "rock",
    "HONK THE HORN": "vtuber",                  # Mr.UNAWARE 2026-05-31: VTuber duo, not rock
    "The Struts": "rock",
    "Alestorm": "rock",
    "Bad Omens": "rock",
    "Sufjan Stevens": "rock",
    "Matt Masson": "rock",
    "ReVamp": "rock",
    "Delta Goodrem": "rock",
    "Rina Sawayama": "rock",
    "The Rose": "rock",                      # User call (Korean rock band)
    "The Midnight": "rock",
    "Floor Jansen": "rock",
    "Noah Kahan": "rock",
    # ============================================================
    # Other (catch-all: non-K/J/Eur/Rock, games, anime, misc)
    # ============================================================
    "F.HERO": "other",
    "MILLI": "other",
    "SB19": "other",                         # Dani 2026-05-13: Filipino, not Korean
    "Jeff Satur": "other",                   # Dani 2026-05-13: Thai, not Korean
    "Casey Edwards": "other",
    "Arcane": "other",
    "Final Fantasy": "other",
    "Final Fantasy VII Remake": "other",
    "Final Fantasy XVI": "other",
    "Cup of Joe": "other",
    "LYKN": "other",
    "William Jakrapatr": "other",
    "Cécilia Cara": "other",
    "Black Gryphon": "other",
    "HOYO-MiX": "other",
    "Ladrones": "other",
    "Voiceplay": "other",
    "Chalkeaters": "other",
    "Christopher Tin": "other",
    "Cristopher Tin": "other",
    "Gorillaz": "other",                     # User call
    "Tia Ray": "other",
    "Doja Cat": "other",
    "NSP": "other",
    "Ninja Sex Party": "other",
    "K/DA": "other",
    "Pentakill": "other",
    "Slayyyter": "other",
    "The Curse of the Sad Mummy": "other",
}

# Lowercase lookup so categorize() handles varied casing from the heuristic
# extractor (e.g. "Bao the whale" vs "Bao the Whale").
_ARTIST_TO_TAB_LOWER = {k.lower(): v for k, v in ARTIST_TO_TAB.items()}

# Strip parenthetical AND "- Vtuber" / "- Hololive" / "- Holostars" dash-suffixes.
# Commenters often append these as a community tag after the artist name
# (e.g. "Otonose Kanade - Vtuber", "Hakka Banzoin(Vtuber)").
_STRIP_SUFFIX_RE = re.compile(
    r"\s*("
    r"\([^)]+\)"                                # (anything)
    r"|"
    r"[-–—]\s*(?:vtuber|hololive|holostars)"    # - Vtuber / -Hololive / etc.
    r")\s*$",
    re.IGNORECASE,
)


def _build_stripped_lookup(lower_lookup):
    """Stripped-suffix lookup so "Nerissa Ravencroft" matches
    "Nerissa Ravencroft (Hololive)". Drops entries where two different full
    names strip to the same key with conflicting tabs."""
    candidates = {}
    for full_lower, tab in lower_lookup.items():
        stripped = _STRIP_SUFFIX_RE.sub("", full_lower).strip()
        if not stripped or stripped == full_lower or stripped in lower_lookup:
            continue
        if stripped in candidates and candidates[stripped] != tab:
            candidates[stripped] = None  # ambiguous — drop
        elif stripped not in candidates:
            candidates[stripped] = tab
    return {k: v for k, v in candidates.items() if v is not None}


_ARTIST_TO_TAB_STRIPPED = _build_stripped_lookup(_ARTIST_TO_TAB_LOWER)

# Precompiled word-boundary patterns for substring fallback in categorize().
# Lets us route "Break-OBKATIEKAT" → vtuber because OBKATIEKAT appears as a
# word inside the messy heuristic-extracted string. Min length 5 avoids
# matching short generic strings (BTS/NCT/etc. are handled via canonical
# names path instead).
_KNOWN_ARTIST_PATTERNS = [
    (re.compile(r"\b" + re.escape(name.lower()) + r"\b"), tab)
    for name, tab in sorted(ARTIST_TO_TAB.items(), key=lambda kv: -len(kv[0]))
    if len(name) >= 5
]


def _is_known_artist(s):
    """True iff `s` resolves to a known artist via ARTIST_TO_TAB (direct or
    stripped) or CANONICAL_NAMES (word-boundary). Used by the heuristic
    fallback to detect reversed "Song — Artist" comment orderings."""
    if not s:
        return False
    s_lower = s.lower()
    if s_lower in _ARTIST_TO_TAB_LOWER or s_lower in _ARTIST_TO_TAB_STRIPPED:
        return True
    stripped = _STRIP_SUFFIX_RE.sub("", s_lower).strip()
    if stripped and stripped != s_lower:
        if stripped in _ARTIST_TO_TAB_LOWER or stripped in _ARTIST_TO_TAB_STRIPPED:
            return True
    canonical, _ = find_canonical_artist_safe(s_lower)
    return canonical is not None

# Pre-sort CANONICAL_NAMES keys longest-first (longest match wins).
_CANONICAL_KEYS_BY_LEN = sorted(CANONICAL_NAMES.keys(), key=len, reverse=True)

# Short canonical keys that produce false positives via naive substring matching
# (e.g. "ive" inside "live", "eve" inside "every", "ado" inside "shadow",
# "rain" inside "brain"). These require a word-boundary match to register.
# The aggregator already guards "han" and "v" inline.
_AMBIGUOUS_SHORT_KEYS = {"ive", "eve", "ado", "rain"}


def find_canonical_artist_safe(text_lower):
    """Like the aggregator's _find_canonical_artist but with word-boundary
    guards for short ambiguous keys. Returns (canonical_name, matched_key) or
    (None, None)."""
    best_match = None
    best_key = None
    best_len = 0
    for key, canonical in sorted(CANONICAL_NAMES.items(), key=lambda x: -len(x[0])):
        if len(key) < 3:
            continue
        if key == "han" and "stray" not in text_lower and "skz" not in text_lower:
            continue
        if key == "v" and "bts" not in text_lower:
            continue
        if key in _AMBIGUOUS_SHORT_KEYS:
            present = re.search(r"\b" + re.escape(key) + r"\b", text_lower) is not None
        else:
            present = key in text_lower
        if present and len(key) > best_len:
            best_match = canonical
            best_key = key
            best_len = len(key)
    return best_match, best_key


YOUTUBE_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com|youtu\.be|m\.youtube\.com)/\S+",
    re.IGNORECASE,
)


# ============================================================
# DATA LOADING
# ============================================================

def load_scrape(path):
    """Returns (current_month_label, list[comment])."""
    with open(path, "r", encoding="utf-8") as f:
        posts = json.load(f)
    month = posts[0].get("month", "Current Month") if posts else "Current Month"
    comments = []
    for post in posts:
        for c in post.get("structured", []):
            if c.get("hearts", 0) > 0:
                comments.append(c)
    return month, comments


def load_overrides(path):
    """Returns (thresholds_by_tab, overrides_by_dedup_key).
    Missing file is OK — returns empty dicts with smart-default fallback."""
    if not os.path.exists(path):
        print(f"    No overrides file at {path}; using built-in defaults.")
        return {}, {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    thresholds = data.get("thresholds", {})
    raw_overrides = data.get("overrides", [])
    attribution_fixes = data.get("attribution_fixes", [])
    valid_tabs = {t[0] for t in TAB_DEFINITIONS}
    valid_badges = {"scheduled", "done", "queue", "partial"}

    # Validate thresholds
    for tab_key, cfg in thresholds.items():
        if tab_key not in valid_tabs:
            sys.exit(f"  ❌ Unknown tab '{tab_key}' in thresholds. Valid: {sorted(valid_tabs)}")
        if cfg.get("min_hearts", 0) < 0:
            sys.exit(f"  ❌ Negative min_hearts for '{tab_key}'.")
        top_pct = cfg.get("top_pct", 20)
        if not 0 <= top_pct <= 100:
            sys.exit(f"  ❌ top_pct {top_pct} out of range for '{tab_key}'.")

    # Validate + index overrides
    overrides_by_key = {}
    for o in raw_overrides:
        artist, song = o.get("artist", ""), o.get("song", "")
        badge, badge_text = o.get("badge", ""), o.get("badge_text", "")
        if not artist or not song:
            sys.exit(f"  ❌ Override missing artist/song: {o}")
        if badge not in valid_badges:
            sys.exit(f"  ❌ Invalid badge '{badge}' for {artist} | {song}")
        if not badge_text:
            sys.exit(f"  ❌ Missing badge_text for {artist} | {song}")
        key = _dedup_key(artist, song)
        if key in overrides_by_key:
            sys.exit(f"  ❌ Duplicate override for {artist} | {song}")
        overrides_by_key[key] = {
            "badge": badge,
            "badge_text": badge_text,
            "note": o.get("note", ""),
            "ctx": o.get("ctx", ""),
            "artist": artist,
            "song": song,
        }
    return thresholds, overrides_by_key, attribution_fixes


def _find_balanced_div(text, start_marker):
    """Find start_marker (must be an opening <div ...> substring) and return the
    full element including matching </div>. Counts nested <div> only."""
    start_idx = text.find(start_marker)
    if start_idx < 0:
        return None, -1
    pos = text.find(">", start_idx) + 1
    depth = 1
    while depth > 0:
        next_open = text.find("<div", pos)
        next_close = text.find("</div>", pos)
        if next_close < 0:
            return None, -1
        if 0 <= next_open < next_close:
            depth += 1
            pos = next_open + 4
        else:
            depth -= 1
            pos = next_close + 6
    return text[start_idx:pos], pos


def _parse_cumulative_tab_counts(template_text):
    counts = {}
    for m in re.finditer(
        r'<div class="tab(?:\s+active)?"\s+data-tab="(\w+)"[^>]*?data-cumulative-count="([^"]*)"',
        template_text,
    ):
        counts[m.group(1)] = m.group(2)
    return counts


def _parse_cumulative_sections(template_text):
    """Extract every cumulative-mode genre-section keyed by tab key."""
    sections = {}
    pos = 0
    while True:
        idx = template_text.find('<div class="genre-section', pos)
        if idx < 0:
            break
        tag_end = template_text.find(">", idx)
        opening = template_text[idx:tag_end + 1]
        m = re.search(r'data-tab="all (\w+)"', opening)
        if not m or 'data-mode="cumulative"' not in opening:
            pos = tag_end + 1
            continue
        tab_key = m.group(1)
        full, end_pos = _find_balanced_div(template_text, opening)
        if full:
            sections[tab_key] = full
            pos = end_pos
        else:
            pos = tag_end + 1
    return sections


def load_template(path):
    """Parse the template tracker file and extract verbatim blocks."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    parts = {}

    m = re.search(r"<style>.*?</style>", text, re.DOTALL)
    parts["style"] = m.group(0) if m else "<style></style>"

    m = re.search(r"<h1>.*?</h1>", text, re.DOTALL)
    parts["h1"] = m.group(0) if m else "<h1>TWVS Community Request Tracker</h1>"

    m = re.search(r'<div class="subtitle">.*?</div>', text, re.DOTALL)
    parts["subtitle"] = m.group(0) if m else '<div class="subtitle"></div>'

    div, _ = _find_balanced_div(text, '<div class="beta-banner">')
    parts["beta_banner"] = div or ""

    div, _ = _find_balanced_div(text, '<div class="mode-toggle">')
    parts["mode_toggle"] = div or ""

    div, _ = _find_balanced_div(text, '<div class="mode-content active" data-mode="cumulative">')
    parts["cumulative_mode_content"] = div or ""

    m = re.search(r'<input class="search"[^>]*>', text)
    parts["search_input"] = (
        m.group(0) if m
        else '<input class="search" type="text" placeholder="Search requests..." oninput="filterRequests(this.value)">'
    )

    parts["cumulative_tab_counts"] = _parse_cumulative_tab_counts(text)
    parts["cumulative_sections"] = _parse_cumulative_sections(text)

    div, _ = _find_balanced_div(text, '<div class="done-note" data-mode="cumulative">')
    parts["done_note"] = div or ""

    m = re.search(r"<script>.*?</script>", text, re.DOTALL)
    parts["script"] = m.group(0) if m else "<script>showMode('cumulative');</script>"

    return parts


# ============================================================
# ENTRY PROCESSING
# ============================================================

def extract_youtube_url(text):
    m = YOUTUBE_RE.search(text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,;)\"'")


def extract_entry(comment):
    """Returns {commenter, hearts, artist, song, youtube_url, raw_text} or None."""
    text = comment.get("text", "") or ""
    hearts = comment.get("hearts", 0) or 0
    commenter = (comment.get("name") or "Anonymous").strip()

    # Community genre prefix wins over the artist heuristic. Strip it so the
    # genre token (e.g. "Vtuber") is never mistaken for the artist downstream.
    genre_tab, text = split_genre_prefix(text)

    # Artist/song live in the "Artist — Song" head, BEFORE the link + description.
    # Scope detection to that head so a name mentioned later in the prose (e.g.
    # "reminds me of Houshou Marine") can't hijack the artist. Fixes false
    # positives like Toby Fox→"Houshou Marine" and Mafumafu→"MILLI".
    head = re.split(r"https?://", text, maxsplit=1)[0].split("\n")[0].strip()
    if not head:
        head = text  # pathological: link-first comment; fall back to full text
    text_lower = head.lower()

    artist, artist_key = find_canonical_artist_safe(text_lower)
    if artist_key is None:
        artist_key = ""

    song = _extract_song_title(head, artist_key)

    if not artist:
        # Heuristic fallback: parse "Artist — Song" from the head.
        # Try BOTH orderings — some comments are reversed as "Song — Artist".
        first_line = head
        parts = re.split(r"\s+[—–-]\s+", first_line, maxsplit=1)
        if len(parts) == 2:
            left = parts[0].strip()[:60]
            right = parts[1].strip()[:80]
            # If only the RIGHT side is a known artist, the comment is reversed.
            if _is_known_artist(right) and not _is_known_artist(left):
                artist = right
                if not song:
                    song = left
            else:
                artist = left
                if not song:
                    song = right
        else:
            artist = first_line[:60] or None
        if not artist:
            return None  # genuinely unparseable

    if not song:
        song = "General Request"

    artist, song = _resolve_song_alias(artist, song)

    return {
        "commenter": commenter,
        "hearts": hearts,
        "artist": artist,
        "song": song,
        "genre_tab": genre_tab,
        "youtube_url": extract_youtube_url(text),
        "raw_text": text,
    }


def apply_attribution_fixes(entries, fixes):
    """Correct known-wrong (artist, song) attributions before dedup.

    Each fix has shape:
      {"match": {"artist": "<orig>", "song_contains": "<substr>"},
       "fix":   {"artist": "<correct>", "song": "<correct>"}}

    The match clause is conservative: requires BOTH artist exact (case-insensitive)
    AND song substring (case-insensitive). After applying, dedup will collapse
    multiple entries that now share the same (corrected_artist, song) key."""
    if not fixes:
        return 0
    n = 0
    for e in entries:
        artist_lower = (e["artist"] or "").lower()
        song_lower = (e["song"] or "").lower()
        for fix in fixes:
            m = fix.get("match", {})
            f = fix.get("fix", {})
            if "artist" in m and m["artist"].lower() != artist_lower:
                continue
            if "song_contains" in m and m["song_contains"].lower() not in song_lower:
                continue
            e["artist"] = f.get("artist", e["artist"])
            e["song"] = f.get("song", e["song"])
            n += 1
            break
    return n


# Genre prefixes the community now puts at the FRONT of each request
# (Tim's 2026-06 rule). When present, the human-supplied genre is authoritative
# and overrides the artist heuristic — this is the fix for the chronic
# miscategorization complaints. K-Pop is intentionally absent: those requests
# live on the separate K-Pop post and route by artist (skz/bts/ateez/enhypen/
# morekpop) via categorize(), so a generic "kpop" prefix must NOT collapse them.
_GENRE_ALIASES = {
    "vtuber": "vtuber", "vtubers": "vtuber", "v-tuber": "vtuber", "vsinger": "vtuber",
    "jpop": "jpop", "j-pop": "jpop", "j pop": "jpop", "jrock": "jpop", "j-rock": "jpop",
    "vocaloid": "jpop", "utaite": "jpop",
    "anime": "anime", "anime series": "anime", "anime ost": "anime", "anime song": "anime",
    "video game": "game", "videogame": "game", "video games": "game", "game": "game",
    "vgm": "game", "game music": "game", "gaming": "game",
    "europe": "euro", "eurovision": "euro", "euro": "euro", "european": "euro",
    "rock": "rock", "metal": "rock", "rock/metal": "rock", "rock / metal": "rock",
    "other": "other", "pop": "other", "art pop": "other", "musical": "other",
    "musical theatre": "other", "soundtrack": "other",
}
# Recognize "[Genre] …" or "Genre - …" / "Genre: …" at the very start.
_GENRE_BRACKET_RE = re.compile(r"^\s*\[([^\]]{1,40})\]\s*[-–—:·]*\s*")
_GENRE_DASH_RE = re.compile(r"^\s*([A-Za-z][\w /&+.\-]{0,30}?)\s*[-–—:]\s+")


def _match_genre(token):
    """Map a leading genre token to a tab key, or None if it isn't a genre we
    route on (so the caller leaves the text untouched and falls back to the
    artist heuristic)."""
    t = re.sub(r"\s+", " ", (token or "")).strip().lower().strip("[]").strip()
    if not t:
        return None
    if t in _GENRE_ALIASES:
        return _GENRE_ALIASES[t]
    # Compound tokens like "europe / lgbtqai+" or "anime series (sub)".
    for alias, tab in _GENRE_ALIASES.items():
        if t == alias or t.startswith(alias + " ") or t.startswith(alias + "/") or t.startswith(alias + " /"):
            return tab
    first = t.split()[0] if t.split() else ""
    return _GENRE_ALIASES.get(first)


def split_genre_prefix(text):
    """Return (tab_key_or_None, text_without_prefix). Only strips/recognizes a
    leading token that maps to a known genre; otherwise returns the text intact
    so non-prefixed requests (e.g. 'SOFIA ISELLA - The Doll People') are
    unaffected."""
    if not text:
        return None, text
    m = _GENRE_BRACKET_RE.match(text)
    if m:
        tab = _match_genre(m.group(1))
        if tab:
            return tab, text[m.end():]
        return None, text  # bracketed but not a known genre — leave intact
    m = _GENRE_DASH_RE.match(text)
    if m:
        tab = _match_genre(m.group(1))
        if tab:
            return tab, text[m.end():]
    return None, text


def categorize(artist):
    """Map an artist name to a tab key. Walks the lookup chain from most
    specific to most permissive: direct → stripped-suffix → input-suffix-strip
    → canonical-names word-boundary → known-artist substring. 'other' if
    nothing matches."""
    a = (artist or "").lower()
    if a in _ARTIST_TO_TAB_LOWER:
        return _ARTIST_TO_TAB_LOWER[a]
    if a in _ARTIST_TO_TAB_STRIPPED:
        return _ARTIST_TO_TAB_STRIPPED[a]
    stripped = _STRIP_SUFFIX_RE.sub("", a).strip()
    if stripped and stripped != a:
        if stripped in _ARTIST_TO_TAB_LOWER:
            return _ARTIST_TO_TAB_LOWER[stripped]
        if stripped in _ARTIST_TO_TAB_STRIPPED:
            return _ARTIST_TO_TAB_STRIPPED[stripped]
    # Canonical-names word-boundary fallback: catches plain names like
    # "Mumei" / "Marine" / "Suisei" that map via CANONICAL_NAMES to a
    # suffix-bearing dict entry.
    canonical, _ = find_canonical_artist_safe(a)
    if canonical:
        canonical_lower = canonical.lower()
        if canonical_lower in _ARTIST_TO_TAB_LOWER:
            return _ARTIST_TO_TAB_LOWER[canonical_lower]
    # Substring fallback: a known artist appears as a word inside the input
    # (catches "Break-OBKATIEKAT", "Hollow Hunger- Octavio(Vtuber)" etc.).
    for pattern, tab in _KNOWN_ARTIST_PATTERNS:
        if pattern.search(a):
            return tab
    return "other"


# ============================================================
# DEDUP & MERGE
# ============================================================

def dedup_and_merge(entries):
    """Group entries by (artist, song) canonical key. Multiple commenters
    requesting the same song merge into ONE row with summed hearts."""
    groups = {}

    for e in entries:
        key = _dedup_key(e["artist"], e["song"])
        if key not in groups:
            groups[key] = {
                "key": key,
                "artist": e["artist"],
                "song": e["song"],
                "hearts": 0,
                "contributions": defaultdict(int),
                "youtube_url": None,
                "raw_ctxs": [],
                "genre_tab": None,
            }
        g = groups[key]
        g["hearts"] += e["hearts"]
        g["contributions"][e["commenter"]] += e["hearts"]
        if not g["youtube_url"] and e["youtube_url"]:
            g["youtube_url"] = e["youtube_url"]
        if not g["genre_tab"] and e.get("genre_tab"):
            g["genre_tab"] = e["genre_tab"]
        g["raw_ctxs"].append(e["raw_text"])

    rows = []
    for g in groups.values():
        # Requesters ordered by individual heart contribution desc, then name asc
        requesters = sorted(
            g["contributions"].keys(),
            key=lambda n: (-g["contributions"][n], n.lower()),
        )
        rows.append({
            "key": g["key"],
            "artist": g["artist"],
            "song": g["song"],
            "hearts": g["hearts"],
            "requesters": requesters,
            "youtube_url": g["youtube_url"],
            "raw_ctxs": g["raw_ctxs"],
            # Human-supplied genre prefix is authoritative; fall back to the
            # artist heuristic only when no genre was given.
            "tab_key": g["genre_tab"] or categorize(g["artist"]),
        })
    return rows


# ============================================================
# THRESHOLDS & RANKING
# ============================================================

def get_threshold(tab_key, thresholds_cfg):
    cfg = thresholds_cfg.get(tab_key, DEFAULT_THRESHOLDS)
    return (
        cfg.get("min_hearts", DEFAULT_THRESHOLDS["min_hearts"]),
        cfg.get("top_pct", DEFAULT_THRESHOLDS["top_pct"]),
    )


def apply_thresholds(rows, tab_key, thresholds_cfg):
    """Returns (kept_rows_sorted_desc, set_of_top_indices)."""
    min_hearts, top_pct = get_threshold(tab_key, thresholds_cfg)
    kept = sorted(
        (r for r in rows if r["hearts"] >= min_hearts),
        key=lambda r: (-r["hearts"], r["artist"].lower(), r["song"].lower()),
    )
    if not kept:
        return [], set()
    n_top = max(1, math.ceil(len(kept) * top_pct / 100))
    return kept, set(range(n_top))


def init_badges(rows):
    """Initialize badge fields to empty defaults. Run before applying log/overrides."""
    for r in rows:
        r["badge"], r["badge_text"], r["note"], r["ctx"] = None, "", "", ""


def format_completion_date(date_str):
    """'2026-05-06' → 'MAY 6' (no leading zero)."""
    if not date_str:
        return ""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return ""
    return d.strftime("%b ") + str(d.day) + d.strftime(" %Y")[:0] or d.strftime("%b ") + str(d.day)


def _format_done_badge_text(date_str):
    """Returns '✅ DONE MAY 6' or '📺 DONE' if no date."""
    if not date_str:
        return "📺 DONE"
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return "📺 DONE"
    return f"✅ DONE {d.strftime('%b').upper()} {d.day}"


# Community-tag tokens that should be stripped before deciding if a request is
# "generic" (artist-only) vs "specific" (a named song). E.g. "Hoshimachi Suisei-Vtuber"
# should be treated the same as "Hoshimachi Suisei" for the purpose of detection.
GENERIC_TAG_TOKENS = {"vtuber", "hololive", "holostars", "kpop", "korean", "vt"}


def _normalize_for_match(s):
    """Lowercase, replace non-word chars with space, collapse whitespace."""
    s = re.sub(r"[^\w]+", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def is_generic_request(artist, song):
    """A request is 'generic' (artist-only, no specific song named) iff the
    song's significant tokens equal the artist's significant tokens after
    stripping community tags like (Hololive), -Vtuber, etc.

    Examples (all return True):
      9lana | 9Lana
      Mori Calliope (Hololive) | Mori Calliope
      Hoshimachi Suisei (Hololive) | Hoshimachi Suisei-Vtuber
      Akuma Nihmune | Akuma Nihmune

    Examples (all return False — specific song):
      Aespa- Dirty Work | Dirty Work      (heuristic-extracted; Dirty Work is a song)
      Stray Kids | LOVER
      Mori Calliope (Hololive) | End of a Life
    """
    if not song:
        return True
    if song.strip().lower() in ("general request", "general"):
        return True
    a_tokens = [t for t in _normalize_for_match(artist).split() if t not in GENERIC_TAG_TOKENS]
    s_tokens = [t for t in _normalize_for_match(song).split() if t not in GENERIC_TAG_TOKENS]
    if not s_tokens:
        return True
    return a_tokens == s_tokens


def load_completed_log(path):
    """Returns (lookup_by_key, lookup_by_artist). The artist lookup powers the
    generic-request rule: 'any song by artist filmed' → generic artist row DONE."""
    if not os.path.exists(path):
        return {}, {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    by_key = {e["key"]: e for e in data.get("done", [])}
    by_artist = defaultdict(list)
    for e in data.get("done", []):
        by_artist[_normalize_for_match(e["artist"])].append(e)
    return by_key, dict(by_artist)


def _apply_done_entry(row, entry, generic_match_song=None):
    """Apply DONE/PARTIAL fields from a log entry onto a row."""
    status = entry.get("status", "done")
    date_str = entry.get("completed_date", "")
    if status == "partial":
        row["badge"] = "partial"
        row["badge_text"] = "PARTIAL"
        row["note"] = entry.get("note", "")
        return
    row["badge"] = "done"
    row["badge_text"] = _format_done_badge_text(date_str)
    note = entry.get("note", "")
    if not note:
        if generic_match_song:
            note = f"Most recent: {generic_match_song}"
        elif entry.get("source_title"):
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                when = d.strftime("%b ") + str(d.day)
                note = f"Done {when} — {entry['source_title']}"
            except ValueError:
                note = f"Done — {entry['source_title']}"
    row["note"] = note


def apply_completion_log(rows, completed_lookup, completed_by_artist):
    """Auto-badge rows that appear in the persistent completed log.

    Two-pass matching:
      1. Direct key match (specific song confirmed done) — straightforward.
      2. Generic-request rule: if the row is a generic artist-only request AND
         the artist has at least one entry in the log, badge with the most
         recent filmed song's date. Specific-song requests never get satisfied
         by a different song; they need an exact key match (Rule 77)."""
    matched = set()
    for r in rows:
        # 1. Direct match wins (specific song confirmation)
        c = completed_lookup.get(r["key"])
        if c:
            _apply_done_entry(r, c)
            matched.add(r["key"])
            continue
        # 2. Generic-request rule
        if is_generic_request(r["artist"], r["song"]):
            artist_norm = _normalize_for_match(r["artist"])
            entries = completed_by_artist.get(artist_norm, [])
            if entries:
                latest = max(entries, key=lambda e: e.get("completed_date") or "")
                _apply_done_entry(r, latest, generic_match_song=latest.get("song", ""))
                matched.add(r["key"])
    return matched


def apply_overrides(rows, overrides_by_key):
    """Per-month overrides win on top of completed-log badges."""
    matched = set()
    for r in rows:
        o = overrides_by_key.get(r["key"])
        if o:
            r["badge"], r["badge_text"] = o["badge"], o["badge_text"]
            r["note"], r["ctx"] = o["note"], o["ctx"]
            matched.add(r["key"])
    return matched


# ============================================================
# RENDERING
# ============================================================

def esc(s):
    return html.escape(str(s), quote=True)


_BADGE_CLASS = {
    "scheduled": "scheduled-badge", "done": "done-badge",
    "queue": "queue-badge", "partial": "partial-badge",
}
_NOTE_CLASS = {
    "scheduled": "scheduled-note", "done": "scheduled-note",
    "queue": "queue-note", "partial": "partial-note",
}


def render_badge(badge, text):
    if not badge:
        return ""
    return f'<span class="{_BADGE_CLASS[badge]}">{esc(text)}</span>'


def render_note(badge, text):
    if not text or not badge:
        return ""
    return f' · <span class="{_NOTE_CLASS[badge]}">{esc(text)}</span>'


def render_yt(url):
    if not url:
        return ""
    return f' <a href="{esc(url)}" target="_blank" rel="noopener" class="yt-link">▶</a>'


def render_requesters(requesters, limit=6):
    if not requesters:
        return ""
    if len(requesters) <= limit:
        return ", ".join(esc(r) for r in requesters)
    shown = ", ".join(esc(r) for r in requesters[:limit])
    return f"{shown} (+{len(requesters) - limit} more)"


def render_row(row, is_top):
    hearts_cls = "hearts top" if is_top else "hearts"
    title = esc(f"{row['artist']} — {row['song']}")
    yt = render_yt(row["youtube_url"])
    badge = render_badge(row["badge"], row["badge_text"])
    meta_parts = [render_requesters(row["requesters"])]
    if row["ctx"]:
        meta_parts.append(f'<span class="ctx">{esc(row["ctx"])}</span>')
    note = render_note(row["badge"], row["note"])
    meta = " · ".join(p for p in meta_parts if p) + note
    return (
        f'<div class="req"><span class="{hearts_cls}">{row["hearts"]}</span>'
        f'<div class="content"><div class="song">{title}{yt}{badge}</div>'
        f'<div class="meta">{meta}</div></div></div>'
    )


def render_current_genre_section(tab_key, h2, rows, top_indices, current_month):
    total_hearts = sum(r["hearts"] for r in rows)
    header = (
        f'<div class="genre-header"><h2>{esc(h2)}</h2>'
        f'<span class="genre-count">{esc(current_month)} · {len(rows)} requests · {total_hearts} ❤️</span></div>'
    )
    rows_html = "\n".join(render_row(r, i in top_indices) for i, r in enumerate(rows))
    return (
        f'<div class="genre-section" data-tab="all {tab_key}" data-mode="current">\n'
        f'{header}\n{rows_html}\n</div>'
    )


def render_current_mode_content(total_requests, total_hearts, scheduled_count, queue_count, current_month):
    return (
        f'<div class="mode-content" data-mode="current">\n'
        f'<div class="scope">{esc(current_month)} · top-level comments only on the {esc(current_month)} General Requests post + {esc(current_month)} K-Pop Requests post. Source: <code>song_requests.json</code> (clean nightly scrape — replies / agreement comments never rendered).</div>\n'
        f'<div class="audit-note"><strong>v6 BETA · current month:</strong> Each entry shows hearts, song title, requester, optional context, and YouTube link (▶ button). Status badges: '
        f'<span class="scheduled-badge">✅ SCHEDULED</span> = on calendar. '
        f'<span class="done-badge">📺 DONE</span> = already in library. '
        f'<span class="queue-badge">⏳ JUNE</span> = in next-month queue. '
        f'Bare entry = open / candidate for slotting.</div>\n'
        f'<div class="stats">\n'
        f'<div class="stat"><div class="num">{total_requests}</div><div class="lbl">{esc(current_month)} Requests</div></div>\n'
        f'<div class="stat"><div class="num">{total_hearts:,}</div><div class="lbl">Total Hearts</div></div>\n'
        f'<div class="stat"><div class="num">{scheduled_count}</div><div class="lbl">Already Honored</div></div>\n'
        f'<div class="stat"><div class="num">{queue_count}</div><div class="lbl">Next-Month Queue</div></div>\n'
        f'</div>\n'
        f'<div class="legend"><strong>Reading the badges:</strong> green ✅ = on calendar ({scheduled_count}). Muted green 📺 = library (0). Purple ⏳ = next-month queue ({queue_count}). Bare = open / candidate for slotting. Click ▶ to open the requester\'s YouTube link in a new tab.</div>\n'
        f'</div>'
    )


def render_tabs(current_counts, cumulative_counts):
    out = [
        '<div class="tab active" data-tab="all" data-label="All" '
        'data-cumulative-count="" data-current-count="" '
        'onclick="showTab(\'all\')">All</div>'
    ]
    for tab_key, display_label, _ in TAB_DEFINITIONS:
        cum = cumulative_counts.get(tab_key, "")
        cur = current_counts.get(tab_key, "")
        # Page loads in cumulative mode by default, so visible text uses cum count
        visible = f"{display_label} ({cum})" if cum else display_label
        out.append(
            f'<div class="tab" data-tab="{tab_key}" data-label="{esc(display_label)}" '
            f'data-cumulative-count="{esc(cum)}" data-current-count="{esc(cur)}" '
            f'onclick="showTab(\'{tab_key}\')">{esc(visible)}</div>'
        )
    return '<div class="tabs">\n' + "\n".join(out) + "\n</div>"


def rewrite_subtitle(subtitle_html, today_str):
    if not subtitle_html:
        return subtitle_html
    return re.sub(
        r"Last updated: [A-Z][a-z]+ \d{1,2}, \d{4}",
        f"Last updated: {today_str}",
        subtitle_html,
    )


def build_tracker_html(rows_by_tab, top_idx_by_tab, template_parts,
                       current_month, scheduled_count, queue_count, today_str):
    current_counts = {}
    for tab_key, _, _ in TAB_DEFINITIONS:
        total = sum(r["hearts"] for r in rows_by_tab.get(tab_key, []))
        current_counts[tab_key] = f"{total} ❤️" if total else ""

    total_requests = sum(len(rows_by_tab.get(k, [])) for k, _, _ in TAB_DEFINITIONS)
    total_hearts = sum(
        sum(r["hearts"] for r in rows_by_tab.get(k, []))
        for k, _, _ in TAB_DEFINITIONS
    )

    current_sections = [
        render_current_genre_section(
            tab_key, h2, rows_by_tab.get(tab_key, []),
            top_idx_by_tab.get(tab_key, set()), current_month,
        )
        for tab_key, _, h2 in TAB_DEFINITIONS
    ]

    cumulative_sections_html = template_parts.get("cumulative_sections", {})
    cumulative_in_order = [
        cumulative_sections_html[k]
        for k, _, _ in TAB_DEFINITIONS
        if k in cumulative_sections_html
    ]

    subtitle = rewrite_subtitle(template_parts.get("subtitle", ""), today_str)
    cumulative_counts = template_parts.get("cumulative_tab_counts", {})

    parts = [
        # UTF-8 charset declaration — required for local file:// preview to render
        # em-dashes (—), heart emojis (❤️), and Japanese/Korean characters correctly.
        # Squarespace's surrounding page provides its own charset and ignores this.
        '<meta charset="utf-8">',
        template_parts["style"],
        template_parts["h1"],
        subtitle,
        template_parts["beta_banner"],
        "",
        template_parts["mode_toggle"],
        "",
        template_parts["cumulative_mode_content"],
        "",
        render_current_mode_content(total_requests, total_hearts,
                                    scheduled_count, queue_count, current_month),
        "",
        template_parts["search_input"],
        render_tabs(current_counts, cumulative_counts),
        *cumulative_in_order,
        *current_sections,
        "",
        template_parts["done_note"],
        template_parts["script"],
    ]
    return "\n".join(p for p in parts if p)


# ============================================================
# OUTPUT
# ============================================================

def write_keys_file(path, rows_by_tab):
    lines = [
        "# Reference list of every (tab | artist | song) key.",
        "# Copy artist+song from here when authoring tracker_overrides.json entries.",
        "# Format: TAB_KEY | ARTIST | SONG | HEARTS | TOP REQUESTERS",
        "",
    ]
    for tab_key, _, _ in TAB_DEFINITIONS:
        rows = rows_by_tab.get(tab_key, [])
        if not rows:
            continue
        lines.append(f"=== {tab_key} ({len(rows)} entries) ===")
        for r in rows:
            top3 = ", ".join(r["requesters"][:3])
            lines.append(f"{tab_key} | {r['artist']} | {r['song']} | {r['hearts']}♥ | {top3}")
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# MAIN
# ============================================================

def main():
    p = argparse.ArgumentParser(description="Generate the TWVS request tracker HTML.")
    p.add_argument("--scrape", default=os.path.expanduser("~/TWVS/data/song_requests.json"))
    p.add_argument("--overrides", default=os.path.expanduser("~/TWVS/data/tracker_overrides.json"))
    p.add_argument("--completed-log", default=os.path.expanduser("~/TWVS/data/tracker_completed.json"))
    p.add_argument("--template", default=os.path.expanduser("~/TWVS/data/tracker_FINAL.html"))
    p.add_argument("--output", default=os.path.expanduser("~/TWVS/data/tracker.html"))
    p.add_argument("--keys", default=os.path.expanduser("~/TWVS/data/tracker_keys.txt"))
    p.add_argument("--current-month", default=None,
                   help="Override the detected current-month label.")
    args = p.parse_args()

    print(f"  Generating tracker → {args.output}")

    current_month, comments = load_scrape(args.scrape)
    if args.current_month:
        current_month = args.current_month
    print(f"    Month: {current_month}")
    print(f"    {len(comments)} comments loaded")

    thresholds, overrides_by_key, attribution_fixes = load_overrides(args.overrides)
    print(f"    {len(overrides_by_key)} overrides loaded, "
          f"{len(attribution_fixes)} attribution-fix rules")

    completed_lookup, completed_by_artist = load_completed_log(args.completed_log)
    print(f"    {len(completed_lookup)} completed-log entries loaded "
          f"({len(completed_by_artist)} distinct artists)")

    template_parts = load_template(args.template)
    print(f"    Template: {len(template_parts.get('cumulative_sections', {}))} cumulative sections preserved")

    entries = []
    skipped = 0
    for c in comments:
        e = extract_entry(c)
        if e:
            entries.append(e)
        else:
            skipped += 1
    print(f"    {len(entries)} entries extracted ({skipped} skipped as unparseable)")

    n_fixed = apply_attribution_fixes(entries, attribution_fixes)
    if n_fixed:
        print(f"    {n_fixed} entries corrected by attribution_fixes")

    rows = dedup_and_merge(entries)
    print(f"    {len(rows)} unique rows after dedup")

    rows_by_tab_raw = defaultdict(list)
    for r in rows:
        rows_by_tab_raw[r["tab_key"]].append(r)

    rows_by_tab = {}
    top_idx_by_tab = {}
    all_matched = set()
    print("    Per-tab filtering:")
    for tab_key, _, _ in TAB_DEFINITIONS:
        tab_rows = rows_by_tab_raw.get(tab_key, [])
        kept, top_idx = apply_thresholds(tab_rows, tab_key, thresholds)
        init_badges(kept)
        apply_completion_log(kept, completed_lookup, completed_by_artist)
        matched = apply_overrides(kept, overrides_by_key)
        all_matched.update(matched)
        rows_by_tab[tab_key] = kept
        top_idx_by_tab[tab_key] = top_idx
        min_h, top_pct = get_threshold(tab_key, thresholds)
        print(f"      {tab_key:10s}: {len(tab_rows):3d} → {len(kept):3d} kept "
              f"(min ♥={min_h}, top {top_pct}%, {len(top_idx)} marked .top)")

    scheduled_count = sum(
        1 for rows in rows_by_tab.values() for r in rows
        if r["badge"] in ("scheduled", "done")
    )
    queue_count = sum(
        1 for rows in rows_by_tab.values() for r in rows
        if r["badge"] == "queue"
    )

    unmatched = set(overrides_by_key.keys()) - all_matched
    if unmatched:
        print(f"  ⚠️  {len(unmatched)} overrides didn't match any entry:")
        for key in sorted(unmatched):
            o = overrides_by_key[key]
            print(f"      {o['artist']} | {o['song']}")

    today_str = datetime.now().strftime("%B ") + str(datetime.now().day) + datetime.now().strftime(", %Y")
    html_out = build_tracker_html(
        rows_by_tab, top_idx_by_tab, template_parts,
        current_month, scheduled_count, queue_count, today_str,
    )
    Path(args.output).write_text(html_out, encoding="utf-8")
    print(f"  ✅ Wrote {args.output} ({len(html_out):,} bytes)")

    write_keys_file(args.keys, rows_by_tab)
    print(f"  ✅ Wrote {args.keys}")


if __name__ == "__main__":
    main()
