#!/usr/bin/env python3
"""
Scoped re-scrape of the May song-request posts.

Runs only `scrape_song_requests` from twvs_patreon_collector_v2 — overwrites
~/TWVS/data/song_requests.{json,txt} and nothing else. No CSV exports
triggered, no Gmail IMAP, no chats, no notifications, no >7-day cleanup.

Usage: python3 ~/TWVS/scripts/scrape_song_requests_only.py
Prerequisite: no Chrome window may be using ~/TWVS/browser_session/.
"""

from playwright.sync_api import sync_playwright

from twvs_patreon_collector_v2 import (
    DOWNLOADS_DIR,
    SESSION_DIR,
    ensure_dirs,
    scrape_song_requests,
)


def main():
    ensure_dirs()
    with sync_playwright() as p:
        print("  Launching browser...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=True,
            downloads_path=DOWNLOADS_DIR,
            accept_downloads=True,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')

        scrape_song_requests(page)
        context.close()


if __name__ == "__main__":
    main()
