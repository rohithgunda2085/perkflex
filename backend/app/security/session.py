"""Signed, HttpOnly session cookie. Stateless: the HMAC signature proves the server issued it.

The cookie format matches the Node API (`pf_session=<base64url JSON>.<base64url HMAC-SHA256>`), so a session
issued by either server is accepted by the other while both exist.
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from ..config import get_settings

COOKIE_NAME = "pf_session"


@dataclass(frozen=True)
class Session:
    user_id: str
    login_id: str
    passenger_id: str | None
    profile_id: str | None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _secret() -> bytes:
    secret = get_settings().session_secret
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET must be set to at least 32 characters.")
    return secret.encode()


def _sign(body: str) -> str:
    return _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())


def create_token(session: Session, now: float | None = None) -> str:
    settings = get_settings()
    payload = {
        "userId": session.user_id,
        "loginId": session.login_id,
        "passengerId": session.passenger_id,
        "profileId": session.profile_id,
        "exp": int((time.time() if now is None else now) + settings.session_ttl_seconds),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def read_token(token: str | None, now: float | None = None) -> Session | None:
    """Returns the session when the token is correctly signed and unexpired, otherwise None."""
    if not token or "." not in token:
        return None
    body, _, signature = token.partition(".")
    if not hmac.compare_digest(_sign(body).encode(), signature.encode()):
        return None
    try:
        data = json.loads(_unb64(body))
        if not isinstance(data.get("exp"), (int, float)) or data["exp"] <= (time.time() if now is None else now):
            return None
        return Session(
            user_id=data["userId"],
            login_id=data["loginId"],
            passenger_id=data.get("passengerId"),
            profile_id=data.get("profileId"),
        )
    except (ValueError, KeyError, TypeError):
        return None


def session_to_public(session: Session) -> dict:
    return {
        "userId": session.user_id,
        "loginId": session.login_id,
        "passengerId": session.passenger_id,
        "profileId": session.profile_id,
        "role": "PASSENGER" if session.passenger_id else "AIRLINE_ADMIN",
    }


__all__ = ["COOKIE_NAME", "Session", "create_token", "read_token", "session_to_public"]
