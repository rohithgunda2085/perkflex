"""Reads shared by the state view, the actions and the assistant: the traveller, flights, seat inventory, the clock."""

from dataclasses import dataclass
from datetime import date, datetime, timezone

import psycopg

from ..config import Settings
from ..rules.pricing import Inventory, Traveller
from .mapping import CARD_FROM_DB, SEAT_FROM_DB, TIER_FROM_DB


@dataclass(frozen=True)
class TravellerInfo:
    passenger_id: str
    login_id: str
    name: str
    story: str
    tier: str
    card: str
    rr_available: int
    rr_pending: int
    pf_available: int
    pf_pending: int
    rapid_first: bool = False
    tqp: int = 0

    @property
    def pricing(self) -> Traveller:
        return Traveller(self.tier, self.card)  # type: ignore[arg-type]

    @property
    def balance(self) -> int:
        """What the traveller can spend: PerkFlex points plus Rapid Rewards points."""
        return self.rr_available + self.pf_available


_TRAVELLER_SQL = """SELECT p.passenger_id, u.login_id, p.passenger_name, p.demo_story, p.tier_status,
                  p.credit_card_type, w.rapid_rewards_available, w.rapid_rewards_pending,
                  w.perkflex_available, w.perkflex_pending, w.pay_rapid_first, p.tqp_ytd
             FROM dim_passenger p
             JOIN fact_points_wallet w USING (passenger_id)
             JOIN dim_user_account u USING (passenger_id)"""


def _traveller(row: dict) -> TravellerInfo:
    return TravellerInfo(
        passenger_id=row["passenger_id"],
        login_id=row["login_id"],
        name=row["passenger_name"],
        story=row["demo_story"],
        tier=TIER_FROM_DB[row["tier_status"]],
        card=CARD_FROM_DB[row["credit_card_type"]],
        rr_available=row["rapid_rewards_available"],
        rr_pending=row["rapid_rewards_pending"],
        pf_available=row["perkflex_available"],
        pf_pending=row["perkflex_pending"],
        rapid_first=row["pay_rapid_first"],
        tqp=row["tqp_ytd"],
    )


def load_traveller(conn: psycopg.Connection, passenger_id: str) -> TravellerInfo | None:
    row = conn.execute(_TRAVELLER_SQL + " WHERE p.passenger_id = %s", (passenger_id,)).fetchone()
    return _traveller(row) if row else None


def load_travellers(conn: psycopg.Connection) -> list[TravellerInfo]:
    """Every traveller, in one query (used by the demo traveller switcher)."""
    return [_traveller(r) for r in conn.execute(_TRAVELLER_SQL + " ORDER BY p.passenger_id")]


def resolve_flight(
    conn: psycopg.Connection, number: str, on: str | None, origin: str, destination: str
) -> dict | None:
    """The scheduled flight with this number on this route whose date is closest to `on` (today when not given).

    The database holds one flight per number, route and date, so a search for a date with no flight lands on the
    nearest one.
    """
    wanted: date | None = None
    if on:
        try:
            wanted = date.fromisoformat(on)
        except ValueError:
            wanted = None
    return conn.execute(
        """SELECT flight_id, flight_number, flight_date, origin_airport, destination_airport,
                  departure_time_utc, checkin_open_time_utc, fare_offset_cents
             FROM dim_flight_schedule
            WHERE flight_number = %s AND origin_airport = %s AND destination_airport = %s
              AND flight_status = 'SCHEDULED'
            ORDER BY abs(flight_date - COALESCE(%s::date, CURRENT_DATE)), flight_date
            LIMIT 1""",
        (number, origin, destination, wanted),
    ).fetchone()


def load_inventory(conn: psycopg.Connection, flight_id: str) -> Inventory:
    """Free seats by class (in row order) and the flight's remaining reward budget and bag grants."""
    seats: dict = {"standard": [], "preferred": [], "extra": []}
    for r in conn.execute(
        """SELECT seat_type, seat_number FROM dim_seat
            WHERE flight_id = %s AND seat_status IN ('AVAILABLE','RELEASED')
            ORDER BY row_number, seat_number""",
        (flight_id,),
    ):
        seats[SEAT_FROM_DB[r["seat_type"]]].append(r["seat_number"])
    campaign = conn.execute(
        "SELECT budget_remaining_points, bag_grants_remaining FROM fact_flight_campaign WHERE flight_id = %s",
        (flight_id,),
    ).fetchone()
    return Inventory(
        seats=seats,
        budget=campaign["budget_remaining_points"] if campaign else 0,
        bag_grants=campaign["bag_grants_remaining"] if campaign else 0,
    )


def clock_now(settings: Settings) -> datetime:
    """The time check-in windows are judged against: the pinned demo time when set, otherwise the real time."""
    if settings.demo_now:
        pinned = datetime.fromisoformat(settings.demo_now)
        return pinned if pinned.tzinfo else pinned.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)
