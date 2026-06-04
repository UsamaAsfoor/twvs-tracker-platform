#!/usr/bin/env python3
"""Scrape ONLY the two April 2026 request posts and merge them into the
existing song_requests.json — preserves every month already scraped, so you
don't have to re-run the full historical scrape just to add April.
"""
import json
import os

from playwright.sync_api import sync_playwright

import twvs_patreon_collector_v2 as C

DATA = os.path.expanduser("~/TWVS/data")
SR_JSON = os.path.join(DATA, "song_requests.json")

APRIL = [
    {"month": "April 2026", "type": "K-Pop",   "url": "https://www.patreon.com/posts/154519835"},
    {"month": "April 2026", "type": "General", "url": "https://www.patreon.com/posts/154516228"},
]

# 1. Keep everything already scraped (drop any prior April so we don't dupe).
existing = json.load(open(SR_JSON)) if os.path.exists(SR_JSON) else []
april_urls = {a["url"] for a in APRIL}
existing = [p for p in existing if p.get("url") not in april_urls]
print(f"  Preserving {len(existing)} already-scraped posts; scraping April (2 posts)...")

# 2. Scrape ONLY April (scrape_song_requests reads this global).
C.SONG_REQUEST_URLS = APRIL
C.ensure_dirs()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=C.SESSION_DIR,
        headless=True,
        downloads_path=C.DOWNLOADS_DIR,
        accept_downloads=True,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
    C.scrape_song_requests(page)   # overwrites song_requests.json with ONLY April
    ctx.close()

# 3. Merge April back in with the preserved months.
april = json.load(open(SR_JSON))
merged = existing + april
json.dump(merged, open(SR_JSON, "w"), ensure_ascii=False, indent=2)
print(f"\n✅ Done: {len(existing)} existing + {len(april)} April = {len(merged)} posts in song_requests.json")
