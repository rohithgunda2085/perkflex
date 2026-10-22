"""AI fare assistant: POST /api/assistant/best-fare."""

from fastapi import APIRouter, Depends, HTTPException

from ..assistant.best_fare import best_fare
from ..assistant.tools import ToolContext
from ..assistant.types import BestFareRequest
from ..assistant.understand import MAX_MESSAGE, understand
from pydantic import BaseModel, ConfigDict, Field
from ..db import request_connection
from ..deps import traveller_session
from ..rules.data import flight_by_id
from ..rules.pricing import DEFAULT_NEEDS, sanitize_needs
from ..security.session import Session
from ..security.throttle import SlidingWindowLimiter
from ..services.context import load_inventory, load_traveller, resolve_flight
from ..services.mapping import flight_number
from ..services.seasons import award_for, nearby_better

router = APIRouter(prefix="/api")

# Each call costs model spend, so 12 per minute per traveller.
assistant_limiter = SlidingWindowLimiter(limit=12, window_seconds=60)


@router.post("/assistant/best-fare")
def find_best_fare(body: BestFareRequest, session: Session = Depends(traveller_session)):
    if flight_by_id(body.flight_id) is None:
        raise HTTPException(status_code=400, detail="Unknown flight.")
    if not assistant_limiter.hit(session.user_id):
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")
    # Read everything the assistant needs, then release the connection before the (slow) model call.
    with request_connection() as conn:
        traveller = load_traveller(conn, session.passenger_id)  # type: ignore[arg-type]
        if traveller is None:
            raise HTTPException(status_code=404, detail="Unknown traveller.")
        flight = resolve_flight(conn, flight_number(body.flight_id), body.date, body.origin, body.destination)
        if flight is None:
            raise HTTPException(status_code=400, detail="Unknown flight.")
        inventory = load_inventory(conn, flight["flight_id"])
        award = award_for(conn, flight["flight_date"])
        award["nearby"] = nearby_better(conn, flight, award["points"])
    ctx = ToolContext(
        traveller=traveller,
        flight_id=body.flight_id,
        inventory=inventory,
        base_needs=sanitize_needs(body.needs, DEFAULT_NEEDS),
    )
    out = best_fare(ctx, body).model_dump(by_alias=True)
    out["award"] = award  # from the rules, never from the model
    return out


class UnderstandBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(max_length=MAX_MESSAGE)
    needs: dict = Field(default_factory=dict)  # the form as it is now: fields the text does not mention keep these values


@router.post("/assistant/understand")
def understand_needs(body: UnderstandBody, session: Session = Depends(traveller_session)):
    """Fills in the fare form from what the traveller wrote. Prices nothing, books nothing, needs no database."""
    if not assistant_limiter.hit(session.user_id):
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")
    return understand(body.message, sanitize_needs(body.needs, DEFAULT_NEEDS))
