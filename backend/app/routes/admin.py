"""The airline's reward-programme overview. Airline accounts only."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..db import request_connection
from ..deps import current_session
from ..security.session import Session
from ..services.admin import overview
from ..services.controls import ControlError, controls_view, set_sale, update_policy

router = APIRouter(prefix="/api/admin")


def airline_session(session: Session = Depends(current_session)) -> Session:
    """The airline admin account has no traveller (no passenger id). Travellers must never see this data."""
    if session.passenger_id:
        raise HTTPException(status_code=403, detail="This view is for the airline.")
    return session


@router.get("/overview")
def get_overview(_: Session = Depends(airline_session)):
    with request_connection() as conn:
        return overview(conn)


class PolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    mode: str | None = Field(default=None, pattern=r"^(FLAT|VALUE)$")
    value_percent: int | None = Field(default=None, alias="valuePercent", ge=1, le=60)
    cents_per_point: float | None = Field(default=None, alias="centsPerPoint", ge=0.25, le=5)
    completion_bonus: int | None = Field(default=None, alias="completionBonus", ge=0, le=500)


class SaleBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    flight_id: str = Field(alias="flightId", pattern=r"^F\d{2,4}$")
    benefit: str = Field(pattern=r"^[a-z]{3,12}$")
    discount_pct: int = Field(alias="discountPct", ge=0, le=50)  # 0 ends the sale


@router.get("/controls")
def get_controls(_: Session = Depends(airline_session)):
    with request_connection() as conn:
        return controls_view(conn)


@router.post("/policy")
def post_policy(body: PolicyBody, session: Session = Depends(airline_session)):
    with request_connection() as conn:
        update_policy(
            conn, session.user_id, mode=body.mode, value_percent=body.value_percent,
            cents_per_point=body.cents_per_point, completion_bonus=body.completion_bonus,
        )
        return controls_view(conn)


@router.post("/sale")
def post_sale(body: SaleBody, session: Session = Depends(airline_session)):
    if 0 < body.discount_pct < 5:
        raise HTTPException(status_code=422, detail="A sale is 5 to 50 percent off.")
    with request_connection() as conn:
        try:
            set_sale(conn, session.user_id, body.flight_id, body.benefit, body.discount_pct)
        except ControlError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return controls_view(conn)
