from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..db import request_connection
from ..deps import clear_session_cookie, current_session, set_session_cookie, settings_dep, traveller_session
from ..security.session import Session, session_to_public
from ..security.throttle import SlidingWindowLimiter
from ..services.auth import authenticate, user_by_login

router = APIRouter(prefix="/api")

# 10 failed sign-ins per 15 minutes for the same address and username.
failed_logins = SlidingWindowLimiter(limit=10, window_seconds=15 * 60)

BAD_CREDENTIALS = "The username or password is incorrect. Please try again."


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    login_id: str = Field(alias="loginId", min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class SwitchBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    profile_id: str = Field(alias="profileId", min_length=1, max_length=100)


def _session_for(user) -> Session:
    return Session(user_id=user.user_id, login_id=user.login_id, passenger_id=user.passenger_id, profile_id=user.profile_id)


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, settings: Settings = Depends(settings_dep)):
    key = f"{request.client.host if request.client else '?'}|{body.login_id.strip().lower()}"
    if failed_logins.blocked(key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    with request_connection() as conn:
        user = authenticate(conn, body.login_id, body.password)
    if user is None:
        failed_logins.hit(key)
        raise HTTPException(status_code=401, detail=BAD_CREDENTIALS)
    failed_logins.reset(key)
    set_session_cookie(response, _session_for(user), settings)
    return {"user": user.to_public()}


@router.get("/auth/me")
def me(session: Session = Depends(current_session)):
    return {"user": session_to_public(session)}


@router.post("/auth/logout")
def logout(response: Response, settings: Settings = Depends(settings_dep)):
    clear_session_cookie(response, settings)
    return {"ok": True}


@router.post("/demo/switch")
def switch_traveller(
    body: SwitchBody,
    response: Response,
    session: Session = Depends(traveller_session),
    settings: Settings = Depends(settings_dep),
):
    """Demo only: lets a presenter jump to another demo traveller without signing in again."""
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found.")
    with request_connection() as conn:
        user = user_by_login(conn, body.profile_id)
    if user is None or not user.passenger_id:
        raise HTTPException(status_code=404, detail="Unknown traveller.")
    set_session_cookie(response, _session_for(user), settings)
    return {"user": user.to_public()}
