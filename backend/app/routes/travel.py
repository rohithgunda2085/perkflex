"""The traveller's state, quotes, and actions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..db import request_connection
from ..deps import settings_dep, traveller_session
from ..rules.data import FLIGHTS
from ..rules.pricing import Needs, entitlements, quote_fares, recommended_quote, sanitize_needs
from ..security.session import Session
from ..services.actions import Action, perform
from ..services.context import load_inventory, load_traveller, resolve_flight
from ..services.mapping import flight_number
from ..services.state import build_state

router = APIRouter(prefix="/api")


class QuoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    flight_id: str = Field(alias="flightId", pattern=r"^WN\d{1,4}$")
    origin: str = Field(alias="from", pattern=r"^[A-Z]{3}$")
    destination: str = Field(alias="to", pattern=r"^[A-Z]{3}$")
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    needs: dict = Field(default_factory=dict)


def _traveller_or_404(conn, session: Session):
    t = load_traveller(conn, session.passenger_id)  # type: ignore[arg-type]
    if t is None:
        raise HTTPException(status_code=404, detail="Unknown traveller.")
    return t


@router.get("/state")
def get_state(session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    with request_connection() as conn:
        return build_state(conn, session.passenger_id, settings)  # type: ignore[arg-type]


@router.post("/quotes")
def get_quotes(body: QuoteBody, session: Session = Depends(traveller_session)):
    """All four fares priced for this traveller, for a flight and set of needs. Prices never come from the browser."""
    if not any(f.id == body.flight_id for f in FLIGHTS):
        raise HTTPException(status_code=422, detail="Unknown flight.")
    needs = sanitize_needs(body.needs, Needs())
    with request_connection() as conn:
        t = _traveller_or_404(conn, session)
        flight = resolve_flight(conn, flight_number(body.flight_id), body.date, body.origin, body.destination)
        if flight is None:
            raise HTTPException(status_code=404, detail="No flight found.")
        inventory = load_inventory(conn, flight["flight_id"])
    quotes = quote_fares(t.pricing, needs, body.flight_id, inventory)
    best = recommended_quote(quotes)
    return {
        "needs": needs.model_dump(by_alias=True),
        "quotes": [q.model_dump(by_alias=True) for q in quotes],
        "best": best.fare if best else None,
        # What this traveller's tier, card and each fare give them, for the fare cards.
        "entitlements": {q.fare: entitlements(t.pricing, q.fare).model_dump(by_alias=True) for q in quotes},
        "flight": {
            "id": body.flight_id,
            "date": flight["flight_date"].isoformat(),
            "from": flight["origin_airport"],
            "to": flight["destination_airport"],
        },
    }


@router.post("/actions")
def post_action(action: Action, session: Session = Depends(traveller_session), settings: Settings = Depends(settings_dep)):
    """Applies one action and returns the traveller's new state.

    A business-rule refusal (not enough points, check-in not complete...) is a normal answer: HTTP 200 with the
    unchanged state, `error: true` and a message written for the traveller.
    """
    with request_connection() as conn:
        t = _traveller_or_404(conn, session)
        outcome = perform(conn, t, action, settings)
        return build_state(conn, t.passenger_id, settings, outcome.notice, outcome.error)
