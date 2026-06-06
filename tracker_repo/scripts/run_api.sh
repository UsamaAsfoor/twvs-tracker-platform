#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export TWVS_REPO_ROOT="${TWVS_REPO_ROOT:-$(pwd)}"
export TWVS_DATA_DIR="${TWVS_DATA_DIR:-$TWVS_REPO_ROOT/data}"
export TWVS_SCRIPTS_DIR="${TWVS_SCRIPTS_DIR:-$TWVS_REPO_ROOT/scripts}"
export TWVS_SESSION_DIR="${TWVS_SESSION_DIR:-$TWVS_REPO_ROOT/browser_session}"

exec python3 -m uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
