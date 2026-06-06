#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/browser_session /data/downloads_temp /data/admin

# Seed baked-in tracker data onto the persistent volume on first boot.
if [[ ! -f /data/tracker_allmonths_engine.json ]]; then
  echo "Seeding /data from image defaults…"
  cp -a /app/data/. /data/
fi

exec python -m uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
