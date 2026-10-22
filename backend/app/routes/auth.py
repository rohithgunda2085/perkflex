from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..db import atomic, request_connection
from ..deps import clear_session_cookie, current_session, set_session_cookie, settings_dep, traveller_session
from ..security.session import Session, session_to_public
from ..security.throttle import SlidingWindowLimiter
from ..services.auth import authenticate, user_by_login
from ..services.context import clock_now
from ..services.controls import set_sale
from ..services.state import build_state, current_booking_row

router = APIRouter(prefix="/api")

# 10 failed sign-ins per 15 minutes for the same address and username.
failed_logins = SlidingWindowLimiter(limit=10, window_seconds=15 * 60)

# A reset rewrites every demo traveller's trip, so it is limited to 3 a minute per account.
reset_limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
simulate_limiter = SlidingWindowLimiter(limit=20, window_seconds=60)

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


@router.post("/demo/reset")
def reset_demo(session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    """Demo only: puts every demo traveller's trips, points and rewards back to the saved starting point.

    Accounts, passwords and the signed-in session are untouched. Returns the signed-in traveller's new state.
    """
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found.")
    if not reset_limiter.hit(session.user_id):
        raise HTTPException(status_code=429, detail="Too many resets. Try again in a minute.")
    with request_connection() as conn:
        try:
            with atomic(conn):
                conn.execute("SELECT pf_demo_restore()")
        except Exception as error:  # e.g. no snapshot yet: say what to do instead of a generic failure
            message = getattr(getattr(error, "diag", None), "message_primary", None) or "The demo could not be reset."
            raise HTTPException(status_code=409, detail=message) from error
        return build_state(
            conn, session.passenger_id, settings, "Demo reset. Everything is back to its starting point."  # type: ignore[arg-type]
        )


SIMULATED = {
    "seat": "Another traveller was given seat {seat}, the one you released.",
    "bag": "Another traveller on your flight added a checked bag.",
    "none": "Nothing more to simulate right now.",
}


@router.post("/demo/simulate")
def simulate_others(session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    """Demo only: one other traveller on the viewer's flight acts, so released benefits can be seen being reused."""
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found.")
    if not simulate_limiter.hit(session.user_id):
        raise HTTPException(status_code=429, detail="Too many simulated events. Try again in a minute.")
    with request_connection() as conn:
        with atomic(conn):
            result = conn.execute(
                "SELECT pf_demo_simulate_other(%s, %s) AS r", (session.passenger_id, clock_now(settings))
            ).fetchone()["r"]
        notice = SIMULATED.get(result.get("event", "none"), SIMULATED["none"]).format(seat=result.get("seat", ""))
        return build_state(conn, session.passenger_id, settings, notice)  # type: ignore[arg-type]


class DemoSaleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benefit: str = Field(pattern=r"^(bag|preferred|extra|boarding|drink|standby|overweight)$")


@router.post("/demo/sale")
def demo_sale(body: DemoSaleBody, session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    """Demo only: the airline puts one benefit on a 25% points sale on the viewer's flight, so a sale price can be seen working."""
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found.")
    if not simulate_limiter.hit(session.user_id):
        raise HTTPException(status_code=429, detail="Too many simulated events. Try again in a minute.")
    with request_connection() as conn:
        row = current_booking_row(conn, session.passenger_id)  # type: ignore[arg-type]
        if row is None:
            raise HTTPException(status_code=409, detail="Book a flight first.")
        set_sale(conn, "demo", row["flight_id"], body.benefit, 25)
        return build_state(conn, session.passenger_id, settings, "The airline put this on sale: 25% off in points.")  # type: ignore[arg-type]
