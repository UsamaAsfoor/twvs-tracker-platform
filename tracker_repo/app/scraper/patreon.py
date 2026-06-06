"""Patreon browser session management and comment scraping."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from app.config import SESSION_DIR, ensure_dirs
from app.pipeline.paths import patch_collector_module


def session_exists() -> bool:
    ensure_dirs()
    if not SESSION_DIR.is_dir():
        return False
    # Chromium profile has content when logged in at least once.
    return any(SESSION_DIR.iterdir())


def check_session_valid() -> tuple[bool, str]:
    """Quick headless check — returns (valid, message)."""
    if not session_exists():
        return False, "No browser session saved. Run Patreon login first."

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright not installed. Run: pip install playwright && playwright install chromium"

    collector = patch_collector_module()
    collector.ensure_dirs()

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=True,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.patreon.com/home", wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)
            url = page.url.lower()
            context.close()
            if "login" in url or "auth" in url:
                return False, "Session expired — log in to Patreon again."
            return True, "Patreon session is valid."
    except Exception as exc:
        return False, f"Session check failed: {exc}"


def open_login_browser(log: Optional[Callable[[str], None]] = None):
    """Launch a visible browser for manual Patreon login."""
    _log = log or (lambda _m: None)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright not installed."

    collector = patch_collector_module()
    collector.ensure_dirs()
    _log("Opening browser — log into Patreon with email + password (not Google).")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.patreon.com/login", wait_until="domcontentloaded", timeout=60000)

            deadline = time.time() + 600  # 10 min
            while time.time() < deadline:
                time.sleep(2)
                url = page.url.lower()
                if "login" not in url and "auth" not in url:
                    _log("Login detected — saving session.")
                    time.sleep(2)
                    context.close()
                    return True, "Patreon login successful. Session saved."
                _log("Waiting for login…")

            context.close()
            return False, "Login timed out after 10 minutes."
    except Exception as exc:
        return False, f"Login browser failed: {exc}"


def run_scrape(log: Optional[Callable[[str], None]] = None):
    """Headless scrape of all song-request posts → song_requests.json."""
    _log = log or (lambda _m: None)

    valid, msg = check_session_valid()
    if not valid:
        return False, msg

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright not installed."

    collector = patch_collector_module()

    def _check_login_noninteractive(page):
        url = page.url.lower()
        if "login" in url or "auth" in url:
            _log("Not logged in — scrape aborted.")
            return False
        return True

    collector.check_login = _check_login_noninteractive
    collector.ensure_dirs()

    try:
        with sync_playwright() as p:
            _log("Launching headless browser for scrape…")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=True,
                downloads_path=str(collector.DOWNLOADS_DIR),
                accept_downloads=True,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.add_init_script(
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            )
            collector.scrape_song_requests(page)
            context.close()

        out = Path(collector.DATA_DIR) / "song_requests.json"
        if not out.is_file():
            return False, "Scrape finished but song_requests.json was not created."
        _log(f"Scrape complete → {out.name}")
        return True, "Scrape completed successfully."
    except Exception as exc:
        return False, f"Scrape failed: {exc}"
