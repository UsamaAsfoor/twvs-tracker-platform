#!/usr/bin/env python3
"""Seed Patreon browser session on a headless server (e.g. Fly.io).

Requires PATREON_EMAIL and PATREON_PASSWORD in the environment.

Usage:
  fly ssh console -a twvs-tracker -C "python /app/scripts/seed_patreon_session.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scraper.patreon import check_session_valid, login_headless


def main() -> int:
    ok, msg = login_headless(log=print)
    print(msg)
    if not ok:
        return 1

    valid, check_msg = check_session_valid()
    print(check_msg)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
