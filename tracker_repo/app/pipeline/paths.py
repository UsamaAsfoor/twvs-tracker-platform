"""Resolve data/script paths for pipeline subprocesses and imports."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app.config import DATA_DIR, REPO_ROOT, SCRIPTS_DIR, SESSION_DIR, DOWNLOADS_DIR


def repo_data() -> str:
    return str(DATA_DIR)


def scripts_on_path() -> None:
    scripts = str(SCRIPTS_DIR)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def patch_collector_module():
    """Point twvs_patreon_collector_v2 at repo-local directories."""
    scripts_on_path()
    import twvs_patreon_collector_v2 as collector

    collector.BASE_DIR = str(REPO_ROOT)
    collector.DATA_DIR = str(DATA_DIR)
    collector.DOWNLOADS_DIR = str(DOWNLOADS_DIR)
    collector.SESSION_DIR = str(SESSION_DIR)
    return collector


def env_for_subprocess() -> dict[str, str]:
    return {
        **os.environ,
        "TWVS_REPO_ROOT": str(REPO_ROOT),
        "TWVS_DATA_DIR": str(DATA_DIR),
        "TWVS_SCRIPTS_DIR": str(SCRIPTS_DIR),
        "TWVS_SESSION_DIR": str(SESSION_DIR),
    }
