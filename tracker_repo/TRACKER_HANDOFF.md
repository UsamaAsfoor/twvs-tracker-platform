# TWVS Request Tracker — Developer Handoff

A rebuild of the community song-request tracker for Tim Welch Vocal Studio.
Built to replace a brittle regex tracker that chronically mis-sorted requests,
split heart counts, and falsely marked songs "done." This rebuild reads every
comment with an LLM, merges across months, and matches completions semantically.

**Please don't rebuild from scratch — the hard parts (accurate scraping, LLM
categorization, cross-month merge, DONE matching) work. The highest-value next
steps are TESTS and a CORRECTION UI (see bottom).**

---

## The finished artifact
- **`data/tracker_REBUILD_preview.html`** — the rebuilt tracker (self-contained:
  inline CSS + JS, reuses the live template's styling). This is what goes on
  Squarespace, replacing the current `tracker_TEST.html`/`tracker_FINAL.html`.
- 13 category tabs: Stray Kids, VTuber, BTS, J-Pop, ATEEZ, Europe/Eurovision,
  More K-Pop/Korean, ENHYPEN, Rock/Alt/Folk, Anime, Video Game, Musicals &
  Soundtracks, Pop & Misc.
- Two views (toggle): **Cumulative** (Oct'25→Jun'26, cross-month-merged hearts +
  per-month breakdown + 🔥 N-month persistence badges) and **Current Month**
  (every June request, no heart cutoff). ✅ DONE badges on completed songs.

## Pipeline (run in this order)
All scripts in `scripts/`, all data in `data/`. Python 3, deps: `playwright`,
plus an Anthropic API key in `~/TWVS/anthropic_api_key.txt` (Haiku model).

1. **`twvs_patreon_collector_v2.py`** — Playwright scraper (auth via persistent
   browser session). Section 4 scrapes the request posts → `song_requests.json`.
   Comment scraping is top-level-only (replies never expanded) with foolproof
   pagination + a count-reconciliation log. The monthly post URLs are in
   `SONG_REQUEST_URLS` near the top (update monthly; titles self-identify month).
   - Inspect modes (read-only): `--inspect-comments`, `--inspect-post <url>`,
     `--inspect`, `--test-conversions`.
2. **`llm_extract_requests.py`** — sends each comment to Claude →
   `{is_request, artist, song, category}`. Cached by comment hash
   (`song_requests_llm_cache.json`). Output: `song_requests_llm.json`.
3. **`llm_extract_library.py`** — reads all Patreon post + YouTube titles →
   which songs were actually studied (livestreams/admin excluded). Output:
   `library_done.json`. Cached (`library_done_cache.json`).
4. **`llm_match_done.py`** — semantically matches requests ↔ studied songs
   (handles typos like "Chk Chk Boom"="Chick Chick Boom", member-vs-group names,
   songs inside multi-song studies). Output: `done_matches.json`. `MANUAL_DONE`
   holds hand-entered completions.
5. **`rebuild_tracker_allmonths.py`** — the ENGINE. Builds per-month rows from
   the LLM extraction, cross-month-merges by normalized artist+song, applies
   category/attribution corrections (inline `CATEGORY_FIX`/`ATTRIB_FIX`), per-tab
   heart cutoffs + 3-month persistence, and DONE badges (incl. a HOP-solos
   special case). Output: `tracker_allmonths_engine.json` + `tracker_review.txt`.
   - `URL_MONTH` maps each post-id → (month, type). `TAB_CUTOFF` = per-tab heart
     thresholds. Imports helpers from `generate_tracker.py` (`TAB_DEFINITIONS`,
     `extract_youtube_url`, `esc`, etc.).
6. **`render_tracker_rebuild.py`** — renders the engine JSON → the final HTML,
   reusing the template's `<style>`/`<script>` via `generate_tracker.load_template`.

`generate_tracker.py` is the ORIGINAL (regex) generator — still the source of the
tab definitions, rendering helpers, and the HTML template parsing. The rebuild
chain (2–6 above) supersedes its categorization.

## Key design decisions (and why)
- **LLM extraction, not regex** — pre-April request comments are free-form prose
  ("Hi Tim! I'd love...King Gnu's Prayer X..."); regex can't parse them. The LLM
  reads meaning. This was the core fix.
- **Replies excluded at the source** — only top-level requests count; the scraper
  never clicks "Load replies" (DOM: replies live in a separate `sc-4c3b5dd-2`
  container under each thread). Verified; reconciliation log flags any drift.
- **Cross-month merge** — same song across months sums hearts (fixed split
  counts). Normalized key = lowercase, strip non-alphanumeric.
- **Per-tab cutoffs + persistence** — busy tabs 5♥, niche 3♥; a song in 3+ months
  with ≥2♥ is kept even below cutoff. Current month: no cutoff (show everything).
- **DONE = strict same-song-same-artist**, never artist-only (a "catalog" request
  stays open). Livestreams don't satisfy a request (only standalone studies).

## Known gaps / TODO
- **Bundle songs without listed titles** — e.g. a "10 SONG STUDY" post that doesn't
  name its songs can't be auto-matched for DONE. Handled ad-hoc (HOP solos hardcoded).
- **Long-tail categorization** — ~5% of low-heart entries are judgment calls.
- **`done_matches.json` re-runs the LLM** each time; could be incremental.

## Recommended next steps (per the prior analysis)
1. **Automated tests** — golden cases ("Chk Chk Boom"→done, a reply never counts,
   King Gnu hearts merge across months). Right now Tim is the test suite.
2. **A correction UI** — a small web form to fix a category / DONE mark / merge,
   writing to a corrections file the engine reads. Removes the code-edit loop;
   lets a non-coder maintain it.
3. **Consolidate** the script-chain into one pipeline with a real data model
   (each comment: stable id, is_reply, parsed fields, captured_at).
4. **Monthly upkeep**: update `SONG_REQUEST_URLS` with the new month's post URLs,
   re-run steps 1–6.

## Data dictionary (most relevant)
- `song_requests.json` — raw scraped comments per post (top-level only).
- `song_requests_llm.json` — per-comment `{is_request, artist, song, category}`.
- `library_done.json` — studied songs from the library.
- `done_matches.json` — request-key → matched completion.
- `tracker_allmonths_engine.json` — computed cumulative + current rows (the model).
- `tracker_review.txt` — human-readable per-tab list of displayed entries.
- `tracker_corrections_pending.md` — community-reported corrections log.
