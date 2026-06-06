"""Admin authentication via signed JWT bearer tokens."""
from __future__ import annotations

import time
from typing import Annotated, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import ADMIN_PASSWORD, JWT_EXPIRE_HOURS, JWT_SECRET

security = HTTPBearer(auto_error=False)


def create_token() -> dict:
    now = int(time.time())
    payload = {
        "sub": "admin",
        "iat": now,
        "exp": now + JWT_EXPIRE_HOURS * 3600,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in": JWT_EXPIRE_HOURS * 3600}


def verify_password(password: str) -> bool:
    return password == ADMIN_PASSWORD


def require_admin(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid authorization")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        if payload.get("sub") != "admin":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
        return "admin"
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
