"""Booking a flight: price it, take a seat, record the benefits the traveller already holds, and start the earn."""

import secrets
from datetime import datetime

import psycopg

from ..db import atomic
from ..rules.data import TIER_BAGS, SeatClass, fare_by_id, seat_rank
from ..rules.pricing import Needs, Traveller, card_seat, entitlements, quote_fares, tier_seat
from .context import TravellerInfo, load_inventory, resolve_flight
from .mapping import FARE_TO_DB, PREF_SEAT_TO_DB, SEAT_BENEFIT, SEAT_TO_DB, flight_number
from .state import current_booking_row

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class ActionRefused(Exception):
    """A business-rule refusal. The message is written for the traveller."""


def _confirmation_code(conn: psycopg.Connection) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not conn.execute("SELECT 1 FROM fact_booking WHERE confirmation_code = %s", (code,)).fetchone():
            return code
    raise RuntimeError("Could not generate a unique confirmation code")


def benefit_rows(t: Traveller, fare_id: str, held: SeatClass, wanted_bags: int) -> list[tuple]:
    """The benefit rows a new booking starts with: (benefit_id, source, source_code, available_from, used).

    One effective row per bag number and per seat, because pf_bag_allowance and the seat checks add rows up.
    Where the fare, status tier and credit card all give the same thing, the fare is recorded first, then the tier,
    then the card, so nothing is counted twice.
    """
    fare = fare_by_id(fare_id)  # type: ignore[arg-type]
    rows: list[tuple] = []
    tier_bags = TIER_BAGS[t.tier]
    card_bags = 0 if t.card == "None" else 1
    for ordinal in (1, 2, 3):
        if ordinal <= fare.bags:
            source = ("FARE", FARE_TO_DB[fare_id])  # type: ignore[index]
        elif ordinal <= tier_bags:
            source = ("TIER", t.tier.upper())
        elif ordinal <= card_bags:
            source = ("CARD", t.card.upper())
        elif ordinal <= wanted_bags:
            source = ("FARE", "ADDON")  # bought with cash at booking
        else:
            continue
        rows.append((f"BAG{ordinal}", *source, "BOOKING", 1 if ordinal <= wanted_bags else 0))

    def giver(cls: SeatClass, stage) -> tuple[str, str]:
        if seat_rank(fare.seat) >= seat_rank(cls):
            return "FARE", FARE_TO_DB[fare_id]  # type: ignore[index]
        if seat_rank(tier_seat(t.tier, stage)) >= seat_rank(cls):
            return "TIER", t.tier.upper()
        return "CARD", t.card.upper()

    at_booking = entitlements(t, fare_id, "booking").seat  # type: ignore[arg-type]
    at_checkin = entitlements(t, fare_id, "checkin").seat  # type: ignore[arg-type]
    if at_booking != "standard":
        rows.append((SEAT_BENEFIT[at_booking], *giver(at_booking, "booking"), "BOOKING", 1 if held == at_booking else 0))
    if seat_rank(held) > seat_rank(at_booking):
        rows.append((SEAT_BENEFIT[held], "FARE", "ADDON", "BOOKING", 1))  # a seat bought with cash
    # Benefits that only become available once check-in opens (for example Silver's Extra Legroom).
    if seat_rank(at_checkin) > max(seat_rank(at_booking), seat_rank(held)):
        rows.append((SEAT_BENEFIT[at_checkin], *giver(at_checkin, "checkin"), "CHECKIN", 0))
    return rows


def _has_perkflex_activity(conn: psycopg.Connection, booking_id: str) -> bool:
    return conn.execute(
        """SELECT EXISTS (SELECT 1 FROM fact_perkflex_transaction
                           WHERE booking_id = %s AND transaction_status IN ('ACCEPTED','SETTLED')) AS yes""",
        (booking_id,),
    ).fetchone()["yes"]


def _cancel(conn: psycopg.Connection, t: TravellerInfo, prev: dict, now: datetime) -> None:
    """Replaces an unused trip: frees the seat and voids the points that were waiting to be earned."""
    conn.execute("UPDATE fact_booking SET booking_status = 'CANCELLED' WHERE booking_id = %s", (prev["booking_id"],))
    conn.execute("UPDATE dim_seat SET seat_status = 'AVAILABLE' WHERE seat_id = %s", (prev["seat_id"],))
    for pend in conn.execute(
        """SELECT point_transaction_id, points_delta FROM fact_point_transaction pt
            WHERE booking_id = %s AND transaction_type = 'FLIGHT_EARN_PENDING'
              AND NOT EXISTS (SELECT 1 FROM fact_point_transaction x
                               WHERE x.source_point_transaction_id = pt.point_transaction_id)""",
        (prev["booking_id"],),
    ).fetchall():
        conn.execute(
            "SELECT pf_ledger(%s, %s, NULL, 'RAPID_REWARDS', 'VOID', %s, 'VOID', false, %s, %s)",
            (t.passenger_id, prev["booking_id"], -pend["points_delta"], now, pend["point_transaction_id"]),
        )
        conn.execute(
            """UPDATE fact_points_wallet SET rapid_rewards_pending = rapid_rewards_pending - %s,
                      wallet_version = wallet_version + 1, updated_time_utc = %s WHERE passenger_id = %s""",
            (pend["points_delta"], now, t.passenger_id),
        )


def create_booking(
    conn: psycopg.Connection,
    t: TravellerInfo,
    *,
    fare: str,
    flight_code: str,
    origin: str,
    destination: str,
    date: str | None,
    needs: Needs,
    now: datetime,
) -> str:
    """Books the trip. Raises ActionRefused with a traveller-friendly message when it cannot."""
    if origin == destination:
        raise ActionRefused("Choose different departure and arrival airports.")
    flight = resolve_flight(conn, flight_number(flight_code), date, origin, destination)
    if flight is None:
        raise ActionRefused(f"There is no {flight_code.replace('WN', 'WN ')} flight from {origin} to {destination}.")

    inventory = load_inventory(conn, flight["flight_id"])
    quote = next((q for q in quote_fares(t.pricing, needs, flight_code, inventory) if q.fare == fare), None)
    if quote is None or quote.issues:
        raise ActionRefused("This fare does not meet your selected requirements. Update your preferences first.")

    with atomic(conn):
        prev = current_booking_row(conn, t.passenger_id)
        if prev and prev["booking_status"] != "FLOWN":
            if prev["booking_status"] != "BOOKED" or _has_perkflex_activity(conn, prev["booking_id"]):
                raise ActionRefused(
                    "This traveller already has an active trip with points activity. "
                    "Complete the current journey before booking again."
                )
            _cancel(conn, t, prev, now)

        seat = conn.execute(
            """SELECT seat_id FROM dim_seat
                WHERE flight_id = %s AND seat_type = %s AND seat_status IN ('AVAILABLE','RELEASED')
                ORDER BY row_number, seat_number LIMIT 1 FOR UPDATE SKIP LOCKED""",
            (flight["flight_id"], SEAT_TO_DB[quote.seat]),
        ).fetchone()
        if seat is None:
            raise ActionRefused("That seat is no longer available. Please choose another fare.")

        booking_id = conn.execute("SELECT 'B' || nextval('pf_booking_seq') AS id").fetchone()["id"]
        conn.execute(
            """INSERT INTO fact_booking (booking_id, confirmation_code, passenger_id, flight_id, fare_id, seat_id,
                 booking_date_utc, booking_status, cash_total_cents, expected_bag_count, actual_bag_count,
                 pref_seat, pref_refundable_flag, pref_flexible_flag, pref_seat_now_flag, pref_early_boarding_flag,
                 pref_budget_cents)
               VALUES (%s, %s, %s, %s, %s, %s, now(), 'BOOKED', %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                booking_id,
                _confirmation_code(conn),
                t.passenger_id,
                flight["flight_id"],
                FARE_TO_DB[fare],
                seat["seat_id"],
                round(quote.total * 100),
                needs.bags,
                needs.bags,
                PREF_SEAT_TO_DB[needs.seat],
                needs.refund,
                needs.flexible,
                needs.seat_now,
                needs.early,
                round(needs.budget * 100),
            ),
        )
        conn.execute("UPDATE dim_seat SET seat_status = 'ASSIGNED' WHERE seat_id = %s", (seat["seat_id"],))

        for benefit_id, source, code, available_from, used in benefit_rows(t.pricing, fare, quote.seat, needs.bags):
            conn.execute(
                """INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source,
                     source_code, eligible_quantity, available_from, used_quantity)
                   VALUES ('PB' || lpad(nextval('pf_txn_seq')::text, 4, '0'), %s, %s, %s, %s, 1, %s, %s)""",
                (booking_id, benefit_id, source, code, available_from, used),
            )

        # Rapid Rewards points for flying are pending until the trip is completed.
        conn.execute(
            "SELECT pf_ledger(%s, %s, NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING', %s, 'PENDING', true, %s, NULL)",
            (t.passenger_id, booking_id, quote.points, now),
        )
        conn.execute(
            """UPDATE fact_points_wallet SET rapid_rewards_pending = rapid_rewards_pending + %s,
                      wallet_version = wallet_version + 1, updated_time_utc = %s WHERE passenger_id = %s""",
            (quote.points, now, t.passenger_id),
        )
    return "Your flight is booked. Next stop: a trip that feels like you."
