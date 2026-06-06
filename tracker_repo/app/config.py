"""Application configuration — paths resolve to tracker_repo by default."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("TWVS_REPO_ROOT", Path(__file__).resolve().parents[1]))


def _load_dotenv() -> None:
    """Load tracker_repo/.env into os.environ (does not override existing vars)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv()
DATA_DIR = Path(os.environ.get("TWVS_DATA_DIR", REPO_ROOT / "data"))
SCRIPTS_DIR = Path(os.environ.get("TWVS_SCRIPTS_DIR", REPO_ROOT / "scripts"))
SESSION_DIR = Path(os.environ.get("TWVS_SESSION_DIR", REPO_ROOT / "browser_session"))
DOWNLOADS_DIR = Path(os.environ.get("TWVS_DOWNLOADS_DIR", REPO_ROOT / "downloads_temp"))
TRACKER_DIR = REPO_ROOT / "tracker"
ADMIN_STATE_DIR = DATA_DIR / "admin"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))

PATREON_EMAIL = os.environ.get("PATREON_EMAIL", "").strip()
PATREON_PASSWORD = os.environ.get("PATREON_PASSWORD", "").strip()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_KEY_FILE = Path(
    os.environ.get("ANTHROPIC_KEY_FILE", REPO_ROOT / "anthropic_api_key.txt")
)

DEFAULT_SCHEDULE_HOURS = int(os.environ.get("SCRAPE_INTERVAL_HOURS", "24"))

# Ensure child processes inherit repo paths.
os.environ.setdefault("TWVS_REPO_ROOT", str(REPO_ROOT))
os.environ.setdefault("TWVS_DATA_DIR", str(DATA_DIR))
os.environ.setdefault("TWVS_SCRIPTS_DIR", str(SCRIPTS_DIR))
os.environ.setdefault("TWVS_SESSION_DIR", str(SESSION_DIR))


def ensure_dirs() -> None:
    for d in (DATA_DIR, SESSION_DIR, DOWNLOADS_DIR, ADMIN_STATE_DIR, TRACKER_DIR):
        d.mkdir(parents=True, exist_ok=True)


def anthropic_key() -> str:
    if ANTHROPIC_API_KEY:
        return ANTHROPIC_API_KEY.strip()
    if ANTHROPIC_KEY_FILE.is_file():
        return "".join(ANTHROPIC_KEY_FILE.read_text().split())
    return ""
