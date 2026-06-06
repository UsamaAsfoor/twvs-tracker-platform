"""Patreon browser session management and comment scraping."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from app.config import PATREON_EMAIL, PATREON_PASSWORD, SESSION_DIR, ensure_dirs
from app.pipeline.paths import patch_collector_module

_CHROMIUM_ARGS = ["--disable-blink-features=AutomationControlled"]
_VIEWPORT = {"width": 1280, "height": 900}


def _logged_in(page) -> bool:
    url = page.url.lower()
    return "login" not in url and "auth" not in url


def _fill_first(page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            field = page.locator(selector).first
            if field.count() and field.is_visible(timeout=2000):
                field.fill(value)
                return True
        except Exception:
            continue
    return False


def _click_first(page, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.count() and button.is_visible(timeout=2000):
                button.click()
                return True
        except Exception:
            continue
    return False


def _launch_context(playwright, *, headless: bool):
    collector = patch_collector_module()
    collector.ensure_dirs()
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=headless,
        viewport=_VIEWPORT,
        args=_CHROMIUM_ARGS,
    )


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
            context = _launch_context(p, headless=True)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.patreon.com/home", wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)
            logged_in = _logged_in(page)
            context.close()
            if not logged_in:
                return False, "Session expired — log in to Patreon again."
            return True, "Patreon session is valid."
    except Exception as exc:
        return False, f"Session check failed: {exc}"


def login_with_credentials(
    email: str,
    password: str,
    log: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    """Headless Patreon login using email + password (for servers without a display)."""
    _log = log or (lambda _m: None)

    if not email or not password:
        return False, "Patreon email and password are required."

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright not installed."

    ensure_dirs()
    _log("Starting headless Patreon login…")

    email_selectors = [
        'input[type="email"]',
        'input[name="email"]',
        'input[autocomplete="email"]',
        "#email",
    ]
    password_selectors = [
        'input[type="password"]',
        'input[name="password"]',
        'input[autocomplete="current-password"]',
        "#password",
    ]
    submit_selectors = [
        'button[type="submit"]',
        'button:has-text("Log in")',
        'button:has-text("Continue")',
        'button:has-text("Sign in")',
    ]

    try:
        with sync_playwright() as p:
            context = _launch_context(p, headless=True)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.patreon.com/login", wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)

            if _logged_in(page):
                context.close()
                return True, "Already logged in. Session saved."

            _log("Entering Patreon email…")
            if not _fill_first(page, email_selectors, email):
                context.close()
                return False, "Could not find Patreon email field."
            _click_first(page, submit_selectors)
            time.sleep(2)

            _log("Entering Patreon password…")
            deadline = time.time() + 30
            password_ready = False
            while time.time() < deadline:
                if _fill_first(page, password_selectors, password):
                    password_ready = True
                    break
                time.sleep(1)

            if not password_ready:
                context.close()
                return False, "Could not find Patreon password field."

            _click_first(page, submit_selectors)
            _log("Submitting login…")

            deadline = time.time() + 60
            while time.time() < deadline:
                time.sleep(2)
                if _logged_in(page):
                    _log("Login successful — saving session.")
                    time.sleep(2)
                    context.close()
                    return True, "Patreon login successful. Session saved."

            context.close()
            return False, "Login timed out — check credentials or complete any verification step."
    except Exception as exc:
        return False, f"Headless login failed: {exc}"


def login_headless(log: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
    """Login using PATREON_EMAIL / PATREON_PASSWORD env vars."""
    return login_with_credentials(PATREON_EMAIL, PATREON_PASSWORD, log=log)


def credentials_configured() -> bool:
    return bool(PATREON_EMAIL and PATREON_PASSWORD)


def bootstrap_session_from_oauth(
    access_token: str,
    log: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    """Seed the persistent Chromium profile using a Patreon OAuth access token."""
    _log = log or (lambda _m: None)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright not installed."

    ensure_dirs()
    _log("Bootstrapping browser session from Patreon OAuth token…")

    try:
        with sync_playwright() as p:
            context = _launch_context(p, headless=True)
            page = context.pages[0] if context.pages else context.new_page()

            def _attach_auth(route) -> None:
                headers = {
                    **route.request.headers,
                    "authorization": f"Bearer {access_token}",
                }
                route.continue_(headers=headers)

            page.route("**/*patreon.com/**", _attach_auth)
            page.goto("https://www.patreon.com/home", wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

            if _logged_in(page):
                _log("Browser session bootstrapped from OAuth.")
                context.close()
                return True, "Patreon browser session saved via OAuth."

            context.close()
            return False, "OAuth connected but browser session could not be established for scraping."
    except Exception as exc:
        return False, f"OAuth browser bootstrap failed: {exc}"


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
            context = _launch_context(p, headless=False)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.patreon.com/login", wait_until="domcontentloaded", timeout=60000)

            deadline = time.time() + 600  # 10 min
            while time.time() < deadline:
                time.sleep(2)
                if _logged_in(page):
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
                viewport=_VIEWPORT,
                args=_CHROMIUM_ARGS,
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
