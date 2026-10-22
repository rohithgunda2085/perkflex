"""Request and response shapes for the fare assistant (camelCase on the wire)."""

from typing import Literal

from pydantic import ConfigDict, Field

from ..rules.data import FareId
from ..rules.pricing import CamelModel, Needs, Quote


class BestFareRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")  # merged with CamelModel's camelCase aliases

    # Optional free text, e.g. "two bags, near the front, refundable, under $400".
    message: str | None = Field(default=None, max_length=500)
    # The traveller's form selections; anything missing falls back to the defaults.
    needs: dict | None = None
    flight_id: str = Field(pattern=r"^WN\d{1,4}$")
    origin: str = Field(alias="from", pattern=r"^[A-Z]{3}$")
    destination: str = Field(alias="to", pattern=r"^[A-Z]{3}$")
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class Recommendation(CamelModel):
    fare: FareId | None  # None when no fare meets every need
    total: float | None
    reasons: list[str]


class Alternative(CamelModel):
    fare: FareId
    total: float
    tradeoff: str


class BestFareResponse(CamelModel):
    # "ai" when the model's answer passed validation, otherwise the rules-only fallback.
    source: Literal["ai", "fallback"]
    # The needs the recommendation was made for (the form, merged with the message).
    understood: Needs
    recommendation: Recommendation
    # Closest options when nothing fits, each priced by the rules engine.
    alternatives: list[Alternative]
    explanation: str
    # All four fares, priced by the rules engine. Never produced by the model.
    quotes: list[Quote]
