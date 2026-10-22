"""Fares, flights and reward values. Ported from the original TypeScript rules data (the rules data, not the demo profiles:
travellers now live in PostgreSQL)."""

from dataclasses import dataclass
from typing import Literal

FareId = Literal["basic", "choice", "preferred", "extra"]
SeatClass = Literal["standard", "preferred", "extra"]
Tier = Literal["Member", "Silver", "Gold", "Platinum"]
Card = Literal["None", "Plus", "Premier", "Priority"]
SeatPreference = Literal["any", "front", "extra"]
Stage = Literal["booking", "checkin"]


@dataclass(frozen=True)
class Fare:
    id: FareId
    name: str
    price: int
    bags: int
    seat: SeatClass
    refundable: bool
    multiplier: int
    description: str


@dataclass(frozen=True)
class Flight:
    id: str
    departure: str
    arrival: str
    duration: str
    offset: int


@dataclass(frozen=True)
class Airport:
    code: str
    city: str


FARES: tuple[Fare, ...] = (
    Fare("basic", "Basic", 150, 0, "standard", False, 2, "The essentials. Your lowest starting fare."),
    Fare("choice", "Choice", 190, 0, "standard", False, 6, "Choose your seat. Keep your plans flexible."),
    Fare("preferred", "Choice Preferred", 230, 0, "preferred", True, 8, "Sit nearer the front, with peace of mind."),
    Fare("extra", "Choice Extra", 270, 2, "extra", True, 10, "More room, two bags, and all the extras."),
)

FLIGHTS: tuple[Flight, ...] = (
    Flight("WN2418", "9:30 AM", "11:00 AM", "2h 30m", 0),
    Flight("WN968", "12:15 PM", "1:50 PM", "2h 35m", 20),
    Flight("WN1820", "5:40 PM", "7:05 PM", "2h 25m", 35),
)

AIRPORTS: tuple[Airport, ...] = (
    Airport("DAL", "Dallas (Love Field)"),
    Airport("DEN", "Denver"),
    Airport("LAS", "Las Vegas"),
    Airport("PHX", "Phoenix"),
    Airport("BNA", "Nashville"),
)

SEAT_NAMES: dict[SeatClass, str] = {
    "standard": "Standard",
    "preferred": "Preferred",
    "extra": "Extra Legroom",
}
SEAT_ORDER: tuple[SeatClass, ...] = ("standard", "preferred", "extra")

# Money is held in whole cents to keep arithmetic exact. Reward values are in points.
TAX_CENTS = 1260
SEAT_CASH: dict[SeatClass, int] = {"standard": 15, "preferred": 35, "extra": 80}  # dollars
BAG_CASH: tuple[int, ...] = (45, 55, 150)  # dollars for the 1st, 2nd and 3rd bag; later bags cost the last price
RELEASE_POINTS = {"bag": 800, "preferred": 700, "extra": 1500}
REDEEM_POINTS = {"bag1": 3000, "bag2": 3500, "preferred": 2200, "extra": 4500}
TIER_BAGS: dict[Tier, int] = {"Member": 0, "Silver": 1, "Gold": 2, "Platinum": 3}


def fare_by_id(fare_id: str) -> Fare:
    for fare in FARES:
        if fare.id == fare_id:
            return fare
    raise KeyError(fare_id)


def flight_by_id(flight_id: str) -> Flight | None:
    return next((f for f in FLIGHTS if f.id == flight_id), None)


def seat_rank(seat: SeatClass) -> int:
    return SEAT_ORDER.index(seat)


def money(value: float) -> str:
    """US dollars with thousands separators, e.g. $1,234.56 (same as the frontend's money())."""
    return f"${value:,.2f}"
