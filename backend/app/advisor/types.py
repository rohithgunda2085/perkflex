"""Shapes for the check-in perk advisor (camelCase on the wire)."""

from typing import Literal

from pydantic import ConfigDict, Field

from ..rules.pricing import CamelModel

OfferId = Literal[
    "RELEASE_BAG",
    "RELEASE_SEAT",
    "REDEEM_BAG",
    "REDEEM_PREFERRED",
    "REDEEM_EXTRA",
    "RELEASE_BOARDING",
    "RELEASE_DRINK",
    "RELEASE_LANE",
    "REDEEM_BOARDING",
    "REDEEM_DRINK",
    "RELEASE_STANDBY",
    "REDEEM_STANDBY",
    "REDEEM_OVERWEIGHT",
]
OFFER_IDS: tuple[str, ...] = (
    "RELEASE_BAG",
    "RELEASE_SEAT",
    "REDEEM_BAG",
    "REDEEM_PREFERRED",
    "REDEEM_EXTRA",
    "RELEASE_BOARDING",
    "RELEASE_DRINK",
    "RELEASE_LANE",
    "REDEEM_BOARDING",
    "REDEEM_DRINK",
    "RELEASE_STANDBY",
    "REDEEM_STANDBY",
    "REDEEM_OVERWEIGHT",
)
# The one rewarded release per flight is a bag OR a seat. Small perks sit beside it and never use that slot.
BIG_RELEASES: frozenset[str] = frozenset({"RELEASE_BAG", "RELEASE_SEAT"})
SMALL_PERK_OFFERS: dict[str, str] = {  # perk id on the booking -> (release offer id, redeem offer id) names
    "boarding": "BOARDING",
    "drink": "DRINK",
    "lane": "LANE",
    "standby": "STANDBY",
    "overweight": "OVERWEIGHT",
}
MAX_PICKS = 4


class AdviceRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")

    # Optional free text, e.g. "I only travel with a backpack". It can narrow the choice, never widen it.
    message: str | None = Field(default=None, max_length=500)


class Offer(CamelModel):
    """One thing the traveller could do right now. Every number comes from the rules, never from the model."""

    id: OfferId
    kind: Literal["release", "redeem"]
    label: str
    # Points the traveller earns (release, pending until they fly) or pays (redeem). 0 when already included.
    points: int
    included: bool = False  # redeem only: the traveller's own benefits already cover it
    affordable: bool = True  # redeem only: balance covers the cost
    shortfall: int = 0  # redeem only: points still needed
    needed: bool = False  # redeem bag only: the traveller's planned luggage exceeds their allowance


class Pick(CamelModel):
    offer_id: OfferId
    why: str


class AdviceResponse(CamelModel):
    # "ai" when the model's answer passed validation, otherwise the rules-only fallback.
    source: Literal["ai", "fallback"]
    summary: str
    picks: list[Pick]
    # Every offer, computed by the rules. The page shows these numbers, not text from the model.
    offers: list[Offer]


class Nudge(CamelModel):
    """A one-line hint shown without asking. Written from the rules by a template: no model is involved."""

    offer_id: OfferId
    kind: Literal["release", "redeem"]
    text: str
    points: int
