#!/usr/bin/env python3
"""
TWVS Patreon Data Collector v2.0
==================================
Collects:
1. Dashboard stats (page scrape)
2. Posts + Members CSV exports (trigger via Patreon, retrieve via Gmail IMAP)
3. Welcome + Exit survey CSVs (direct download)
4. Song request post comments with hearts (page scrape)
5. Community chat messages (page scrape, right panel)

Prerequisites:
  pip3 install playwright --break-system-packages
  python3 -m playwright install chromium

Usage: python3 twvs_patreon_collector_v2.py
"""

import os
import sys
import glob
import csv
import shutil
import time
import json
import random
import imaplib
import email
from datetime import datetime, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: Playwright not installed.")
    print("  pip3 install playwright --break-system-packages")
    print("  python3 -m playwright install chromium")
    sys.exit(1)

# === CONFIGURATION ===
BASE_DIR = os.path.expanduser("~/TWVS")
DATA_DIR = os.path.join(BASE_DIR, "data")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads_temp")
SESSION_DIR = os.path.join(BASE_DIR, "browser_session")

# Gmail IMAP for retrieving emailed CSVs
GMAIL_ADDRESS = "freerangemusic@gmail.com"


def _load_gmail_password():
    """Load the Gmail app password without editing code. Order:
    1) env var GMAIL_APP_PASSWORD, 2) the plain text file
    ~/TWVS/gmail_app_password.txt (just paste the password in there),
    3) the hardcoded fallback below."""
    # Strip ALL whitespace — Gmail app passwords are 16 chars; the spaces are
    # only visual grouping, and copy-paste often smuggles in non-breaking
    # spaces (\xa0) that break IMAP's ASCII login.
    def _clean(s):
        return "".join((s or "").split())

    v = _clean(os.environ.get("GMAIL_APP_PASSWORD"))
    if v:
        return v
    try:
        with open(os.path.join(BASE_DIR, "gmail_app_password.txt"), "r") as f:
            txt = _clean(f.read())
            if txt:
                return txt
    except OSError:
        pass
    return ""  # no fallback — set the app password in ~/TWVS/gmail_app_password.txt


GMAIL_APP_PASSWORD = _load_gmail_password()

# Patreon URLs
DASHBOARD_URL = "https://www.patreon.com/insights/membership"
POSTS_INSIGHTS_URL = "https://www.patreon.com/insights/posts"
MEMBERS_URL = "https://www.patreon.com/members"
WELCOME_SURVEYS_URL = "https://www.patreon.com/insights/surveys"
EXIT_SURVEYS_URL = "https://www.patreon.com/dashboard/exit-surveys"

# Song request posts. Months are provisional labels; the scraper now also
# captures each post's title (which states the month), so the rebuild can
# self-correct the month/type from the actual post. The full historical set is
# listed so every past month can be rebuilt from live source comments.
SONG_REQUEST_URLS = [
    # --- Current month ---
    {"month": "June 2026", "type": "General", "url": "https://www.patreon.com/posts/june-2026-159839506"},
    {"month": "June 2026", "type": "K-Pop",   "url": "https://www.patreon.com/posts/159837783"},
    # --- May 2026 ---
    {"month": "May 2026", "type": "General", "url": "https://www.patreon.com/posts/content-requests-157072299"},
    {"month": "May 2026", "type": "K-Pop",   "url": "https://www.patreon.com/posts/k-pop-korean-may-157069116"},
    # --- Historical backfill (provisional months; corrected from post_title) ---
    {"month": "April 2026",    "type": "K-Pop",   "url": "https://www.patreon.com/posts/154519835"},
    {"month": "April 2026",    "type": "General", "url": "https://www.patreon.com/posts/154516228"},
    {"month": "March 2026",    "type": "K-Pop",   "url": "https://www.patreon.com/posts/151978841"},
    {"month": "March 2026",    "type": "General", "url": "https://www.patreon.com/posts/151976141"},
    {"month": "March 2026",    "type": "General", "url": "https://www.patreon.com/posts/149669027"},
    {"month": "March 2026",    "type": "K-Pop",   "url": "https://www.patreon.com/posts/149664332"},
    {"month": "February 2026", "type": "General", "url": "https://www.patreon.com/posts/147171618"},
    {"month": "February 2026", "type": "K-Pop",   "url": "https://www.patreon.com/posts/147172552"},
    {"month": "January 2026",  "type": "General", "url": "https://www.patreon.com/posts/144798397"},
    {"month": "January 2026",  "type": "K-Pop",   "url": "https://www.patreon.com/posts/144796741"},
    {"month": "January 2026",  "type": "General-2","url": "https://www.patreon.com/posts/144795170"},
    {"month": "December 2025", "type": "General", "url": "https://www.patreon.com/posts/142578563"},
    {"month": "December 2025", "type": "K-Pop",   "url": "https://www.patreon.com/posts/142578301"},
    {"month": "October 2025",  "type": "General", "url": "https://www.patreon.com/posts/140186892"},
]

# Community chats
PATREON_CHATS = {
    "VTUBER_VIDEOGAME": {
        "url": "https://www.patreon.com/messages/43abdca9466e43c3a77b0297412a152f?mode=campaign&tab=chats",
        "label": "VTuber & Video Game Chat",
    },
    "JPOP_JROCK_ANIME": {
        "url": "https://www.patreon.com/messages/90822878ea1a4802b52459bd0f3564b1?mode=campaign&tab=chats",
        "label": "J-Pop & J-Rock & Anime",
    },
    "PPOP_SOUTHEAST_ASIA": {
        "url": "https://www.patreon.com/messages/69a76e1c6d6b448893fe0edcb7284a32?mode=campaign&tab=chats",
        "label": "P-Pop & South East Asia",
    },
    "KPOP_KOREAN": {
        "url": "https://www.patreon.com/messages/b38e08693e9744b593a12409ecfaf86b?mode=campaign&tab=chats",
        "label": "K-Pop / Korean Artists",
    },
    "MUSICAL_THEATRE": {
        "url": "https://www.patreon.com/messages/58658cc53bdf4a3cabe5a23938c592d5?mode=campaign&tab=chats",
        "label": "Musical Theatre, Soundtracks & Opera",
    },
    "METAL_ROCK": {
        "url": "https://www.patreon.com/messages/8f2f8c94c12d4de4994ebc45ce0c8d02?mode=campaign&tab=chats",
        "label": "Metal/Rock",
    },
    "EUROPE_TURKEY_ME": {
        "url": "https://www.patreon.com/messages/0a385033f7d94d1a98296158fbc3c62e?mode=campaign&tab=chats",
        "label": "Europe, Turkey & Middle East",
    },
    "LATIN_SPAIN": {
        "url": "https://www.patreon.com/messages/46154751b85f4ddc9791e265af2fe302?mode=campaign&tab=chats",
        "label": "Latin American & Spain",
    },
    "CPOP_EAST_ASIA": {
        "url": "https://www.patreon.com/messages/72093cd8a8bc4adea6dcdee4e574d473?mode=campaign&tab=chats",
        "label": "C-Pop & East Asia",
    },
    "US_UK_AU_CA": {
        "url": "https://www.patreon.com/messages/06115d34cf994105bdf6851673995f5f?mode=campaign&tab=chats",
        "label": "US, UK, AU & Canada",
    },
}

CHAT_SCROLL_SCREENS = 5
DOWNLOAD_TIMEOUT = 60


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    os.makedirs(SESSION_DIR, exist_ok=True)


def check_login(page):
    if "login" in page.url.lower() or "auth" in page.url.lower():
        print("\n  ⚠️  NOT LOGGED IN!")
        print("  Log into Patreon in the browser window.")
        print("  Use email + password (NOT Google sign-in).")
        input("  → Press Enter after logging in: ")
        return False
    return True


def wait_for_csv(download_dir, timeout=DOWNLOAD_TIMEOUT):
    start = time.time()
    existing = set(glob.glob(os.path.join(download_dir, "*.csv")))
    while time.time() - start < timeout:
        current = set(glob.glob(os.path.join(download_dir, "*.csv")))
        new_files = current - existing
        if new_files:
            time.sleep(2)
            return list(new_files)[0]
        time.sleep(1)
    return None


# ============================================================
# SECTION 1: Dashboard Stats
# ============================================================
def _parse_dashboard_number(text, label, skip_tokens=0):
    """Extract a number following a label in dashboard text.
    Patreon format: 'LABEL\\n\\n$10/mo\\n\\n1,163' or 'Paid (active)\\n\\n1,824'.
    skip_tokens: how many number-like tokens to skip (e.g. skip '$10/mo' price)."""
    import re
    idx = text.find(label)
    if idx < 0:
        return None
    after = text[idx + len(label):idx + len(label) + 120]
    # Find all number-like tokens (digits with optional commas)
    matches = re.findall(r'[\d,]+', after)
    skipped = 0
    for m in matches:
        if skipped < skip_tokens:
            skipped += 1
            continue
        val = int(m.replace(",", ""))
        if val > 0:
            return val
    return None


def scrape_dashboard(page):
    print("\n" + "=" * 50)
    print("  SECTION 1: Dashboard Stats")
    print("=" * 50)

    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    if not check_login(page):
        page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

    # --- Overall tab (default) ---
    try:
        overall_text = page.inner_text("main") or page.inner_text("body")
    except Exception:
        overall_text = page.inner_text("body")

    membership = {}

    # Parse Overall numbers — use "Paid\n\n1,875" and "Free\n\n10,922" from the chart area
    membership["total_paid"] = _parse_dashboard_number(overall_text, "\nPaid\n")
    membership["total_free"] = _parse_dashboard_number(overall_text, "\nFree\n")

    # --- Paid status tab ---
    try:
        btn = page.query_selector('button:has-text("Paid status")')
        if btn and btn.is_visible():
            btn.click()
            time.sleep(3)
            paid_text = page.inner_text("main") or page.inner_text("body")
            membership["paid_active"] = _parse_dashboard_number(paid_text, "Paid (active)")
            membership["paid_retrying"] = _parse_dashboard_number(paid_text, "Paid (retrying)")
            membership["gifted_others"] = _parse_dashboard_number(paid_text, "Gifted (others)")
            membership["gifted_you"] = _parse_dashboard_number(paid_text, "Gifted (you)")
            print(f"  Paid status: active={membership.get('paid_active')} retrying={membership.get('paid_retrying')} gifted={membership.get('gifted_others', 0)}+{membership.get('gifted_you', 0)}")
    except Exception as e:
        print(f"  ⚠️  Paid status tab: {e}")

    # --- Membership tier tab ---
    try:
        btn = page.query_selector('button:has-text("Membership tier")')
        if btn and btn.is_visible():
            btn.click()
            time.sleep(3)
            tier_text = page.inner_text("main") or page.inner_text("body")
            membership["tier_10"] = _parse_dashboard_number(tier_text, "AMBASSADOR LEVEL 2", skip_tokens=1)
            membership["tier_5"] = _parse_dashboard_number(tier_text, "AMBASSADOR LEVEL 1", skip_tokens=1)
            membership["tier_50"] = _parse_dashboard_number(tier_text, "SUPER AMBASSADOR", skip_tokens=1)
            print(f"  Tiers: $10={membership.get('tier_10')} $5={membership.get('tier_5')} Super={membership.get('tier_50')}")
    except Exception as e:
        print(f"  ⚠️  Membership tier tab: {e}")

    # Save full text dump (includes all tab views visited)
    path = os.path.join(DATA_DIR, "dashboard_stats.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"TWVS Dashboard — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("=" * 60 + "\n\n")
        f.write(overall_text)

    # Save structured membership data
    membership["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    json_path = os.path.join(DATA_DIR, "dashboard_membership.json")
    with open(json_path, "w") as f:
        json.dump(membership, f, indent=2)

    page.screenshot(path=os.path.join(DATA_DIR, "dashboard_screenshot.png"))
    print(f"  ✅ Dashboard saved: {path}")
    print(f"  ✅ Membership JSON: {json_path}")
    return path



# ============================================================
# SECTION 1b: Scrape Post Metrics from Page Table
# ============================================================
def scrape_post_metrics(page):
    """Scrape real impressions/seen/plays from the Insights page table.
    The CSV export has a ~7 day lag on metrics. The page shows current data."""
    print("\n" + "=" * 50)
    print("  SECTION 1b: Scrape Post Metrics (page table)")
    print("=" * 50)

    import re as _re
    import csv as _csv

    page.goto(POSTS_INSIGHTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    if not check_login(page):
        page.goto(POSTS_INSIGHTS_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

    # Ensure Past 30 days
    try:
        page.select_option("select", label="Past 30 days")
        time.sleep(3)
    except:
        pass

    # Expand all posts
    for i in range(20):
        try:
            btn = page.query_selector('button:has-text("Show 5 more")')
            if btn and btn.is_visible():
                btn.click()
                time.sleep(1)
            else:
                break
        except:
            break
    time.sleep(2)

    # Get page text and parse the posts section
    raw = page.evaluate("() => (document.querySelector('main') || document.body).innerText")
    start = raw.find("Latest posts")
    end = raw.find("Latest lives")
    if start < 0:
        start = raw.find("Impressions\nSeen\nPlays")
    if end < 0:
        end = len(raw)

    section = raw[start:end]
    lines = [l.strip() for l in section.split("\n") if l.strip()]

    posts = []
    idx = 0
    while idx < len(lines):
        dm = _re.match(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})', lines[idx])
        if dm:
            date = dm.group(1)
            title = lines[idx-1] if idx > 0 else "Unknown"
            nums = []
            j = idx + 1
            while j < len(lines) and len(nums) < 3:
                cleaned = lines[j].replace(",", "").replace("\u2013", "0").strip()
                if _re.match(r'^\d+$', cleaned):
                    nums.append(int(cleaned))
                    j += 1
                elif "Not available" in lines[j]:
                    nums.append(0)
                    j += 1
                else:
                    break
            posts.append({
                "Post Title": title[:200],
                "Publish Date (UTC)": date,
                "Total Impressions": nums[0] if len(nums) > 0 else 0,
                "Total Seen": nums[1] if len(nums) > 1 else 0,
                "Total Plays": nums[2] if len(nums) > 2 else 0,
                "Appeared on Patreon": 0,
                "Email and Notifications": 0,
                "Seen on Patreon": 0,
                "Email Open Rate": "0.0%",
                "Email Click Rate": "0.0%",
                "Notification Click Rate": "0.0%",
                "Played On Patreon": 0,
                "Average Play Duration Percentage": "0.0%",
                "Preview Plays": 0,
                "Likes": 0,
                "Comments": 0,
                "New Free Members": 0,
                "New Paid Members": 0,
                "New Membership Revenue": 0,
                "Purchases": 0,
                "Purchase Revenue": 0,
                "Total Revenue": 0,
                "Currency Code": "",
                "Link To Post": "",
            })
            idx = j
        else:
            idx += 1

    if posts:
        today = datetime.now().strftime("%Y%m%d")
        dest = os.path.join(DATA_DIR, "patreon_posts_scraped.csv")
        fieldnames = ["Post Title","Total Impressions","Appeared on Patreon","Email and Notifications","Total Seen","Seen on Patreon","Email Open Rate","Email Click Rate","Notification Click Rate","Total Plays","Played On Patreon","Average Play Duration Percentage","Preview Plays","Likes","Comments","New Free Members","New Paid Members","New Membership Revenue","Purchases","Purchase Revenue","Total Revenue","Currency Code","Publish Date (UTC)","Link To Post"]
        with open(dest, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(posts)
        print(f"  \u2705 Scraped {len(posts)} posts with metrics \u2192 {dest}")
    else:
        print("  \u274c Could not scrape post metrics from page")

    return len(posts)


def _norm_title(t):
    """Normalize a post title for cross-source matching (scrape vs CSV)."""
    import re as _re
    return _re.sub(r"\s+", " ", (t or "")).strip().lower()


def scrape_post_conversions(page):
    """Scrape the Insights → Conversions tab for per-post New Paid Members
    (and New Free Members). This is the freshest conversion source; the
    emailed 'all post insights' CSV lags it by days (e.g. BTOB live=103 vs
    CSV=72). Covers only the recent posts in the 30-day window — same limit
    as every other view on this page. Writes patreon_post_conversions.json
    keyed by normalized title."""
    print("\n" + "=" * 50)
    print("  SECTION 1c: Scrape Post Conversions (Conversions tab)")
    print("=" * 50)

    import re as _re
    import json as _json

    page.goto(POSTS_INSIGHTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    if not check_login(page):
        page.goto(POSTS_INSIGHTS_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

    # Click the "Conversions" tab
    clicked = False
    for sel in ['button:has-text("Conversions")', '[role=tab]:has-text("Conversions")', 'a:has-text("Conversions")']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(3)
                clicked = True
                break
        except Exception:
            pass
    if not clicked:
        print("  ⚠️  Could not find/click the Conversions tab — leaving NPM untouched")
        return 0

    # Expand the post-revenue list
    for _ in range(12):
        try:
            b = page.query_selector('button:has-text("Show 5 more"), button:has-text("Show more")')
            if b and b.is_visible():
                b.click()
                time.sleep(1)
            else:
                break
        except Exception:
            break
    time.sleep(2)

    raw = page.evaluate("() => (document.querySelector('main') || document.body).innerText")
    lines = [l.strip() for l in raw.split("\n") if l.strip()]

    def _find(label, start=0):
        for i in range(start, len(lines)):
            if lines[i] == label:
                return i
        return -1

    # Section boundaries: paid members live under "Post revenue",
    # free members under "Free member conversions".
    paid_start = _find("Post revenue")
    free_start = _find("Free member conversions")
    paid_end = free_start if free_start > paid_start else len(lines)
    paid_lines = lines[paid_start:paid_end] if paid_start >= 0 else lines
    free_lines = lines[free_start:] if free_start >= 0 else []

    date_re = _re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2}(,\s+\d{4})?$")
    npm_re = _re.compile(r"^(\d[\d,]*)\s+new paid member")
    int_re = _re.compile(r"^\d[\d,]*$")

    data = {}

    # --- New paid members (Post revenue section) ---
    cur = None
    for i, l in enumerate(paid_lines):
        if date_re.match(l):
            cur = paid_lines[i - 1] if i > 0 else None  # title is the line before the date
        m = npm_re.match(l)
        if m and cur:
            npm = int(m.group(1).replace(",", ""))
            data[_norm_title(cur)] = {"npm": npm, "free": 0, "raw_title": cur}
            cur = None

    # --- New free members (Free member conversions section) ---
    cur = None
    for i, l in enumerate(free_lines):
        if date_re.match(l):
            cur = free_lines[i - 1] if i > 0 else None
        elif int_re.match(l) and cur:
            key = _norm_title(cur)
            free = int(l.replace(",", ""))
            if key in data:
                data[key]["free"] = free
            else:
                data[key] = {"npm": 0, "free": free, "raw_title": cur}
            cur = None

    dest = os.path.join(DATA_DIR, "patreon_post_conversions.json")
    payload = {"scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "posts": data}
    with open(dest, "w", encoding="utf-8") as f:
        _json.dump(payload, f, ensure_ascii=False, indent=2)

    npm_count = sum(1 for v in data.values() if v["npm"] > 0)
    print(f"  ✅ Scraped conversions for {len(data)} posts ({npm_count} with paid members) → {dest}")
    # Surface the top few so a bad parse is obvious in the cron log
    for k, v in sorted(data.items(), key=lambda kv: kv[1]["npm"], reverse=True)[:5]:
        print(f"     {v['npm']:>4} NPM  {v['raw_title'][:55]}")
    return len(data)


def inspect_insights_page(page):
    """READ-ONLY diagnostic. Dumps the Insights posts page so we can locate
    where per-post New Paid Members / conversions render (same row as plays,
    a separate column, or behind a tab). Writes a dump file and prints it.
    Invoke with:  python3 twvs_patreon_collector_v2.py --inspect
    Changes nothing in the data pipeline."""
    print("\n" + "=" * 50)
    print("  INSPECT MODE (read-only): Insights posts page")
    print("=" * 50)

    page.goto(POSTS_INSIGHTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    if not check_login(page):
        page.goto(POSTS_INSIGHTS_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

    lines_out = []

    def emit(s=""):
        lines_out.append(s)
        print(s)

    # 1. Enumerate clickable tabs / buttons / toggles (to spot a "Conversions" tab)
    emit("\n--- TABS / BUTTONS / ROLES (look for a conversions/members tab) ---")
    try:
        controls = page.evaluate("""() => {
            const out = [];
            const sels = ['button', '[role=tab]', 'a[role=button]', 'select option'];
            for (const sel of sels) {
                for (const el of document.querySelectorAll(sel)) {
                    const t = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (t && t.length < 60) out.push(sel.split('[')[0] + ': ' + t);
                }
            }
            return [...new Set(out)];
        }""")
        for c in controls:
            emit("  " + c)
    except Exception as e:
        emit(f"  (control enumeration failed: {e})")

    # 2. Expand the recent-posts list a few times
    for i in range(6):
        try:
            btn = page.query_selector('button:has-text("Show 5 more")')
            if btn and btn.is_visible():
                btn.click()
                time.sleep(1)
            else:
                break
        except Exception:
            break
    time.sleep(2)

    # 3. Dump the posts-section innerText with line markers so column order is visible
    emit("\n--- MAIN innerText (posts section; \\u2193 markers per line) ---")
    try:
        raw = page.evaluate("() => (document.querySelector('main') || document.body).innerText")
        section = raw
        s = raw.find("Latest posts")
        if s < 0:
            s = raw.find("Impressions")
        if s >= 0:
            e = raw.find("Latest lives", s)
            section = raw[s: e if e > 0 else s + 6000]
        for ln in section.split("\n"):
            ln = ln.rstrip()
            if ln.strip():
                emit("  | " + ln)
    except Exception as e:
        emit(f"  (innerText dump failed: {e})")

    dump_path = os.path.join(DATA_DIR, "insights_inspect_dump.txt")
    try:
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines_out))
        print(f"\n  ✅ Dump written to {dump_path}")
        print("  Paste that file's contents back so selectors can be written exactly.")
    except Exception as e:
        print(f"  Could not write dump file: {e}")
    return dump_path


def inspect_post_page(page, url):
    """READ-ONLY diagnostic. Navigates to a single post (as the logged-in
    creator), tries to surface its per-post insights, and dumps any text
    mentioning members/conversions so we can locate the live NPM number.
    Invoke with:  python3 twvs_patreon_collector_v2.py --inspect-post <url>"""
    print("\n" + "=" * 50)
    print("  INSPECT POST (read-only):", url)
    print("=" * 50)

    lines_out = []

    def emit(s=""):
        lines_out.append(s)
        print(s)

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    if not check_login(page):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

    # Try to open a per-post insights view if one is offered
    for label in ["View insights", "Insights", "View stats", "Post insights"]:
        try:
            el = page.query_selector(f'button:has-text("{label}"), a:has-text("{label}")')
            if el and el.is_visible():
                emit(f"  (clicking '{label}')")
                el.click()
                time.sleep(4)
                break
        except Exception:
            pass

    emit(f"\n  URL after navigation: {page.url}")

    # Enumerate short button/link labels (find insights affordances / numbers)
    emit("\n--- BUTTONS / LINKS (short labels) ---")
    try:
        ctrls = page.evaluate("""() => {
            const out = [];
            for (const el of document.querySelectorAll('button, a[role=button], [role=tab]')) {
                const t = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                if (t && t.length < 70) out.push(t);
            }
            return [...new Set(out)];
        }""")
        for c in ctrls:
            emit("  " + c)
    except Exception as e:
        emit(f"  (enumeration failed: {e})")

    # Dump every line mentioning members / conversions / paid
    emit("\n--- LINES mentioning member/paid/convert/join/patron ---")
    try:
        raw = page.evaluate("() => (document.querySelector('main') || document.body).innerText")
        kws = ("member", "paid", "convert", "join", "patron", "free", "insight", "new ")
        prev = ""
        for ln in raw.split("\n"):
            t = ln.strip()
            if not t:
                continue
            low = t.lower()
            if any(k in low for k in kws):
                # include the following line too (often the number sits on next line)
                emit(f"  | {t}")
            prev = t
    except Exception as e:
        emit(f"  (text scan failed: {e})")

    dump_path = os.path.join(DATA_DIR, "insights_post_dump.txt")
    try:
        with open(dump_path, "w", encoding="utf-8") as f:
            # also persist the FULL main text for completeness
            full = page.evaluate("() => (document.querySelector('main') || document.body).innerText")
            f.write("\n".join(lines_out) + "\n\n===== FULL MAIN innerText =====\n" + full)
        print(f"\n  ✅ Dump written to {dump_path}")
        print("  Paste it back (especially any 'new paid members' line + its number).")
    except Exception as e:
        print(f"  Could not write dump file: {e}")
    return dump_path


def inspect_comments(page, url):
    """READ-ONLY diagnostic. Expands a reply thread on a request post and dumps
    the DOM so we can find how Patreon marks a REPLY vs a TOP-LEVEL comment —
    then the scraper can tag is_reply and exclude replies reliably, and verify
    no top-level comments are missed.
    Invoke with:  python3 twvs_patreon_collector_v2.py --inspect-comments [url]"""
    print("\n" + "=" * 50)
    print("  INSPECT COMMENTS (read-only):", url)
    print("=" * 50)
    lines = []

    def emit(s=""):
        lines.append(s)
        print(s)

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    if not check_login(page):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(3)

    # Load a few pages of top-level comments
    for _ in range(4):
        try:
            b = page.query_selector('button:has-text("Load more comments"), a:has-text("Load more comments")')
            if b and b.is_visible():
                b.click(); time.sleep(2)
            else:
                break
        except Exception:
            break

    # Page-reported comment count text (to compare against extracted count later)
    emit("\n--- lines mentioning 'comment' (the page's reported count) ---")
    try:
        body = page.evaluate("() => (document.querySelector('main')||document.body).innerText")
        for ln in body.split("\n"):
            if "omment" in ln and len(ln.strip()) < 40:
                emit("  | " + ln.strip())
    except Exception as e:
        emit(f"  (failed: {e})")

    # Reply-expander buttons present
    emit("\n--- reply-expander buttons (View/Collapse replies) ---")
    reply_btn = None
    try:
        btns = page.evaluate("""() => {
            const out=[];
            for (const el of document.querySelectorAll('button,a,span,div')) {
                const t=(el.innerText||'').trim();
                if (/\\brepl(y|ies)\\b/i.test(t) && t.length<40) out.push(t);
            }
            return [...new Set(out)];
        }""")
        for t in btns[:12]:
            emit("  | " + t)
    except Exception as e:
        emit(f"  (failed: {e})")

    # Click the first "view/show replies" expander, then dump the block's HTML
    for sel in ['button:has-text("View replies")', 'button:has-text("Show replies")',
                'button:has-text("replies")', 'a:has-text("replies")',
                'button:has-text("reply")']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.scroll_into_view_if_needed(); time.sleep(0.5)
                el.click(); time.sleep(2)
                reply_btn = sel
                emit(f"\n  (expanded replies via {sel})")
                break
        except Exception:
            continue
    if not reply_btn:
        emit("\n  ⚠️ no reply expander found/clicked")

    # Dump the outerHTML of the comment block containing that expander (parent +
    # now-revealed replies) — structure only (attrs), text trimmed, ~2500 chars.
    emit("\n--- comment block structure (tags + class/data-attrs) ---")
    try:
        html_struct = page.evaluate(r"""() => {
            // find an element whose text mentions replies, walk up to a sizable block
            let node=null;
            for (const el of document.querySelectorAll('button,a')) {
                if (/\brepl(y|ies)\b/i.test(el.innerText||'')) { node=el; break; }
            }
            if (!node) return '(no reply node)';
            let block=node;
            for (let i=0;i<6 && block.parentElement;i++){ block=block.parentElement; if(block.innerText && block.innerText.length>400) break; }
            // serialize tags+attrs, eliding text, capped
            const tags=[];
            const walk=(el,depth)=>{
                if (depth>6 || tags.length>120) return;
                const cls=el.getAttribute('class')||'';
                const data=[...el.attributes].filter(a=>a.name.startsWith('data-')).map(a=>a.name+'='+a.value).join(' ');
                tags.push('  '.repeat(depth)+'<'+el.tagName.toLowerCase()+(cls?' class=\"'+cls+'\"':'')+(data?' '+data:'')+'>');
                for (const c of el.children) walk(c,depth+1);
            };
            walk(block,0);
            return tags.join('\n');
        }""")
        emit(html_struct[:3500])
    except Exception as e:
        emit(f"  (structure dump failed: {e})")

    dump = os.path.join(DATA_DIR, "comments_inspect_dump.txt")
    try:
        with open(dump, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n  ✅ Dump written to {dump} — paste it back.")
    except Exception as e:
        print(f"  Could not write dump: {e}")
    return dump


# ============================================================
# SECTION 2: Trigger CSV Exports (arrive via email)
# ============================================================
def trigger_csv_exports(page):
    print("\n" + "=" * 50)
    print("  SECTION 2: Trigger CSV Exports (email delivery)")
    print("=" * 50)

    results = {}

    # --- Posts CSV (set to All Time first) ---
    print("\n  [Posts CSV]")
    page.goto(POSTS_INSIGHTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    if not check_login(page):
        page.goto(POSTS_INSIGHTS_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
    # Set date range to All Time using <select> element
    print("  Setting All Time...")
    try:
        select_el = page.query_selector("select")
        if select_el:
            page.select_option("select", label="All time")
            time.sleep(5)
            print("  Set to All Time")
        else:
            print("  Note: No select element found")
    except Exception as e:
        print(f"  Note: date range issue ({e})")

    # Click Export
    for sel in ['button:has-text("Export data as CSV")', 'button:has-text("Export")', 'a:has-text("Export")']:
        try:
            el = page.wait_for_selector(sel, timeout=5000)
            if el:
                el.click()
                print("  ✅ Posts export triggered → email")
                results["posts"] = True
                time.sleep(3)
                break
        except:
            continue
    if "posts" not in results:
        print("  ❌ Posts export button not found")
        page.screenshot(path=os.path.join(DATA_DIR, "debug_posts_export.png"))
        results["posts"] = False

    # --- Members CSV ---
    print("\n  [Members CSV]")
    page.goto(MEMBERS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    if not check_login(page):
        page.goto(MEMBERS_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

    for sel in ['button:has-text("CSV")', 'button:has-text("Export")', 'a:has-text("CSV")', 'a:has-text("Export")']:
        try:
            el = page.wait_for_selector(sel, timeout=5000)
            if el:
                el.click()
                print("  ✅ Members export triggered → email")
                results["members"] = True
                time.sleep(3)
                break
        except:
            continue
    if "members" not in results:
        print("  ❌ Members export button not found")
        page.screenshot(path=os.path.join(DATA_DIR, "debug_members_export.png"))
        results["members"] = False

    return results


# ============================================================
# SECTION 3: Download Surveys (direct download)
# ============================================================
def download_surveys(page):
    print("\n" + "=" * 50)
    print("  SECTION 3: Survey Downloads")
    print("=" * 50)

    results = {}

    for label, url in [("welcome_surveys", WELCOME_SURVEYS_URL), ("exit_surveys", EXIT_SURVEYS_URL)]:
        print(f"\n  [{label}]")

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        if not check_login(page):
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

        # Use expect_download to properly catch the file
        try:
            with page.expect_download(timeout=30000) as download_info:
                # Try clicking various button selectors
                clicked = False
                for sel in ['button:has-text("Download surveys")', 'a:has-text("Export welcome survey")',
                           'button:has-text("Export welcome")', 'a:has-text("Export")',
                           'button:has-text("Export")', 'button:has-text("CSV")',
                           'button:has-text("Download")', 'a:has-text("Download")']:
                    try:
                        el = page.wait_for_selector(sel, timeout=3000)
                        if el:
                            el.click()
                            clicked = True
                            print(f"    Clicked: {sel}")
                            break
                    except:
                        continue

                if not clicked:
                    raise Exception("No download button found")

            download = download_info.value
            today = datetime.now().strftime("%Y%m%d")
            dest = os.path.join(DATA_DIR, f"patreon_{label}_export_{today}.csv") if label == "posts" else os.path.join(DATA_DIR, f"patreon_{label}_{today}.csv")
            download.save_as(dest)
            time.sleep(2)

            try:
                with open(dest, "r", encoding="utf-8-sig") as f:
                    rows = sum(1 for _ in f) - 1
                print(f"  ✅ {label}: {rows} rows → {dest}")
            except:
                print(f"  ✅ {label}: {dest}")
            results[label] = dest

        except Exception as e:
            print(f"  ❌ {label}: {e}")
            page.screenshot(path=os.path.join(DATA_DIR, f"debug_{label}.png"))
            results[label] = None

    return results


# ============================================================
# SECTION 4: Song Request Comments
# ============================================================
def scrape_song_requests(page):
    print("\n" + "=" * 50)
    print("  SECTION 4: Song Request Comments")
    print("=" * 50)

    months = sorted({e["month"] for e in SONG_REQUEST_URLS})
    for m in months:
        types_in_month = [e["type"] for e in SONG_REQUEST_URLS if e["month"] == m]
        print(f"\n  [v2] Scraping {m} — {' + '.join(types_in_month)}")

    all_comments = []
    for entry in SONG_REQUEST_URLS:
        url = entry["url"]
        label = entry["type"]
        month = entry["month"]
        print(f"\n  Scraping {month} {label} request post...")

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        if not check_login(page):
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

        # Capture the post title (contains the month, e.g. "JANUARY 2026:
        # Content Requests") so month labels self-assign even when the config
        # entry's month is provisional — used when rebuilding past months.
        post_title = ""
        try:
            h1 = page.query_selector("h1")
            post_title = ((h1.inner_text() if h1 else "") or page.title() or "").strip()
        except Exception:
            pass

        # Scroll down to reach comments section
        print("  Loading comments...")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(random.uniform(2, 3))

        # Expand ALL top-level comments. We deliberately NEVER click "Load
        # replies" — reply threads stay collapsed, so every [data-tag=comment-row]
        # is a top-level comment by construction. Termination is foolproof: we
        # only stop once the "Load more comments" button is genuinely absent,
        # confirmed across 3 consecutive checks (with scroll + wait between, to
        # survive lazy/slow rendering) — never on a single slow round.
        max_rounds = 120
        round_count = 0
        total_clicks = 0
        gone_streak = 0
        while round_count < max_rounds:
            round_count += 1
            btn = page.query_selector('button:has-text("Load more comments"), a:has-text("Load more comments")')
            if not btn or not btn.is_visible():
                gone_streak += 1
                if gone_streak >= 3:
                    break  # button truly gone — all top-level comments loaded
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(random.uniform(2.0, 3.5))   # allow a late button to render
                continue
            gone_streak = 0
            try:
                btn.scroll_into_view_if_needed()
                time.sleep(random.uniform(1.0, 2.0))
                btn.click()
                total_clicks += 1
                time.sleep(random.uniform(2.0, 3.5))
            except Exception:
                time.sleep(2)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.5)

        print(f"  Comment expansion complete: {round_count} rounds, {total_clicks} clicks"
              + (" ⚠️ HIT ROUND CAP — may be incomplete" if round_count >= max_rounds else ""))

        # Extract comment data from DOM. Reply threads left collapsed above, so
        # every [data-tag="comment-row"] here is a top-level comment.
        print("  Extracting structured comments...")
        structured = page.evaluate("""() => {
            const seen = new Map();
            const VALID_TS = /^(\\d{1,2}\\s*[smhdw]|\\d{1,2}\\s*(?:second|minute|hour|day|week|month|year)s?\\s+ago|just now)$/i;

            for (const row of document.querySelectorAll('[data-tag="comment-row"]')) {
                const nameEl = row.querySelector('[data-tag="commenter-name"]');
                const bodyEl = row.querySelector('[data-tag="comment-body"]');
                const likeEl = row.querySelector('[data-tag="like-count"]');
                const name = nameEl ? nameEl.innerText.trim() : '';
                let body = bodyEl ? bodyEl.innerText.trim() : '';
                body = body.replace(/^Show more\\s+/i, '');
                const hearts = likeEl ? parseInt(likeEl.innerText.trim() || '0') : 0;
                if (!name || !body) continue;

                let timestamp = '';
                const timeEl = row.querySelector('time, [data-tag*="time"]');
                if (timeEl) timestamp = (timeEl.innerText || '').trim();
                if (!timestamp) {
                    const fullText = row.innerText || '';
                    const m = fullText.match(/(?:^|\\s|·|⸱)(\\d{1,2}\\s*[smhdw](?=\\s|$|[^a-z0-9])|\\d{1,2}\\s*(?:second|minute|hour|day|week|month|year)s?\\s+ago|just now)/);
                    timestamp = m ? m[1] : '';
                }
                if (!VALID_TS.test(timestamp)) timestamp = '';

                const key = name + '|' + body.substring(0, 80);
                const prev = seen.get(key);
                const entry = {name, text: body.substring(0, 500), hearts, timestamp};
                if (!prev) {
                    seen.set(key, entry);
                } else if (timestamp && !prev.timestamp) {
                    seen.set(key, entry);
                } else if (!prev.timestamp && entry.text.length > prev.text.length) {
                    seen.set(key, entry);
                }
            }
            return Array.from(seen.values());
        }""")

        # Also get raw text as fallback
        try:
            raw_text = page.inner_text("main") or page.inner_text("body")
        except Exception:
            raw_text = page.inner_text("body")

        # --- Foolproof count reconciliation ---
        # rendered = top-level comment-rows present (replies never expanded);
        # page_total = Patreon's displayed count (INCLUDES reply threads). The
        # gap between them is replies, correctly excluded. Warn loudly on any
        # extraction drop, or if rendered is far below page_total (pagination gap).
        import re as _re_rc
        rendered = page.evaluate("""() => document.querySelectorAll('[data-tag="comment-row"]').length""")
        _m = _re_rc.search(r"([\d,]+)\s+comments?\b", raw_text or "")
        page_total = int(_m.group(1).replace(",", "")) if _m else None
        extracted = len(structured)
        recon = {"rendered_toplevel": rendered, "extracted": extracted, "page_total": page_total}
        line = f"  Reconcile: page={page_total} total · {rendered} top-level rendered · {extracted} extracted"
        if page_total is not None:
            line += f" · ~{max(0, page_total - rendered)} replies excluded"
        print(line)
        if extracted < rendered - 3:
            print(f"  ⚠️ EXTRACTION DROP: {rendered - extracted} rendered top-level rows missing from output — investigate.")
        if page_total and rendered < page_total * 0.5:
            print(f"  ⚠️ PAGINATION GAP: only {rendered} top-level vs page total {page_total} — likely incomplete.")

        all_comments.append({
            "month": month,
            "type": label,
            "url": url,
            "post_title": post_title,
            "reconcile": recon,
            "structured": structured,
            "text": raw_text,
        })
        print(f"  ✅ {len(structured)} top-level comments + {len(raw_text)} chars raw text")

    # Save structured data
    path = os.path.join(DATA_DIR, "song_requests.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Song Requests — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("=" * 60 + "\n")
        for item in all_comments:
            f.write(f"\n{'=' * 40}\n  {item['type']} REQUESTS\n  {item['url']}\n{'=' * 40}\n\n")
            # Structured table
            f.write(f"COMMENTER | HEARTS | TIMESTAMP | REQUEST_TEXT\n")
            f.write(f"----------|--------|-----------|-------------\n")
            for c in sorted(item.get("structured", []), key=lambda x: -x["hearts"]):
                text_oneline = c["text"].replace("\n", " ")[:200]
                f.write(f"{c['name']} | {c['hearts']} | {c['timestamp']} | {text_oneline}\n")
            f.write(f"\n### Raw Text (fallback)\n\n")
            f.write(item.get("text", ""))
            f.write("\n\n")

    json_path = os.path.join(DATA_DIR, "song_requests.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_comments, f, indent=2, ensure_ascii=False)

    print(f"\n  ✅ Song requests: {path}")
    return path


# ============================================================
# SECTION 4b: Recent Patreon Post Comments
# ============================================================
def scrape_recent_post_comments(page):
    """Scrape comments from the 15 most recent Patreon posts (by publish date)."""
    print("\n" + "=" * 50)
    print("  SECTION 4b: Recent Post Comments")
    print("=" * 50)

    # Get post URLs from the most recent posts CSV (exported in Section 2)
    posts_files = sorted(glob.glob(os.path.join(DATA_DIR, "patreon_posts_export_*.csv")))
    if not posts_files:
        posts_files = sorted(glob.glob(os.path.join(DATA_DIR, "patreon_posts_*.csv")))
    if not posts_files:
        print("  ⚠️  No posts CSV found — skipping")
        return None

    with open(posts_files[-1], "r", encoding="utf-8-sig") as f:
        posts = list(csv.DictReader(f))

    # Sort by publish date descending, take 15 most recent with valid URLs
    posts.sort(key=lambda r: r.get("Publish Date (UTC)", ""), reverse=True)
    post_links = []
    for r in posts:
        url = (r.get("Link To Post") or "").strip()
        title = (r.get("Post Title") or "").strip()
        if url and title:
            post_links.append({"url": url, "title": title[:100]})
        if len(post_links) >= 15:
            break

    if not post_links:
        print("  ⚠️  No post URLs found in CSV")
        return None

    print(f"  Found {len(post_links)} recent posts from {os.path.basename(posts_files[-1])}")

    # Warm the session via creator dashboard to get Cloudflare clearance
    print("  Warming session via creator dashboard...")
    page.goto("https://www.patreon.com/c/TImWelchVocalStudio/posts", wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)

    all_post_comments = []

    for i, post in enumerate(post_links):
        title = post["title"][:60] or f"Post {i+1}"
        url = post["url"]
        print(f"\n  [{i+1}/{len(post_links)}] {title}...")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"    ❌ Navigation failed: {e}")
            continue
        time.sleep(random.uniform(3, 5))

        # Scroll to load comments
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(random.uniform(2, 3))

        # Click "Load more comments" + "Load replies" until exhausted
        for load_round in range(30):
            clicked = False
            for sel in ['button:has-text("Load more comments")', 'button:has-text("Load more")']:
                for btn in page.query_selector_all(sel):
                    try:
                        if btn.is_visible():
                            btn.scroll_into_view_if_needed()
                            time.sleep(random.uniform(1.5, 3.0))
                            btn.click()
                            time.sleep(random.uniform(2.5, 4.5))
                            clicked = True
                    except Exception:
                        continue
            for btn in page.query_selector_all('button:has-text("Load replies")'):
                try:
                    if btn.is_visible():
                        btn.scroll_into_view_if_needed()
                        time.sleep(random.uniform(1.0, 2.0))
                        btn.click()
                        time.sleep(random.uniform(1.5, 3.0))
                        clicked = True
                except Exception:
                    continue
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
            if not clicked:
                break

        # Check for Cloudflare block
        try:
            page_text = page.inner_text("body")[:200]
        except Exception:
            page_text = ""
        if "security verification" in page_text.lower():
            print(f"    ⚠️  Cloudflare block — skipping")
            continue

        # Extract structured comments from DOM
        comments = page.evaluate("""() => {
            const rows = document.querySelectorAll('[data-tag="comment-row"]');
            const seen = new Map();
            const VALID_TS = /^(\\d{1,2}\\s*[smhdw]|\\d{1,2}\\s*(?:second|minute|hour|day|week|month|year)s?\\s+ago|just now)$/i;
            for (const row of rows) {
                const nameEl = row.querySelector('[data-tag="commenter-name"]');
                const bodyEl = row.querySelector('[data-tag="comment-body"]');
                const likeEl = row.querySelector('[data-tag="like-count"]');
                const name = nameEl ? nameEl.innerText.trim() : '';
                let body = bodyEl ? bodyEl.innerText.trim() : '';
                body = body.replace(/^Show more\\s+/i, '');
                const hearts = likeEl ? parseInt(likeEl.innerText.trim() || '0') : 0;
                if (!name || !body) continue;

                let timestamp = '';
                const timeEl = row.querySelector('time, [data-tag*="time"]');
                if (timeEl) timestamp = (timeEl.innerText || '').trim();
                if (!timestamp) {
                    const fullText = row.innerText || '';
                    const m = fullText.match(/(?:^|\\s|·|⸱)(\\d{1,2}\\s*[smhdw](?=\\s|$|[^a-z0-9])|\\d{1,2}\\s*(?:second|minute|hour|day|week|month|year)s?\\s+ago|just now)/);
                    timestamp = m ? m[1] : '';
                }
                if (!VALID_TS.test(timestamp)) timestamp = '';

                const key = name + '|' + body.substring(0, 80);
                const prev = seen.get(key);
                const entry = {author: name, body: body.substring(0, 500), hearts, timestamp};
                if (!prev) {
                    seen.set(key, entry);
                } else if (timestamp && !prev.timestamp) {
                    seen.set(key, entry);
                } else if (!prev.timestamp && entry.body.length > prev.body.length) {
                    seen.set(key, entry);
                }
            }
            return Array.from(seen.values());
        }""")

        # Also get raw text as legacy fallback
        try:
            post_el = page.query_selector('[data-tag="post-card"]')
            raw_text = post_el.inner_text() if post_el else page.inner_text("main")
        except Exception:
            raw_text = ""

        all_post_comments.append({
            "title": title,
            "url": url,
            "comments": comments,
            "text": raw_text,  # legacy fallback
        })
        print(f"    {len(comments)} structured comments")

    # Save structured data
    path = os.path.join(DATA_DIR, "recent_post_comments.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Recent Post Comments — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("=" * 60 + "\n")
        for item in all_post_comments:
            comments = item.get("comments", [])
            f.write(f"\n### {item['title']}\n{item['url']}\n{len(comments)} comments\n\n")
            for c in comments:
                hearts_str = f", {c['hearts']}♥" if c['hearts'] else ""
                f.write(f"- **{c['author']}** ({c['timestamp']}{hearts_str}): {c['body'][:300]}\n")
            f.write("\n")

    json_path = os.path.join(DATA_DIR, "recent_post_comments.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_post_comments, f, indent=2, ensure_ascii=False)

    total_comments = sum(len(item.get("comments", [])) for item in all_post_comments)
    print(f"\n  ✅ {len(all_post_comments)} posts, {total_comments} comments → {path}")
    return path


# ============================================================
# SECTION 4c: Notifications (real-time community pulse)
# ============================================================
def scrape_notifications(page):
    """Scrape Patreon notifications — real-time signals for joins, cancels, engagement.
    NOTE: This is directional data, not exact counts. CSVs are the source of truth
    for member totals. Notifications show WHAT HAPPENED TODAY."""
    print("\n" + "=" * 50)
    print("  SECTION 4c: Notifications (real-time pulse)")
    print("=" * 50)

    page.goto("https://www.patreon.com/notifications", wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)

    if not check_login(page):
        page.goto("https://www.patreon.com/notifications", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

    # Scroll to load more notifications (they lazy-load)
    print("  Loading notifications...")
    last_height = 0
    for scroll in range(10):  # ~10 scrolls = several days of notifications
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    print(f"  Scrolled {scroll + 1} times")

    try:
        text = page.inner_text("main") or page.inner_text("body")
    except:
        text = page.inner_text("body")

    # Save
    path = os.path.join(DATA_DIR, "notifications.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Patreon Notifications — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("NOTE: Real-time signals only. CSVs are source of truth for exact counts.\n")
        f.write("=" * 60 + "\n\n")
        f.write(text)

    print(f"  ✅ Notifications: {len(text)} characters → {path}")
    return path


# ============================================================
# SECTION 5: Community Chats (right panel, not sidebar)
# ============================================================
def scrape_single_chat(page, chat_key, chat_config):
    label = chat_config["label"]
    url = chat_config["url"]
    print(f"\n  --- {label} ---")

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(8)  # Wait longer for chat messages to fully render

    if not check_login(page):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(8)

    # Debug screenshot
    page.screenshot(path=os.path.join(DATA_DIR, f"debug_chat_{chat_key}.png"))

    all_blocks = []

    try:
        # Find the RIGHT panel (messages area) — it's positioned to the right of sidebar
        # The sidebar is on the left (~300px wide), messages on the right
        text = page.evaluate("""
            () => {
                const allDivs = document.querySelectorAll('div');
                let candidates = [];

                for (const div of allDivs) {
                    const style = window.getComputedStyle(div);
                    const rect = div.getBoundingClientRect();
                    const isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll';
                    const text = div.innerText || '';

                    // Right panel: scrollable, has content, positioned right of sidebar
                    if (isScrollable && text.length > 100 && rect.left > 250 && rect.width > 400) {
                        candidates.push({ el: div, text: text, left: rect.left, len: text.length });
                    }
                }

                // Pick the one with the most content that's clearly in the right panel
                candidates.sort((a, b) => b.len - a.len);
                if (candidates.length > 0) return candidates[0].text;

                // Fallback: try all scrollable divs
                for (const div of allDivs) {
                    const style = window.getComputedStyle(div);
                    const isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll';
                    const text = div.innerText || '';
                    if (isScrollable && text.length > 500) return text;
                }

                return document.body.innerText;
            }
        """)

        if text and len(text) > 50:
            all_blocks.append(text)
            print(f"    Found messages ({len(text)} chars)")
        else:
            text = page.inner_text("body")
            all_blocks.append(text)
            print(f"    Fallback to body ({len(text)} chars)")

        # Scroll up in the right panel for older messages
        for _ in range(CHAT_SCROLL_SCREENS - 1):
            page.evaluate("""
                () => {
                    const allDivs = document.querySelectorAll('div');
                    let best = null;
                    let bestLen = 0;
                    for (const div of allDivs) {
                        const style = window.getComputedStyle(div);
                        const rect = div.getBoundingClientRect();
                        const isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll';
                        const text = div.innerText || '';
                        if (isScrollable && text.length > 100 && rect.left > 250 && rect.width > 400) {
                            if (text.length > bestLen) { best = div; bestLen = text.length; }
                        }
                    }
                    if (best) best.scrollTop = Math.max(0, best.scrollTop - best.clientHeight);
                }
            """)
            time.sleep(2)

            new_text = page.evaluate("""
                () => {
                    const allDivs = document.querySelectorAll('div');
                    let best = null;
                    let bestLen = 0;
                    for (const div of allDivs) {
                        const style = window.getComputedStyle(div);
                        const rect = div.getBoundingClientRect();
                        const isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll';
                        const text = div.innerText || '';
                        if (isScrollable && text.length > 100 && rect.left > 250 && rect.width > 400) {
                            if (text.length > bestLen) { best = div; bestLen = text.length; }
                        }
                    }
                    return best ? best.innerText : '';
                }
            """)

            if new_text and len(new_text) > 50 and new_text != all_blocks[-1]:
                all_blocks.append(new_text)
            else:
                break

    except Exception as e:
        print(f"    ERROR: {e}")
        try:
            all_blocks.append(page.inner_text("body"))
        except:
            all_blocks.append(f"ERROR: {label}")

    # Combine, deduplicate, and parse into structured messages
    combined = "\n\n".join(reversed(all_blocks))
    lines = combined.split("\n")

    # Parse the raw text into structured messages
    # Pattern: Author\n[\n]CREATOR\n[\n]⸱ Nd ago\n[\n]body lines
    # NOTE: Patreon inserts blank lines (\n\n) between every element.
    # Strip blank lines first to simplify parsing.
    import re as _re
    JUNK_LINES = {
        "Shift + Return to add new line", "Show more", "CREATOR",
        "Where Creator Communities Thrive — Patreon", "--- SCROLL ---",
    }
    TS_PATTERN = _re.compile(r'^\s*[⸱·]?\s*(\d+[smhdw]\s*ago|just now)\s*$', _re.IGNORECASE)

    # Remove blank lines — Patreon double-spaces everything
    non_blank = [l for l in lines if l.strip()]

    messages = []
    seen_keys = set()
    i = 0
    while i < len(non_blank):
        line = non_blank[i].strip()
        if line in JUNK_LINES or line.startswith("---"):
            i += 1
            continue

        # Look ahead: skip optional CREATOR badge, then check for timestamp
        peek = i + 1
        is_creator = False
        if peek < len(non_blank) and non_blank[peek].strip() == "CREATOR":
            is_creator = True
            peek += 1

        if peek < len(non_blank) and TS_PATTERN.match(non_blank[peek].strip()):
            author = line
            ts_match = TS_PATTERN.match(non_blank[peek].strip())
            ts = ts_match.group(1) if ts_match else ""
            body_start = peek + 1

            # Collect body lines until next author+timestamp pair
            body_lines = []
            j = body_start
            while j < len(non_blank):
                bl = non_blank[j].strip()
                if bl in JUNK_LINES:
                    j += 1
                    continue
                # Check if this starts a new message (line followed by optional CREATOR then timestamp)
                next_peek = j + 1
                if next_peek < len(non_blank) and non_blank[next_peek].strip() == "CREATOR":
                    next_peek += 1
                if next_peek < len(non_blank) and TS_PATTERN.match(non_blank[next_peek].strip()):
                    break
                body_lines.append(bl)
                j += 1

            body = " ".join(body_lines).strip()
            if body and not _re.match(r'^[\U0001F300-\U0001FAFF\U00002702-\U000027B0\s\d]+$', body):
                key = f"{author}|{body[:40]}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    messages.append({
                        "author": author,
                        "is_creator": is_creator,
                        "timestamp": ts,
                        "body": body[:500],
                    })
            i = j
        else:
            i += 1

    print(f"    [chat scraper] {len(messages)} messages from '{label}'")
    return messages


def scrape_all_chats(page):
    print("\n" + "=" * 50)
    print("  SECTION 5: Community Chats")
    print("=" * 50)

    chat_data = {}
    for key, config in PATREON_CHATS.items():
        messages = scrape_single_chat(page, key, config)
        chat_data[key] = {
            "label": config["label"],
            "messages": messages if isinstance(messages, list) else [],
            "scraped_at": datetime.now().isoformat(),
        }

    # Save structured text
    path = os.path.join(DATA_DIR, "patreon_chats.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Patreon Chats — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("=" * 60 + "\n")
        for key, data in chat_data.items():
            msgs = data.get("messages", [])
            f.write(f"\n### {data['label']}\n{len(msgs)} messages\n\n")
            for m in msgs:
                creator_tag = " (CREATOR)" if m.get("is_creator") else ""
                f.write(f"- **{m['author']}**{creator_tag} ({m['timestamp']}): {m['body'][:300]}\n")

    # Save JSON
    json_path = os.path.join(DATA_DIR, "patreon_chats.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(chat_data, f, indent=2, ensure_ascii=False)

    total = sum(len(d.get("messages", [])) for d in chat_data.values())
    print(f"\n  ✅ Chats: {total} messages across {len(chat_data)} threads → {path}")
    return path


# ============================================================
# SECTION 6: Gmail IMAP — Retrieve emailed CSVs
# ============================================================
def get_csv_urls_from_gmail():
    """Get download URLs from Gmail. Returns dict of label → URL."""
    print("\n" + "=" * 50)
    print("  SECTION 6: Gmail — Get CSV Download URLs")
    print("=" * 50)

    print(f"  Connecting to {GMAIL_ADDRESS}...")
    urls = {}

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("INBOX")
        print("  ✅ Connected to Gmail")

        import re

        date_str = (datetime.now() - timedelta(hours=4)).strftime("%d-%b-%Y")
        print(f"  Searching for Patreon export emails since {date_str}...")
        status, messages = mail.search(None, 'FROM', '"patreon"', 'SINCE', date_str)

        if status != "OK" or not messages[0]:
            print("  ⚠️  No Patreon emails found")
            mail.logout()
            return urls

        msg_ids = messages[0].split()
        print(f"  Found {len(msg_ids)} Patreon emails")

        for msg_id in reversed(msg_ids):
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "")

            subject_lower = subject.lower()
            is_posts = "post" in subject_lower and "export" in subject_lower
            is_members = "relationship" in subject_lower and "export" in subject_lower

            if not is_posts and not is_members:
                continue

            label = "posts" if is_posts else "members"

            # Skip if we already found this type
            if label in urls:
                continue

            print(f"  Found: {subject[:60]}")

            # Get email body
            body = ""
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")
                        break
                elif ctype == "text/plain" and not body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")

            if body:
                found_urls = re.findall(r'https?://[^\s"\'<>]+', body)
                for url in found_urls:
                    url_lower = url.lower()
                    if ".csv" in url_lower or ("export" in url_lower and "patreon" in url_lower) or ("download" in url_lower and "patreon" in url_lower):
                        clean_url = url.split('"')[0].split("'")[0].split(">")[0]
                        urls[label] = clean_url
                        print(f"    → {label} URL found")
                        break

        mail.logout()
        print("  Gmail closed")

    except Exception as e:
        print(f"  ❌ Gmail error: {e}")

    return urls


def download_csvs_via_browser(page, csv_urls):
    """Use the authenticated Playwright browser to download CSVs from Patreon URLs."""
    print("\n" + "=" * 50)
    print("  SECTION 7: Download CSVs via Browser")
    print("=" * 50)

    results = {}

    for label, url in csv_urls.items():
        print(f"\n  Downloading {label} CSV...")
        print(f"    URL: {url[:80]}...")

        try:
            # Use Playwright's download handler — catches file downloads properly
            with page.expect_download(timeout=60000) as download_info:
                page.evaluate(f"window.location.href = '{url}'")

            download = download_info.value
            today = datetime.now().strftime("%Y%m%d")
            dest = os.path.join(DATA_DIR, f"patreon_{label}_export_{today}.csv") if label == "posts" else os.path.join(DATA_DIR, f"patreon_{label}_{today}.csv")

            # Save to final location
            download.save_as(dest)

            # Wait for save to complete
            time.sleep(2)

            try:
                with open(dest, "r", encoding="utf-8-sig") as f:
                    rows = sum(1 for _ in f) - 1
                print(f"    ✅ {label}: {rows} rows → {dest}")
            except:
                size = os.path.getsize(dest)
                print(f"    ✅ {label}: {size:,} bytes → {dest}")
            results[label] = dest

        except Exception as e:
            print(f"    ❌ {label}: {e}")
            # Save URL for manual download
            url_path = os.path.join(DATA_DIR, f"patreon_{label}_download_url.txt")
            with open(url_path, "w") as f:
                f.write(url)
            print(f"    Saved URL to: {url_path}")

    return results



# ============================================================
# SECTION 8: Merge Scraped + CSV Data
# ============================================================
def merge_post_data():
    """Combine historical CSV (old collector) with page scrape (current).
    Uses higher metrics from scrape, adds new posts not in historical."""
    print("\n" + "=" * 50)
    print("  SECTION 8: Merge Post Data")
    print("=" * 50)

    import csv as _csv
    import re as _re

    today = datetime.now().strftime("%Y%m%d")
    scraped_path = os.path.join(DATA_DIR, "patreon_posts_scraped.csv")

    # Find best historical CSV (largest recent file, not today's)
    candidates = sorted(glob.glob(os.path.join(DATA_DIR, "patreon_posts_*.csv")), key=os.path.getsize, reverse=True)
    hist_path = None
    for c in candidates:
        bn = os.path.basename(c)
        if bn == f"patreon_posts_{today}.csv" or bn == "patreon_posts_scraped.csv":
            continue
        if os.path.getsize(c) > 50000:
            hist_path = c
            break

    # Load scrape
    scraped = {}
    if os.path.exists(scraped_path):
        with open(scraped_path, "r") as f:
            for row in _csv.DictReader(f):
                t = (row.get("title", "") or row.get("Post Title", "")).strip()[:35]
                if t:
                    scraped[t] = row
        print(f"  Scraped: {len(scraped)} posts with live metrics")

    # Load historical
    hist = {}
    fieldnames = None
    if hist_path:
        with open(hist_path, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                t = row.get("Post Title", "").strip()
                if t:
                    hist[t] = row
        print(f"  Historical: {len(hist)} posts from {os.path.basename(hist_path)}")

    if not fieldnames:
        fieldnames = ["Post Title","Total Impressions","Appeared on Patreon","Email and Notifications","Total Seen","Seen on Patreon","Email Open Rate","Email Click Rate","Notification Click Rate","Total Plays","Played On Patreon","Average Play Duration Percentage","Preview Plays","Likes","Comments","New Free Members","New Paid Members","New Membership Revenue","Purchases","Purchase Revenue","Total Revenue","Currency Code","Publish Date (UTC)","Link To Post"]

    def convert_date(d):
        try:
            return datetime.strptime(d, "%b %d, %Y").strftime("%Y-%m-%d 12:00:00")
        except:
            return d

    # Merge: use higher metrics from scrape
    filled = 0
    added = 0
    for s_short, srow in scraped.items():
        matched = None
        for htitle in hist:
            if htitle[:35] == s_short[:35]:
                matched = htitle
                break

        s_imp = int(srow.get("impressions", 0) or srow.get("Total Impressions", 0) or 0)
        s_seen = int(srow.get("seen", 0) or srow.get("Total Seen", 0) or 0)
        s_plays = int(srow.get("plays", 0) or srow.get("Total Plays", 0) or 0)

        if matched:
            h = hist[matched]
            h_imp = int(h.get("Total Impressions") or 0)
            if s_imp > h_imp:
                h["Total Impressions"] = str(s_imp)
                h["Total Seen"] = str(s_seen)
                h["Total Plays"] = str(s_plays)
                filled += 1
        else:
            # The scraped CSV uses capitalized headers ("Post Title",
            # "Publish Date (UTC)", "Link To Post"). Older code read the
            # lowercase keys ("title"/"date"), which returned "" — so every
            # added post collapsed into a single empty-titled row and was
            # lost. Read the real columns (lowercase kept as fallback).
            s_title = (srow.get("Post Title") or srow.get("title") or "").strip()
            if not s_title:
                continue
            new_row = {fn: "" for fn in fieldnames}
            new_row["Post Title"] = s_title
            new_row["Total Impressions"] = str(s_imp)
            new_row["Total Seen"] = str(s_seen)
            new_row["Total Plays"] = str(s_plays)
            new_row["Publish Date (UTC)"] = convert_date(srow.get("Publish Date (UTC)") or srow.get("date", ""))
            new_row["Link To Post"] = srow.get("Link To Post") or srow.get("link", "")
            hist[s_title] = new_row
            added += 1

    print(f"  Updated: {filled} | Added: {added}")

    # --- Overlay LIVE conversions (Conversions tab) onto the full set ---
    # The emailed CSV's New Paid Members lags by days; the Conversions-tab
    # scrape is the freshest source. Apply to ALL posts (not just those in the
    # reach scrape) so recent high-velocity converters like BTOB are corrected.
    # Only ever raise NPM — never let a parse miss clobber a good value down.
    import json as _json
    conv_path = os.path.join(DATA_DIR, "patreon_post_conversions.json")
    conv = {}
    if os.path.exists(conv_path):
        try:
            with open(conv_path, "r", encoding="utf-8") as f:
                conv = (_json.load(f) or {}).get("posts", {})
        except Exception as e:
            print(f"  ⚠️  Could not read conversions JSON: {e}")

    def _normt(t):
        return _re.sub(r"\s+", " ", t or "").strip().lower()

    npm_updated = 0
    if conv:
        norm_to_hist = {_normt(t): t for t in hist}
        hist_norms = list(norm_to_hist.items())  # (normalized, original)

        def _match(ntitle):
            # Exact normalized match first.
            if ntitle in norm_to_hist:
                return norm_to_hist[ntitle]
            # Fallback: prefix containment, to survive the reach scrape's
            # 80-char title truncation. Require >=45 chars so distinct posts
            # that share a long prefix (e.g. "Kingdom Legendary Wars Episode 4
            # (part 1/2/3 of 3)") don't collide.
            for hn, htitle in hist_norms:
                if len(ntitle) >= 45 and len(hn) >= 45 and (ntitle.startswith(hn) or hn.startswith(ntitle)):
                    return htitle
            return None

        unmatched = []
        for ntitle, c in conv.items():
            live_npm = int(c.get("npm", 0) or 0)
            htitle = _match(ntitle)
            if not htitle:
                if live_npm > 0:
                    unmatched.append((live_npm, c.get("raw_title", ntitle)))
                continue
            h = hist[htitle]
            try:
                cur_npm = int(float(h.get("New Paid Members") or 0))
            except (TypeError, ValueError):
                cur_npm = 0
            if live_npm > cur_npm:
                h["New Paid Members"] = str(live_npm)
                npm_updated += 1
        print(f"  Live NPM overlaid: {npm_updated} post(s) raised from Conversions tab")
        if unmatched:
            # Visible in the cron log so a parse/title drift never silently
            # swallows a real conversion count.
            print(f"  ⚠️  {len(unmatched)} live-converting post(s) had NO title match (NPM not applied):")
            for npm, title in sorted(unmatched, reverse=True)[:10]:
                print(f"       {npm:>4} NPM  {title[:60]}")

    # --- Pull NPM up from today's fresh email export ---
    # The emailed export is a 30-DAY ROLLING window: recent posts can show a
    # higher count there than our carried-forward merged value (e.g. a post
    # the scrape undercounts), while old posts decay toward 0. Taking the MAX
    # raises undercounted recent posts WITHOUT lowering the accumulated
    # lifetime peak of old posts (their export value is small/zero).
    export_glob = sorted(glob.glob(os.path.join(DATA_DIR, "patreon_posts_export_*.csv")))
    export_raised = 0
    if export_glob:
        exp = {}
        try:
            with open(export_glob[-1], "r", encoding="utf-8-sig", newline="") as f:
                for r in _csv.DictReader(f):
                    t = (r.get("Post Title", "") or "").strip()
                    if t:
                        exp[_normt(t)] = r
        except Exception as e:
            print(f"  ⚠️  Could not read fresh export for NPM max: {e}")
        if exp:
            norm_to_hist2 = {_normt(t): t for t in hist}
            for ntitle, erow in exp.items():
                htitle = norm_to_hist2.get(ntitle)
                if not htitle:
                    continue
                try:
                    e_npm = int(float(erow.get("New Paid Members") or 0))
                except (TypeError, ValueError):
                    e_npm = 0
                h = hist[htitle]
                try:
                    cur = int(float(h.get("New Paid Members") or 0))
                except (TypeError, ValueError):
                    cur = 0
                if e_npm > cur:
                    h["New Paid Members"] = str(e_npm)
                    export_raised += 1
            print(f"  Export NPM max: {export_raised} post(s) raised from fresh 30-day export")

    rows = sorted(hist.values(), key=lambda r: r.get("Publish Date (UTC)", "") or "0", reverse=True)
    dest = os.path.join(DATA_DIR, f"patreon_posts_{today}.csv")
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    has = sum(1 for r in rows if (r.get("Total Impressions") or "").strip() not in ("", "0"))
    print(f"  Result: {len(rows)} posts, {has} with metrics")
    print(f"  Saved: {dest}")
    return dest


# ============================================================
# MAIN
# ============================================================
def run_inspect(post_url=None, comments_url=None):
    """Read-only: launch browser, dump a diagnostic, then exit. Triggers no
    exports/downloads/merges/writes to pipeline data (only a dump file)."""
    ensure_dirs()
    print("=" * 60)
    print("  INSPECT MODE — read-only dump (no pipeline changes)")
    print("=" * 60)
    with sync_playwright() as p:
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
        try:
            if comments_url:
                inspect_comments(page, comments_url)
            elif post_url:
                inspect_post_page(page, post_url)
            else:
                inspect_insights_page(page)
        finally:
            context.close()


def run_test_conversions():
    """Run ONLY the Conversions-tab scrape and print the result. No exports,
    downloads, or merges — safe way to verify the live NPM capture in isolation.
    Invoke with:  python3 twvs_patreon_collector_v2.py --test-conversions"""
    ensure_dirs()
    print("=" * 60)
    print("  TEST: Conversions scrape only (no exports/downloads/merge)")
    print("=" * 60)
    with sync_playwright() as p:
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
        try:
            scrape_post_conversions(page)
            path = os.path.join(DATA_DIR, "patreon_post_conversions.json")
            print(f"\n  Full result written to: {path}")
        finally:
            context.close()


def main():
    if "--test-conversions" in sys.argv:
        run_test_conversions()
        return
    if "--inspect-comments" in sys.argv:
        i = sys.argv.index("--inspect-comments")
        url = sys.argv[i + 1] if (i + 1 < len(sys.argv) and sys.argv[i + 1].startswith("http")) else \
            "https://www.patreon.com/posts/content-requests-157072299"
        run_inspect(comments_url=url)
        return
    if "--inspect-post" in sys.argv:
        i = sys.argv.index("--inspect-post")
        url = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if not url:
            print("Usage: --inspect-post <post_url>")
            return
        run_inspect(post_url=url)
        return
    if "--inspect" in sys.argv:
        run_inspect()
        return

    ensure_dirs()
    now = datetime.now()

    print("=" * 60)
    print(f"  TWVS Patreon Data Collector v2.0")
    print(f"  {now.strftime('%A, %B %d, %Y at %I:%M %p')}")
    print("=" * 60)
    print(f"  Data: {DATA_DIR}")
    print(f"  Gmail: {GMAIL_ADDRESS}")

    # Clean temp
    for f in glob.glob(os.path.join(DOWNLOADS_DIR, "*")):
        os.remove(f)

    results = {}

    # === ALL SECTIONS USE BROWSER — keep it open throughout ===
    with sync_playwright() as p:
        print("\n  Launching browser...")

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

        # 1. Dashboard
        try:
            results["dashboard"] = scrape_dashboard(page)
        except Exception as e:
            print(f"  ❌ Dashboard: {e}")

        # 1b. Scrape post metrics from page table (current data)
        try:
            results["post_metrics"] = scrape_post_metrics(page)
        except Exception as e:
            print(f"  Error scraping post metrics: {e}")

        # 1c. Scrape live per-post conversions (Conversions tab → fresh NPM)
        try:
            results["conversions"] = scrape_post_conversions(page)
        except Exception as e:
            print(f"  Error scraping conversions: {e}")

        # 2. Trigger CSV exports (these go to email)
        try:
            results["csv_triggers"] = trigger_csv_exports(page)
        except Exception as e:
            print(f"  ❌ CSV triggers: {e}")

        # 3. Download surveys (direct download)
        try:
            results["surveys"] = download_surveys(page)
        except Exception as e:
            print(f"  ❌ Surveys: {e}")

        # 4. Song requests
        try:
            results["song_requests"] = scrape_song_requests(page)
        except Exception as e:
            print(f"  ❌ Song requests: {e}")

        # 4b. Recent post comments
        try:
            results["post_comments"] = scrape_recent_post_comments(page)
        except Exception as e:
            print(f"  ❌ Post comments: {e}")

        # 4c. Notifications (real-time community pulse)
        try:
            results["notifications"] = scrape_notifications(page)
        except Exception as e:
            print(f"  ❌ Notifications: {e}")

        # 5. Community chats
        try:
            results["chats"] = scrape_all_chats(page)
        except Exception as e:
            print(f"  ❌ Chats: {e}")

        # 6. Get CSV URLs from Gmail (while browser is still open)
        print("\n  Waiting 30 seconds for Patreon to email CSVs...")
        time.sleep(30)

        csv_urls = {}
        try:
            csv_urls = get_csv_urls_from_gmail()
        except Exception as e:
            print(f"  ❌ Gmail: {e}")

        # 7. Download CSVs using the browser (has Patreon auth)
        if csv_urls:
            try:
                results["csv_downloads"] = download_csvs_via_browser(page, csv_urls)
            except Exception as e:
                print(f"  ❌ CSV downloads: {e}")
        else:
            print("\n  No CSV URLs found — skipping browser download")

        # 8. Merge scraped + CSV data
        try:
            results["merge"] = merge_post_data()
        except Exception as e:
            print(f"  Error merging data: {e}")

        # NOW close the browser
        context.close()

    # === CLEANUP: Keep only last 7 days of member CSVs ===
    # Most exports: keep 7 days. The post-insights export is kept 90 days —
    # it carries the 30-day-rolling NPM the Old-Post Revival Watch relies on
    # to spot older posts that start converting again (YouTube-funnel signal).
    retention = [
        ("patreon_members_*.csv", 7),
        ("patreon_welcome_surveys_*.csv", 7),
        ("patreon_exit_surveys_*.csv", 7),
        ("patreon_posts_export_*.csv", 90),
    ]
    for pattern, days in retention:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        for f in sorted(glob.glob(os.path.join(DATA_DIR, pattern))):
            base = os.path.basename(f)
            date_part = base.replace(".csv", "").split("_")[-1]
            if len(date_part) == 8 and date_part.isdigit() and date_part < cutoff:
                os.remove(f)
                print(f"  🗑️  Removed old export ({days}d retention): {base}")

    # === SUMMARY ===
    print("\n" + "=" * 60)
    print("  COLLECTION SUMMARY")
    print("=" * 60)
    for key, value in results.items():
        status = "✅" if value else "❌"
        print(f"  {status} {key}: {value or 'FAILED'}")

    print(f"\n  Files in {DATA_DIR}:")
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "*"))):
        name = os.path.basename(f)
        try:
            size = os.path.getsize(f)
            print(f"    {name} ({size:,} bytes)")
        except OSError:
            print(f"    {name} (broken symlink)")

    print("\nDone!")


if __name__ == "__main__":
    main()
