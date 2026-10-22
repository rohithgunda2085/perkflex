"""Check-in actions. State changes run inside PostgreSQL (the pf_* functions): each is one atomic transaction with
row locks and an idempotency key, so a retried or double-clicked request cannot apply twice. Python decides which
function to call and words the result for the traveller."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..db import atomic
from ..rules.data import SEAT_NAMES, FareId, SeatClass, seat_rank
from ..rules.pricing import CamelModel, Needs, entitlements
from .booking import ActionRefused, create_booking
from .context import TravellerInfo, clock_now
from .mapping import SEAT_FROM_DB, SEAT_TO_DB
from .state import current_booking_row


@dataclass(frozen=True)
class Outcome:
    notice: str = ""
    error: bool = False


# ---- request shapes (validated by FastAPI; unknown types are rejected with 422) ----
class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    # Send the same key when retrying a request so it is applied once.
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey", max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")


class OpenCheckin(_Base):
    type: Literal["open-checkin"]


class SetBags(_Base):
    type: Literal["bags"]
    count: int = Field(ge=0, le=3)


class Release(_Base):
    type: Literal["release"]
    benefit: Literal["bag", "seat"]


class Redeem(_Base):
    type: Literal["redeem"]
    benefit: Literal["bag", "standard", "preferred", "extra"]


class CheckIn(_Base):
    type: Literal["checkin"]


class Complete(_Base):
    type: Literal["complete"]


class Book(_Base):
    type: Literal["book"]
    fare: FareId
    flight_id: str = Field(alias="flightId", pattern=r"^WN\d{1,4}$")
    origin: str = Field(alias="from", pattern=r"^[A-Z]{3}$")
    destination: str = Field(alias="to", pattern=r"^[A-Z]{3}$")
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    needs: Needs


Action = Annotated[
    OpenCheckin | SetBags | Release | Redeem | CheckIn | Complete | Book,
    Field(discriminator="type"),
]


def _call(conn: psycopg.Connection, function: str, *args) -> dict:
    """Calls one pf_* function. Its RAISE EXCEPTION messages are written for travellers, so they pass through."""
    placeholders = ", ".join(["%s"] * len(args))
    try:
        with atomic(conn):
            return conn.execute(f"SELECT {function}({placeholders}) AS r", args).fetchone()["r"]  # noqa: S608 (fixed names)
    except psycopg.errors.RaiseException as exc:
        raise ActionRefused(exc.diag.message_primary or "That isn’t available right now.") from exc


def _failed(result: dict) -> None:
    """Business outcomes such as 'not enough points' come back as ok = false with a message."""
    if not result.get("ok"):
        raise ActionRefused(result.get("message") or "That didn’t go through. Nothing was changed.")


def _free_upgrade_on_open(conn: psycopg.Connection, t: TravellerInfo, b: dict, now: datetime) -> str:
    """The first time check-in opens, a better seat the traveller's benefits already cover is given at no charge."""
    if b["seat_waiver_flag"]:
        return ""
    e = entitlements(t.pricing, _fare(b), "checkin")
    held: SeatClass = SEAT_FROM_DB[b["seat_type"]]
    if seat_rank(e.seat) <= seat_rank(held):
        return ""
    try:
        with atomic(conn):
            result = conn.execute(
                "SELECT pf_redeem_seat(%s, %s, %s, %s, %s) AS r",
                (t.passenger_id, b["booking_id"], SEAT_TO_DB[e.seat], f"auto-upgrade:{b['booking_id']}", now),
            ).fetchone()["r"]
            if not result.get("ok") or result.get("points_charged", 0) != 0:
                raise ActionRefused("not free")  # roll back: this must never cost points
    except (ActionRefused, psycopg.errors.RaiseException):
        return ""
    return f"Your {e.seat_source} already cover {SEAT_NAMES[e.seat]}. Your seat was updated at no charge."


def _fare(b: dict) -> FareId:
    from .mapping import FARE_FROM_DB

    return FARE_FROM_DB[b["fare_id"]]  # type: ignore[return-value]


def perform(conn: psycopg.Connection, t: TravellerInfo, action: Action, settings: Settings) -> Outcome:
    """Applies one action for the signed-in traveller. Never commits. Refusals come back as Outcome(error=True)."""
    now = clock_now(settings)
    idem = f"{t.passenger_id}:{action.idempotency_key or uuid.uuid4().hex}"
    try:
        if isinstance(action, Book):
            notice = create_booking(
                conn,
                t,
                fare=action.fare,
                flight_code=action.flight_id,
                origin=action.origin,
                destination=action.destination,
                date=action.date,
                needs=action.needs,
                now=now,
            )
            return Outcome(notice)

        b = current_booking_row(conn, t.passenger_id)
        if isinstance(action, OpenCheckin):
            # Navigating to Check in calls this every time; with nothing to open it is quietly a no-op.
            if b is None or b["booking_status"] != "BOOKED":
                return Outcome()
            try:
                _call(conn, "pf_open_checkin", t.passenger_id, b["booking_id"], now)
            except ActionRefused:
                return Outcome()  # check-in is not open yet; offers stay locked and the actions explain why
            if b["checkin_opened_time_utc"] is None:
                return Outcome(_free_upgrade_on_open(conn, t, b, now))
            return Outcome()

        if b is None:
            raise ActionRefused("Book a flight first. You don’t have a trip yet.")
        booking = b["booking_id"]

        if isinstance(action, SetBags):
            _call(conn, "pf_set_bags", t.passenger_id, booking, action.count, now)
            return Outcome()

        if isinstance(action, Release):
            fn = "pf_release_bag" if action.benefit == "bag" else "pf_release_seat"
            result = _call(conn, fn, t.passenger_id, booking, idem, now)
            _failed(result)
            if result.get("replayed"):
                return Outcome(result.get("message", ""))
            return Outcome(f"All set! {result['points_pending']:,} points are pending and will post after you fly.")

        if isinstance(action, Redeem):
            if action.benefit == "bag":
                result = _call(conn, "pf_redeem_bag", t.passenger_id, booking, idem, now)
                _failed(result)
                if result.get("replayed"):
                    return Outcome(result.get("message", ""))
                cost = result["perkflex_points_used"] + result["rapid_rewards_points_used"]
                count = conn.execute("SELECT pf_bag_allowance(%s) AS n", (booking,)).fetchone()["n"]
                return Outcome(f"You’re all set. Checked bag {count} added for {cost:,} points.")
            if action.benefit == "standard":
                raise ActionRefused("Your current seat already includes this benefit.")
            result = _call(conn, "pf_redeem_seat", t.passenger_id, booking, SEAT_TO_DB[action.benefit], idem, now)
            _failed(result)
            if result.get("replayed"):
                return Outcome(result.get("message", ""))
            if result.get("points_charged", 0) == 0:
                return Outcome("This seat is already covered by your benefits. No points charged.")
            return Outcome(
                f"You’re all set. {SEAT_NAMES[action.benefit]} seat added for {result['points_charged']:,} points."
            )

        if isinstance(action, CheckIn):
            _call(conn, "pf_complete_checkin", t.passenger_id, booking, now)
            return Outcome("You’re checked in! Your boarding pass is ready.")

        if isinstance(action, Complete):
            result = _call(conn, "pf_complete_booking", t.passenger_id, booking, now)
            pf, rr = result.get("perkflex_points_posted", 0), result.get("rapid_rewards_points_posted", 0)
            parts = [p for p in (f"{pf:,} PerkFlex points" if pf else "", f"{rr:,} Rapid Rewards points" if rr else "") if p]
            if parts:
                return Outcome(f"Flight complete! {' and '.join(parts)} are now available.")
            return Outcome("Flight complete. Thanks for trying PerkFlex!")
    except ActionRefused as refusal:
        return Outcome(str(refusal), error=True)
    raise AssertionError(f"unhandled action {action!r}")  # pragma: no cover
