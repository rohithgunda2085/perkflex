"""The traveller's view of the world, built from PostgreSQL. All keys are camelCase, as the frontend expects."""

from typing import Any

import psycopg

from ..config import Settings
from ..rules.data import SEAT_NAMES, SeatClass, seat_rank
from ..rules.pricing import DEFAULT_NEEDS, Needs, entitlements
from .context import TravellerInfo, load_inventory, load_traveller, load_travellers
from .mapping import (
    FARE_FROM_DB,
    PREF_SEAT_FROM_DB,
    SEAT_FROM_DB,
    STATUS_FROM_DB,
    avatar_color,
    flight_code,
    initials,
)


def current_booking_row(conn: psycopg.Connection, passenger_id: str) -> dict | None:
    """The traveller's current trip: an open one if there is one, otherwise the most recent completed one."""
    return conn.execute(
        """SELECT b.*, f.flight_number, f.flight_date, f.origin_airport, f.destination_airport,
                  s.seat_number, s.seat_type,
                  pf_bag_allowance(b.booking_id) AS allowance,
                  (SELECT count(*) FROM fact_passenger_benefit pb JOIN dim_benefit d USING (benefit_id)
                    WHERE pb.booking_id = b.booking_id AND d.benefit_type = 'BAG'
                      AND pb.benefit_source = 'PERKFLEX' AND pb.granted_quantity > 0) AS redeemed_bags,
                  EXISTS (SELECT 1 FROM fact_perkflex_transaction x JOIN dim_benefit d USING (benefit_id)
                           WHERE x.booking_id = b.booking_id AND x.action_type = 'REDEEM'
                             AND d.benefit_type = 'SEAT' AND x.transaction_status IN ('ACCEPTED','SETTLED')
                             AND x.total_benefit_price_points > 0) AS redeemed_seat
             FROM fact_booking b
             JOIN dim_flight_schedule f USING (flight_id)
             LEFT JOIN dim_seat s ON s.seat_id = b.seat_id
            WHERE b.passenger_id = %s AND b.booking_status <> 'CANCELLED'
            ORDER BY (b.booking_status = 'FLOWN'), b.booking_date_utc DESC
            LIMIT 1""",
        (passenger_id,),
    ).fetchone()


def _needs_from_booking(b: dict) -> Needs:
    return Needs(
        bags=b["expected_bag_count"],
        seat=PREF_SEAT_FROM_DB[b["pref_seat"]],
        refund=b["pref_refundable_flag"],
        flexible=b["pref_flexible_flag"],
        seat_now=b["pref_seat_now_flag"],
        early=b["pref_early_boarding_flag"],
        budget=b["pref_budget_cents"] / 100,
    )


def _booking_view(conn: psycopg.Connection, t: TravellerInfo, b: dict) -> dict[str, Any]:
    fare = FARE_FROM_DB[b["fare_id"]]
    seat_class: SeatClass = SEAT_FROM_DB[b["seat_type"]]
    checkin_stage = entitlements(t.pricing, fare, "checkin")
    booking_stage = entitlements(t.pricing, fare, "booking")
    e = checkin_stage if b["checkin_opened_time_utc"] else booking_stage

    allowance, redeemed_bags, redeemed_seat = b["allowance"], b["redeemed_bags"], b["redeemed_seat"]

    if b["seat_waiver_flag"]:
        seat_source = "PerkFlex replacement"
    elif redeemed_seat:
        seat_source = "PerkFlex redemption"
    elif seat_rank(seat_class) > seat_rank(e.seat):
        seat_source = "Seat add-on"
    else:
        seat_source = e.seat_source

    bag_source = (
        "Included benefits + bag add-on" if allowance > e.bags + redeemed_bags else e.bag_source
    )
    return {
        "id": b["confirmation_code"],
        "profileId": t.login_id,
        "fare": fare,
        "flightId": flight_code(b["flight_number"]),
        "from": b["origin_airport"],
        "to": b["destination_airport"],
        "date": b["flight_date"].isoformat(),
        "seat": b["seat_number"],
        "seatClass": seat_class,
        "seatSource": seat_source,
        "bags": allowance,
        "bagSource": bag_source,
        "needs": _needs_from_booking(b).model_dump(by_alias=True),
        "actualBags": b["actual_bag_count"] if b["actual_bag_count"] is not None else b["expected_bag_count"],
        "total": b["cash_total_cents"] / 100,
        "status": STATUS_FROM_DB[b["booking_status"]],
        "released": b["reward_release_used_flag"],
        "releasedSeat": b["seat_waiver_flag"],
        "redeemedSeat": redeemed_seat,
        "redeemedBags": redeemed_bags,
        "clockAdvanced": b["checkin_opened_time_utc"] is not None,
        # What the traveller's benefits cover once check-in is open (the frontend no longer computes this).
        "checkinEntitlements": checkin_stage.model_dump(by_alias=True),
    }


def _ledger_view(conn: psycopg.Connection, passenger_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    # Releases: pending until a matching POST row exists.
    for r in conn.execute(
        """SELECT pt.point_transaction_id, pt.booking_id, pt.points_delta, pt.transaction_time_utc,
                  d.benefit_type, d.seat_class,
                  EXISTS (SELECT 1 FROM fact_point_transaction x
                           WHERE x.source_point_transaction_id = pt.point_transaction_id
                             AND x.transaction_type = 'RELEASE_POST') AS posted,
                  b.confirmation_code
             FROM fact_point_transaction pt
             JOIN fact_perkflex_transaction t ON t.transaction_id = pt.perkflex_transaction_id
             JOIN dim_benefit d ON d.benefit_id = t.benefit_id
             JOIN fact_booking b ON b.booking_id = pt.booking_id
            WHERE pt.passenger_id = %s AND pt.transaction_type = 'RELEASE_PENDING'""",
        (passenger_id,),
    ):
        label = (
            "Unused checked-bag allowance"
            if r["benefit_type"] == "BAG"
            else f"{SEAT_NAMES[SEAT_FROM_DB[r['seat_class']]]} → Standard seat"
        )
        entries.append(
            {
                "id": r["point_transaction_id"],
                "bookingId": r["confirmation_code"],
                "kind": "release",
                "label": label,
                "points": r["points_delta"],
                "status": "posted" if r["posted"] else "pending",
                "createdAt": r["transaction_time_utc"].isoformat(),
            }
        )
    # Redemptions: one entry per purchase, even when paid from two point balances.
    for r in conn.execute(
        """SELECT pt.perkflex_transaction_id, b.confirmation_code, sum(pt.points_delta) AS points,
                  max(pt.transaction_time_utc) AS at, d.benefit_type, d.seat_class, d.bag_ordinal
             FROM fact_point_transaction pt
             JOIN fact_perkflex_transaction t ON t.transaction_id = pt.perkflex_transaction_id
             JOIN dim_benefit d ON d.benefit_id = t.benefit_id
             JOIN fact_booking b ON b.booking_id = pt.booking_id
            WHERE pt.passenger_id = %s AND pt.transaction_type = 'BENEFIT_DEBIT'
            GROUP BY pt.perkflex_transaction_id, b.confirmation_code, d.benefit_type, d.seat_class, d.bag_ordinal""",
        (passenger_id,),
    ):
        label = (
            f"Checked bag {r['bag_ordinal']}"
            if r["benefit_type"] == "BAG"
            else f"{SEAT_NAMES[SEAT_FROM_DB[r['seat_class']]]} seat"
        )
        entries.append(
            {
                "id": r["perkflex_transaction_id"],
                "bookingId": r["confirmation_code"],
                "kind": "redemption",
                "label": label,
                "points": int(r["points"]),
                "status": "posted",
                "createdAt": r["at"].isoformat(),
            }
        )
    entries.sort(key=lambda e: e["createdAt"], reverse=True)
    return entries


def profile_view(t: TravellerInfo, needs: Needs | None = None, trip: bool = False) -> dict[str, Any]:
    return {
        "id": t.login_id,
        "name": t.name,
        "initials": initials(t.name),
        "tier": t.tier,
        "card": t.card,
        "color": avatar_color(t.login_id, t.tier),
        "description": t.story,
        "points": t.balance,
        "needs": (needs or DEFAULT_NEEDS).model_dump(by_alias=True),
        "hasTrip": trip,
    }


def build_state(
    conn: psycopg.Connection,
    passenger_id: str,
    settings: Settings,
    notice: str = "",
    error: bool = False,
) -> dict[str, Any]:
    t = load_traveller(conn, passenger_id)
    if t is None:
        raise LookupError(passenger_id)
    row = current_booking_row(conn, passenger_id)
    booking = _booking_view(conn, t, row) if row else None
    inventory = None
    if row:
        inv = load_inventory(conn, row["flight_id"])
        inventory = {"flightId": booking["flightId"], **inv.model_dump(by_alias=True)}  # type: ignore[index]

    travellers = [profile_view(other) for other in load_travellers(conn)] if settings.demo_mode else []

    return {
        "profile": profile_view(t, _needs_from_booking(row) if row else None, trip=row is not None),
        "balance": t.balance,
        "pending": t.pf_pending,
        "booking": booking,
        "inventory": inventory,
        "ledger": _ledger_view(conn, passenger_id),
        "travellers": travellers,
        "demo": settings.demo_mode,
        "notice": notice,
        "error": error,
    }
