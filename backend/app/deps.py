from fastapi import Depends, HTTPException, Request, Response

from .config import Settings, get_settings
from .security.session import COOKIE_NAME, Session, create_token, read_token


def settings_dep() -> Settings:
    return get_settings()


def current_session(request: Request) -> Session:
    session = read_token(request.cookies.get(COOKIE_NAME))
    if session is None:
        raise HTTPException(status_code=401, detail="Please sign in again.")
    return session


def traveller_session(session: Session = Depends(current_session)) -> Session:
    """A signed-in traveller (the airline admin account has no trip to show)."""
    if not session.passenger_id:
        raise HTTPException(status_code=403, detail="This account does not have a traveller view.")
    return session


def set_session_cookie(response: Response, session: Session, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_token(session),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=settings.is_production)
