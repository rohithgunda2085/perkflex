"""A traveller's email notification settings, and the link in the confirmation email."""

import hashlib
import re
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from ..config import Settings
from ..db import request_connection
from ..deps import settings_dep, traveller_session
from ..email.outbox import queue
from ..email.templates import EMAIL_SHAPE
from ..security.session import Session
from ..security.throttle import SlidingWindowLimiter

router = APIRouter(prefix="/api")

# Changing the address sends a confirmation email, so it is limited: 5 changes an hour per account.
change_limiter = SlidingWindowLimiter(limit=5, window_seconds=60 * 60)


class EmailBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str | None = None  # empty or null removes the address
    enabled: bool = False


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _view(row: dict | None, settings: Settings) -> dict:
    row = row or {}
    return {
        "email": row.get("email") or "",
        "verified": bool(row.get("email_verified_flag")),
        "enabled": bool(row.get("email_opt_in_flag")),
        "available": bool(settings.email_enabled and settings.email_from),  # false: the deployment has no SES set up
    }


def _row(conn, passenger_id: str) -> dict | None:
    return conn.execute(
        "SELECT email, email_verified_flag, email_opt_in_flag FROM dim_user_account WHERE passenger_id = %s", (passenger_id,)
    ).fetchone()


@router.get("/me/email")
def get_email(session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    with request_connection() as conn:
        return _view(_row(conn, session.passenger_id), settings)  # type: ignore[arg-type]


@router.post("/me/email")
def set_email(body: EmailBody, session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    address = (body.email or "").strip().lower()
    if address and (len(address) > 254 or not re.match(EMAIL_SHAPE, address)):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    pid: str = session.passenger_id  # type: ignore[assignment]
    with request_connection() as conn:
        current = _row(conn, pid) or {}
        if not address:
            conn.execute(
                "UPDATE dim_user_account SET email = NULL, email_verified_flag = false, email_opt_in_flag = false, email_token_hash = NULL WHERE passenger_id = %s",
                (pid,),
            )
        elif address != (current.get("email") or ""):
            if not change_limiter.hit(pid):
                raise HTTPException(status_code=429, detail="Too many changes. Try again later.")
            token = secrets.token_urlsafe(32)
            conn.execute(
                "UPDATE dim_user_account SET email = %s, email_verified_flag = false, email_opt_in_flag = %s, email_token_hash = %s WHERE passenger_id = %s",
                (address, body.enabled, _hash(token), pid),
            )
            if settings.email_enabled and settings.email_from:
                link = f"{settings.public_base_url.rstrip('/')}/api/email/confirm?token={quote(token)}"
                queue(conn, pid, "CONFIRM", address, link=link)
        else:
            conn.execute("UPDATE dim_user_account SET email_opt_in_flag = %s WHERE passenger_id = %s", (body.enabled, pid))
        return _view(_row(conn, pid), settings)


@router.get("/email/confirm", response_class=HTMLResponse)
def confirm(token: str = "") -> HTMLResponse:
    """The link in the confirmation email. The token is secret and used once."""
    if not (20 <= len(token) <= 100):
        return HTMLResponse(_page("This link is not valid."), status_code=400)
    with request_connection() as conn:
        row = conn.execute(
            "UPDATE dim_user_account SET email_verified_flag = true, email_token_hash = NULL WHERE email_token_hash = %s RETURNING user_id",
            (_hash(token),),
        ).fetchone()
    if row is None:
        return HTMLResponse(_page("This link has already been used or has expired."), status_code=400)
    return HTMLResponse(_page("Your email is confirmed. You can close this tab and return to PerkFlex."))


def _page(message: str) -> str:
    return (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>PerkFlex</title><body style='font-family:Arial,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem'><h1>PerkFlex</h1><p>{message}</p></body>"
    )
