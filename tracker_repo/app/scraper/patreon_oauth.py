"""Patreon OAuth2 — authorize, token exchange, refresh, and token storage."""
from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from app.config import (
    ADMIN_STATE_DIR,
    PATREON_CLIENT_ID,
    PATREON_CLIENT_SECRET,
    PATREON_REDIRECT_URI,
    ensure_dirs,
)

OAUTH_AUTHORIZE_URL = "https://www.patreon.com/oauth2/authorize"
OAUTH_TOKEN_URL = "https://www.patreon.com/api/oauth2/token"
IDENTITY_URL = (
    "https://www.patreon.com/api/oauth2/v2/identity"
    "?fields%5Buser%5D=full_name,email,image_url"
    "&include=campaign"
    "&fields%5Bcampaign%5D=creation_name,url"
)

OAUTH_SCOPES = "identity identity[email] campaigns campaigns.posts"
TOKEN_PATH = ADMIN_STATE_DIR / "patreon_oauth.json"
STATE_DIR = ADMIN_STATE_DIR / "oauth_states"
STATE_TTL_SECONDS = 600


def oauth_configured() -> bool:
    return bool(PATREON_CLIENT_ID and PATREON_CLIENT_SECRET and PATREON_REDIRECT_URI)


def redirect_uri() -> str:
    return PATREON_REDIRECT_URI


def _http_form_post(url: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Patreon API error {exc.code}: {detail}") from exc


def _http_get_json(url: str, access_token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Patreon API error {exc.code}: {detail}") from exc


def _save_tokens(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    TOKEN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_tokens() -> Optional[dict[str, Any]]:
    if not TOKEN_PATH.is_file():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def clear_tokens() -> None:
    if TOKEN_PATH.is_file():
        TOKEN_PATH.unlink()


def oauth_connected() -> bool:
    tokens = load_tokens()
    return bool(tokens and tokens.get("access_token"))


def _token_expired(tokens: dict[str, Any], *, skew_seconds: int = 120) -> bool:
    expires_at = tokens.get("expires_at")
    if not expires_at:
        return True
    return time.time() >= float(expires_at) - skew_seconds


def _merge_identity(tokens: dict[str, Any], access_token: str) -> dict[str, Any]:
    identity = _http_get_json(IDENTITY_URL, access_token)
    user = identity.get("data", {})
    attrs = user.get("attributes", {})
    campaign = None
    for item in identity.get("included", []):
        if item.get("type") == "campaign":
            campaign = item
            break
    if not campaign:
        rel = user.get("relationships", {}).get("campaign", {}).get("data")
        if rel:
            campaign = {"id": rel.get("id"), "attributes": {}}

    tokens["user_id"] = user.get("id")
    tokens["user_name"] = attrs.get("full_name") or attrs.get("email") or "Patreon user"
    tokens["user_email"] = attrs.get("email")
    if campaign:
        tokens["campaign_id"] = campaign.get("id")
        tokens["campaign_name"] = (campaign.get("attributes") or {}).get("creation_name")
    return tokens


def _store_token_response(token_response: dict[str, Any], *, existing: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    now = time.time()
    expires_in = int(token_response.get("expires_in") or 0)
    payload = {
        **(existing or {}),
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token") or (existing or {}).get("refresh_token"),
        "token_type": token_response.get("token_type", "Bearer"),
        "scope": token_response.get("scope") or (existing or {}).get("scope"),
        "expires_at": now + expires_in if expires_in else now + 3600,
        "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
    }
    payload = _merge_identity(payload, payload["access_token"])
    return _save_tokens(payload)


def create_oauth_state() -> str:
    ensure_dirs()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = secrets.token_urlsafe(32)
    path = STATE_DIR / f"{state}.json"
    path.write_text(json.dumps({"created_at": time.time()}), encoding="utf-8")
    return state


def consume_oauth_state(state: str) -> bool:
    if not state:
        return False
    path = STATE_DIR / f"{state}.json"
    if not path.is_file():
        return False
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        path.unlink(missing_ok=True)
        return False
    path.unlink(missing_ok=True)
    created_at = float(meta.get("created_at") or 0)
    return (time.time() - created_at) <= STATE_TTL_SECONDS


def build_authorize_url(state: str) -> str:
    if not oauth_configured():
        raise RuntimeError("Patreon OAuth is not configured on the server.")
    params = {
        "response_type": "code",
        "client_id": PATREON_CLIENT_ID,
        "redirect_uri": PATREON_REDIRECT_URI,
        "scope": OAUTH_SCOPES,
        "state": state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    if not oauth_configured():
        raise RuntimeError("Patreon OAuth is not configured on the server.")
    token_response = _http_form_post(
        OAUTH_TOKEN_URL,
        {
            "code": code,
            "grant_type": "authorization_code",
            "client_id": PATREON_CLIENT_ID,
            "client_secret": PATREON_CLIENT_SECRET,
            "redirect_uri": PATREON_REDIRECT_URI,
        },
    )
    return _store_token_response(token_response)


def refresh_access_token(log: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
    _log = log or (lambda _m: None)
    tokens = load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        return False, "No Patreon OAuth refresh token saved."

    if not oauth_configured():
        return False, "Patreon OAuth client credentials are not configured."

    try:
        token_response = _http_form_post(
            OAUTH_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": PATREON_CLIENT_ID,
                "client_secret": PATREON_CLIENT_SECRET,
            },
        )
        _store_token_response(token_response, existing=tokens)
        _log("Patreon OAuth token refreshed.")
        return True, "Patreon OAuth token refreshed."
    except Exception as exc:
        return False, f"Patreon token refresh failed: {exc}"


def get_valid_access_token(log: Optional[Callable[[str], None]] = None) -> tuple[Optional[str], str]:
    tokens = load_tokens()
    if not tokens or not tokens.get("access_token"):
        return None, "Patreon is not connected via OAuth."

    if _token_expired(tokens):
        ok, msg = refresh_access_token(log=log)
        if not ok:
            return None, msg
        tokens = load_tokens()

    if not tokens or not tokens.get("access_token"):
        return None, "Patreon OAuth token unavailable."
    return tokens["access_token"], "Patreon OAuth token is valid."


def oauth_status() -> dict[str, Any]:
    tokens = load_tokens()
    if not tokens:
        return {
            "connected": False,
            "message": "Patreon OAuth not connected.",
        }

    access_token, msg = get_valid_access_token()
    return {
        "connected": bool(access_token),
        "message": msg,
        "user_name": tokens.get("user_name"),
        "user_email": tokens.get("user_email"),
        "campaign_id": tokens.get("campaign_id"),
        "campaign_name": tokens.get("campaign_name"),
        "connected_at": tokens.get("connected_at"),
        "expires_at": tokens.get("expires_at"),
    }
