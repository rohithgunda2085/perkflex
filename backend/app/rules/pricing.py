"""Pricing rules: what a traveller already has, and what each fare costs them.

Ported from the original TypeScript rules engine (entitlements / quoteFares / recommendedQuote). The port is checked
against outputs that engine generated before it was removed (tests/fixtures/pricing_parity.json, used by
tests/test_pricing_parity.py).
Models serialise to camelCase, which is what the frontend already expects.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .data import (
    BAG_CASH,
    FARES,
    SEAT_CASH,
    SEAT_NAMES,
    TAX_CENTS,
    TIER_BAGS,
    TIER_FLYING_BONUS_PCT,
    Card,
    FareId,
    SeatClass,
    SeatPreference,
    Stage,
    Tier,
    fare_by_id,
    flight_by_id,
    flying_points,
    seat_rank,
)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Needs(CamelModel):
    bags: int = 0
    seat: SeatPreference = "any"
    refund: bool = False
    flexible: bool = False
    seat_now: bool = False
    early: bool = False
    budget: float = 450


DEFAULT_NEEDS = Needs()


@dataclass(frozen=True)
class Traveller:
    """The only facts the pricing rules need about a person."""

    tier: Tier
    card: Card


class Entitlements(CamelModel):
    bags: int
    bag_source: str
    seat: SeatClass
    seat_source: str
    choose_now: bool
    refundable: bool
    flexible: bool
    early: bool


class Addon(CamelModel):
    label: str
    price: int


class Quote(CamelModel):
    fare: FareId
    base: int
    tax: float
    total: float
    addons: list[Addon]
    bags: int
    seat: SeatClass
    seat_source: str
    bag_source: str
    issues: list[str]
    points: int
    # How `points` was worked out: base fare x rate, plus the traveller's status bonus (percent).
    rate: int = 0
    status_bonus: int = 0


class Inventory(CamelModel):
    """Available seats by class (the seat numbers themselves), plus the flight's reward budget."""

    seats: dict[SeatClass, list[str]]
    budget: int = 0
    bag_grants: int = 0


def tier_seat(tier: Tier, stage: Stage) -> SeatClass:
    """The best seat class a status tier grants: Gold/Platinum always, Silver Preferred then Extra at check-in."""
    if tier in ("Gold", "Platinum") or (tier == "Silver" and stage == "checkin"):
        return "extra"
    return "preferred" if tier == "Silver" else "standard"


def card_seat(card: Card, stage: Stage) -> SeatClass:
    """The best seat class a credit card grants."""
    return {
        "None": "standard",
        "Plus": "standard",
        "Premier": "preferred" if stage == "checkin" else "standard",
        "Priority": "extra" if stage == "checkin" else "preferred",
    }[card]


def entitlements(traveller: Traveller, fare_id: FareId, stage: Stage = "booking") -> Entitlements:
    fare = fare_by_id(fare_id)
    tier, card = traveller.tier, traveller.card
    tier_bags = TIER_BAGS[tier]
    card_bags = 0 if card == "None" else 1
    bags = max(fare.bags, tier_bags, card_bags)
    if bags == 0:
        bag_source = "No bags included"
    elif tier_bags == bags:
        bag_source = f"{tier} benefits"
    elif fare.bags == bags:
        bag_source = fare.name
    else:
        bag_source = f"{card} card"

    seat: SeatClass = fare.seat
    seat_source = fare.name
    if seat_rank(tier_seat(tier, stage)) > seat_rank(seat):
        seat, seat_source = tier_seat(tier, stage), f"{tier} benefits"
    if seat_rank(card_seat(card, stage)) > seat_rank(seat):
        seat, seat_source = card_seat(card, stage), f"{card} card"

    choose_now = (
        fare_id != "basic"
        or tier != "Member"
        or card == "Priority"
        or (stage == "checkin" and card != "None")
    )
    return Entitlements(
        bags=bags,
        bag_source=bag_source,
        seat=seat,
        seat_source=seat_source,
        choose_now=choose_now,
        refundable=fare.refundable,
        flexible=fare_id != "basic",
        early=fare_id in ("preferred", "extra") or tier != "Member",
    )


def quote_fares(
    traveller: Traveller,
    needs: Needs,
    flight_id: str,
    inventory: Inventory | None = None,
) -> list[Quote]:
    flight = flight_by_id(flight_id)
    if flight is None:
        raise ValueError(f"Unknown flight {flight_id}")
    wanted: SeatClass = {"extra": "extra", "front": "preferred"}.get(needs.seat, "standard")  # type: ignore[assignment]
    quotes: list[Quote] = []
    for fare in FARES:
        e = entitlements(traveller, fare.id)
        addons: list[Addon] = []
        issues: list[str] = []
        seat, seat_source = e.seat, e.seat_source

        if seat_rank(wanted) > seat_rank(seat):
            addons.append(Addon(label=f"{SEAT_NAMES[wanted]} seat", price=SEAT_CASH[wanted]))
            seat, seat_source = wanted, "Seat add-on"
        elif needs.seat_now and not e.choose_now:
            addons.append(Addon(label="Select a Standard seat now", price=SEAT_CASH["standard"]))
            seat_source = "Seat add-on"

        if inventory is not None and len(inventory.seats.get(seat, [])) == 0:
            if needs.seat != "any":
                issues.append(f"{SEAT_NAMES[seat]} seats unavailable")
            else:
                seat, seat_source = "standard", "Available Standard seat"

        for ordinal in range(e.bags, needs.bags):
            price = BAG_CASH[ordinal] if ordinal < len(BAG_CASH) else 150
            addons.append(Addon(label=f"Checked bag {ordinal + 1}", price=price))

        if needs.refund and not e.refundable:
            issues.append("Not refundable")
        if needs.flexible and not e.flexible:
            issues.append("Flight changes not included")
        if needs.early and not e.early:
            issues.append("Priority boarding not included")

        base = fare.price + flight.offset
        total_cents = (base + sum(a.price for a in addons)) * 100 + TAX_CENTS
        total = total_cents / 100
        if total > needs.budget:
            issues.append("Over your budget")

        quotes.append(
            Quote(
                fare=fare.id,
                base=base,
                tax=TAX_CENTS / 100,
                total=total,
                addons=addons,
                bags=max(e.bags, needs.bags),
                seat=seat,
                seat_source=seat_source,
                bag_source=(
                    "Included benefits + bag add-on" if needs.bags > e.bags else e.bag_source
                ),
                issues=issues,
                points=flying_points(base, fare.multiplier, traveller.tier),
                rate=fare.multiplier,
                status_bonus=TIER_FLYING_BONUS_PCT[traveller.tier],
            )
        )
    return quotes


def recommended_quote(quotes: list[Quote]) -> Quote | None:
    """The cheapest fare that meets every need. Ties keep the original fare order (stable sort)."""
    fits = [q for q in quotes if not q.issues]
    return sorted(fits, key=lambda q: q.total)[0] if fits else None


def sanitize_needs(raw: Any, base: Needs) -> Needs:
    """Clamps anything from the browser or the model into a valid Needs; unknown fields fall back to `base`."""
    r: dict[str, Any] = raw if isinstance(raw, dict) else {}

    def flag(key: str, attr: str) -> bool:
        value = r.get(key)
        return value if isinstance(value, bool) else getattr(base, attr)

    bags = r.get("bags")
    budget = r.get("budget")
    seat = r.get("seat")
    return Needs(
        bags=min(3, max(0, bags)) if isinstance(bags, int) and not isinstance(bags, bool) else base.bags,
        seat=seat if seat in ("any", "front", "extra") else base.seat,
        refund=flag("refund", "refund"),
        flexible=flag("flexible", "flexible"),
        seat_now=flag("seatNow", "seat_now"),
        early=flag("early", "early"),
        budget=(
            min(2000, max(100, budget))
            if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget == budget
            else base.budget
        ),
    )
