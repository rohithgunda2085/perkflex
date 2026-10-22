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
from ..email.outbox import EMAIL_KIND_BY_ACTION, queue_for_traveller
from ..rules.data import SEAT_NAMES, FareId, SeatClass, seat_rank
from ..rules.pricing import CamelModel, Needs, entitlements
from .booking import ActionRefused, create_booking
from .context import TravellerInfo, clock_now
from .mapping import SEAT_FROM_DB, SEAT_TO_DB
from .state import current_booking_row


# Small perks: the app's word -> the dim_benefit id
PERK_BENEFIT = {
    "boarding": "PERK_BOARDING",
    "drink": "PERK_DRINK",
    "lane": "PERK_LANE",
    "standby": "PERK_STANDBY",
    "overweight": "PERK_OVERWEIGHT",
    "meal": "PERK_MEAL",
}


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
    benefit: Literal["bag", "seat", "boarding", "drink", "lane", "standby"]


class Redeem(_Base):
    type: Literal["redeem"]
    benefit: Literal["bag", "standard", "preferred", "extra", "boarding", "drink", "standby", "overweight", "meal"]


class Undo(_Base):
    type: Literal["undo"]
    benefit: Literal["bag", "seat", "boarding", "drink", "lane", "standby"]


class PayOrder(_Base):
    type: Literal["payment-order"]
    rapid_first: bool = Field(alias="rapidFirst")


class GroupInvite(_Base):
    type: Literal["group-invite"]
    companion: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._@-]+$")  # login id or Rapid Rewards number


class GroupRespond(_Base):
    type: Literal["group-respond"]
    group: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._@-]+$")  # the organiser's login id
    accept: bool


class GroupLeave(_Base):
    type: Literal["group-leave"]


class Gift(_Base):
    type: Literal["gift"]
    to: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._@-]+$")  # a group member's login id
    points: int = Field(ge=1, le=100000)  # the database enforces the real limits (100 to 2,000 per gift)


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
    OpenCheckin | SetBags | Release | Redeem | Undo | PayOrder | GroupInvite | GroupRespond | GroupLeave | Gift
    | CheckIn | Complete | Book,
    Field(discriminator="type"),
]


def _paid(pf: int, rr: int) -> str:
    """'600 PerkFlex', '300 PerkFlex + 300 Rapid Rewards'... : which wallet(s) a purchase was taken from."""
    parts = [f"{pf:,} PerkFlex" if pf else "", f"{rr:,} Rapid Rewards" if rr else ""]
    return " + ".join(p for p in parts if p) or "0"


def _seat_split(conn: psycopg.Connection, transaction_id: str) -> tuple[int, int]:
    """What a seat purchase took from each wallet (the SQL function reports only the total)."""
    row = conn.execute(
        """SELECT COALESCE(-sum(points_delta) FILTER (WHERE point_type = 'PERKFLEX'), 0) AS pf,
                  COALESCE(-sum(points_delta) FILTER (WHERE point_type = 'RAPID_REWARDS'), 0) AS rr
             FROM fact_point_transaction WHERE perkflex_transaction_id = %s AND transaction_type = 'BENEFIT_DEBIT'""",
        (transaction_id,),
    ).fetchone()
    return int(row["pf"]), int(row["rr"])


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


def _passenger_for(conn: psycopg.Connection, who: str) -> str | None:
    """A traveller's passenger id from their login id or their Rapid Rewards number."""
    row = conn.execute(
        """SELECT p.passenger_id FROM dim_passenger p LEFT JOIN dim_user_account u USING (passenger_id)
            WHERE lower(u.login_id) = lower(%(w)s) OR upper(p.rapid_rewards_account_id) = upper(%(w)s) LIMIT 1""",
        {"w": who},
    ).fetchone()
    return row["passenger_id"] if row else None


def _social(conn: psycopg.Connection, t: TravellerInfo, action: Action, idem: str, now: datetime) -> Outcome:
    """Travel groups and gifts."""
    if isinstance(action, GroupLeave):
        return Outcome(_call(conn, "pf_group_leave", t.passenger_id)["message"])
    other = _passenger_for(
        conn, action.companion if isinstance(action, GroupInvite) else action.group if isinstance(action, GroupRespond) else action.to  # type: ignore[union-attr]
    )
    if other is None:
        raise ActionRefused("We could not find that traveller.")
    if isinstance(action, GroupInvite):
        return Outcome(_call(conn, "pf_group_invite", t.passenger_id, other)["message"])
    if isinstance(action, GroupRespond):
        return Outcome(_call(conn, "pf_group_respond", t.passenger_id, other, action.accept)["message"])
    result = _call(conn, "pf_gift_points", t.passenger_id, other, action.points, idem, now)  # type: ignore[union-attr]
    return Outcome(result["message"])


def _apply(conn: psycopg.Connection, t: TravellerInfo, action: Action, settings: Settings) -> Outcome:
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

        if isinstance(action, (GroupInvite, GroupRespond, GroupLeave, Gift)):
            return _social(conn, t, action, idem, now)  # these need no trip

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

        if isinstance(action, PayOrder):
            _call(conn, "pf_set_pay_order", t.passenger_id, action.rapid_first)
            return Outcome(
                "Rapid Rewards points will be used first, then PerkFlex."
                if action.rapid_first
                else "PerkFlex points will be used first, then Rapid Rewards."
            )

        if isinstance(action, Undo):
            benefit_id = {"bag": None, "seat": None, **PERK_BENEFIT}[action.benefit]
            row = conn.execute(
                """SELECT t.transaction_id FROM fact_perkflex_transaction t JOIN dim_benefit d USING (benefit_id)
                    WHERE t.booking_id = %s AND t.action_type = 'RELEASE' AND t.transaction_status = 'ACCEPTED'
                      AND (CASE WHEN %s::text IS NOT NULL THEN t.benefit_id = %s
                                WHEN %s = 'bag' THEN d.benefit_type = 'BAG' ELSE d.benefit_type = 'SEAT' END)
                    ORDER BY t.recorded_at DESC LIMIT 1""",
                (booking, benefit_id, benefit_id, action.benefit),
            ).fetchone()
            if row is None:
                raise ActionRefused("There is no release to undo.")
            result = _call(conn, "pf_undo_release", t.passenger_id, booking, row["transaction_id"], now)
            _failed(result)
            if result.get("replayed"):
                return Outcome(result.get("message", ""))
            return Outcome(f"Release undone. {result['points_returned']:,} pending points were taken back and your benefit is restored.")

        if isinstance(action, SetBags):
            _call(conn, "pf_set_bags", t.passenger_id, booking, action.count, now)
            return Outcome()

        if isinstance(action, Release) and action.benefit in PERK_BENEFIT:
            result = _call(conn, "pf_release_perk", t.passenger_id, booking, PERK_BENEFIT[action.benefit], idem, now)
            _failed(result)
            if result.get("replayed"):
                return Outcome(result.get("message", ""))
            return Outcome(f"All set! {result['points_pending']:,} points are pending and will post after you fly.")

        if isinstance(action, Redeem) and action.benefit in PERK_BENEFIT:
            result = _call(conn, "pf_redeem_perk", t.passenger_id, booking, PERK_BENEFIT[action.benefit], idem, now)
            _failed(result)
            if result.get("replayed"):
                return Outcome(result.get("message", ""))
            paid = _paid(result["perkflex_points_used"], result["rapid_rewards_points_used"])
            return Outcome(f"You’re all set. {result['message']} for {paid} points.")

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
                paid = _paid(result["perkflex_points_used"], result["rapid_rewards_points_used"])
                count = conn.execute("SELECT pf_bag_allowance(%s) AS n", (booking,)).fetchone()["n"]
                return Outcome(f"You’re all set. Checked bag {count} added for {paid} points.")
            if action.benefit == "standard":
                raise ActionRefused("Your current seat already includes this benefit.")
            result = _call(conn, "pf_redeem_seat", t.passenger_id, booking, SEAT_TO_DB[action.benefit], idem, now)
            _failed(result)
            if result.get("replayed"):
                return Outcome(result.get("message", ""))
            if result.get("points_charged", 0) == 0:
                return Outcome("This seat is already covered by your benefits. No points charged.")
            paid = _paid(*_seat_split(conn, result["transaction_id"]))
            return Outcome(f"You’re all set. {SEAT_NAMES[action.benefit]} seat added for {paid} points.")

        if isinstance(action, CheckIn):
            _call(conn, "pf_complete_checkin", t.passenger_id, booking, now)
            return Outcome("You’re checked in! Your boarding pass is ready.")

        if isinstance(action, Complete):
            result = _call(conn, "pf_complete_booking", t.passenger_id, booking, now)
            pf, rr = result.get("perkflex_points_posted", 0), result.get("rapid_rewards_points_posted", 0)
            bonus = result.get("completion_bonus", 0)
            award = result.get("flight_award", 0)
            award_note = result.get("award_note")
            parts = [
                p
                for p in (
                    f"+{pf:,} PerkFlex (released benefits)" if pf else "",
                    f"+{bonus:,} PerkFlex (completion bonus)" if bonus else "",
                    f"+{award:,} PerkFlex (flight award{', ' + award_note if award_note else ''})" if award else "",
                    f"+{rr:,} Rapid Rewards (flying)" if rr else "",
                )
                if p
            ]
            if parts:
                return Outcome(f"Flight complete! {' and '.join(parts)}. Your PerkFlex points stay for your next flight.")
            return Outcome("Flight complete. Thanks for trying PerkFlex!")
    except ActionRefused as refusal:
        return Outcome(str(refusal), error=True)
    raise AssertionError(f"unhandled action {action!r}")  # pragma: no cover


def perform(conn: psycopg.Connection, t: TravellerInfo, action: Action, settings: Settings) -> Outcome:
    """Applies one action for the signed-in traveller, then queues its email. Never commits.

    The email is queued in the same transaction, so a refused or rolled-back action sends nothing. A repeated request
    with the same idempotency key queues the email once.
    """
    outcome = _apply(conn, t, action, settings)
    kind = EMAIL_KIND_BY_ACTION.get(action.type)
    if kind and not outcome.error and outcome.notice and settings.email_enabled:
        key = f"{t.passenger_id}:{action.idempotency_key}:{kind}" if action.idempotency_key else None
        queue_for_traveller(conn, t.passenger_id, kind, outcome.notice, key)
    return outcome
