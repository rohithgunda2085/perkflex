"""Check-in perk advisor: POST /api/assistant/perk-advice. Advice only: it never changes anything."""

from fastapi import APIRouter, Depends, HTTPException

from ..advisor.advisor import advise, nudge
from ..advisor.offers import build_context
from ..advisor.types import AdviceRequest
from ..db import request_connection
from ..deps import settings_dep, traveller_session
from ..config import Settings
from ..security.session import Session
from ..security.throttle import SlidingWindowLimiter
from ..services.state import build_state

router = APIRouter(prefix="/api")

# Each call can cost model spend, so 12 per minute per traveller (the same as the fare assistant).
advisor_limiter = SlidingWindowLimiter(limit=12, window_seconds=60)


@router.post("/assistant/perk-advice")
def perk_advice(body: AdviceRequest, session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    if not advisor_limiter.hit(session.user_id):
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")
    # Read the traveller's state, then release the connection before the (slow) model call.
    with request_connection() as conn:
        try:
            state = build_state(conn, session.passenger_id, settings)  # type: ignore[arg-type]
        except LookupError:
            raise HTTPException(status_code=404, detail="Unknown traveller.")
    return advise(build_context(state), body).model_dump(by_alias=True)


@router.get("/assistant/perk-nudge")
def perk_nudge(session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    """A rules-only hint for the check-in page. No model call, so no spend and no per-minute model limit."""
    with request_connection() as conn:
        try:
            state = build_state(conn, session.passenger_id, settings)  # type: ignore[arg-type]
        except LookupError:
            raise HTTPException(status_code=404, detail="Unknown traveller.")
    n = nudge(build_context(state))
    return {"nudge": n.model_dump(by_alias=True) if n else None}
