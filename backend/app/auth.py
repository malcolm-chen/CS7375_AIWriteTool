"""Admin login via a signed cookie; participants via a per-session link token."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request

SECRET = os.environ.get("COWRITE_SECRET", "dev-secret-change-me")
ADMIN_PASSWORD = os.environ.get("COWRITE_ADMIN_PASSWORD", "admin")
COOKIE = "cowrite_admin"
TTL_SECONDS = 12 * 3600


def _sign(value: str) -> str:
    mac = hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{mac}"


def admin_cookie_value() -> str:
    return _sign(f"admin:{int(time.time()) + TTL_SECONDS}")


def check_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())


def is_admin(request: Request) -> bool:
    raw = request.cookies.get(COOKIE)
    if not raw or "." not in raw:
        return False
    value, _ = raw.rsplit(".", 1)
    if not hmac.compare_digest(_sign(value), raw):
        return False
    try:
        return int(value.split(":", 1)[1]) > time.time()
    except (IndexError, ValueError):
        return False


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin login required.")


def new_participant_token() -> str:
    return secrets.token_urlsafe(18)


def session_role(request: Request, session: dict, token: str | None) -> str:
    """'participant' with a valid link token (even for a logged-in admin), else 'admin'; 403 otherwise."""
    if token and hmac.compare_digest(token, session["participant_token"]):
        return "participant"
    if is_admin(request):
        return "admin"
    raise HTTPException(status_code=403, detail="This link is not valid.")
