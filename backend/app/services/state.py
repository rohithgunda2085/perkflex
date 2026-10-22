"""The traveller's view of the world, built from PostgreSQL. All keys are camelCase, as the frontend expects."""

from typing import Any

import psycopg

from ..config import Settings
from ..rules.data import SEAT_NAMES, TIER_RELEASE_BONUS_PCT, SeatClass, release_points, seat_rank
from ..rules.pricing import DEFAULT_NEEDS, Needs, entitlements
from .context import TravellerInfo, load_inventory, load_traveller, load_travellers
from .seasons import award_for, promos_view
from .extras import extra_alerts, group_view, policy_view, prices_view, release_table, status_nudge
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


PERK_CODE = {
    "PERK_BOARDING": "boarding",
    "PERK_DRINK": "drink",
    "PERK_LANE": "lane",
    "PERK_STANDBY": "standby",
    "PERK_OVERWEIGHT": "overweight",
    "PERK_MEAL": "meal",
}
PERK_CAP = 300  # small-perk release points per booking (pf_release_perk enforces the same number)
EXPIRY_NOTIFY_DAYS = 14  # an expiry this close becomes a notification
UNDO_SECONDS = 60  # the undo window, in real seconds
EXPIRY_SOON_DAYS = 60

# 2027 status levels (concept values; see docs/SOUTHWEST_BENEFITS.md). Shown read-only.
TIER_STEPS = [
    ("Member", 0, ["Points for flying", "Pay with points"]),
    ("Silver", 35000, ["1 free checked bag", "Priority lane and boarding", "Same-day standby", "+40% flying points"]),
    ("Gold", 65000, ["2 free checked bags", "2 premium drinks", "Earlier boarding", "+60% flying points"]),
    ("Platinum", 140000, ["3 free checked bags", "Any seat", "+120% flying points"]),
]
MILESTONES = [
    (20000, "2,000 bonus points or 2 Preferred Seat Certificates"),
    (95000, "3 Companion Pass trips"),
]


def _perks_view(conn: psycopg.Connection, booking_id: str, tier: str, flight_id: str = "") -> list[dict[str, Any]]:
    """The small perks (priority boarding, premium drink, priority lane) and where each one stands for this trip.

    `included` comes from the fare and tier inside PostgreSQL (pf_perk_source), the same test the release and
    redeem functions apply, so what the page offers always matches what the database will accept.
    """
    cap_left = PERK_CAP - int(
        conn.execute(
            """SELECT COALESCE(sum(d.perkflex_release_points), 0) AS n  -- base points: the cap ignores the status bonus
                 FROM fact_perkflex_transaction t JOIN dim_benefit d USING (benefit_id)
                WHERE t.booking_id = %s AND d.benefit_type = 'PERK' AND t.action_type = 'RELEASE'
                  AND t.transaction_status IN ('ACCEPTED','SETTLED')""",
            (booking_id,),
        ).fetchone()["n"]
    )
    rows = conn.execute(
        """SELECT d.benefit_id, d.benefit_name, d.perkflex_release_points AS release_points,
                  d.perkflex_redeem_points AS list_points, pf_redeem_price(%(f)s, d.benefit_id) AS redeem_points,
                  pf_perk_source(%(b)s, d.benefit_id) AS source,
                  EXISTS (SELECT 1 FROM fact_passenger_benefit pb WHERE pb.booking_id = %(b)s
                           AND pb.benefit_id = d.benefit_id AND pb.released_quantity > 0) AS released,
                  EXISTS (SELECT 1 FROM fact_passenger_benefit pb WHERE pb.booking_id = %(b)s
                           AND pb.benefit_id = d.benefit_id AND pb.benefit_source = 'PERKFLEX'
                           AND pb.granted_quantity > 0) AS bought
             FROM dim_benefit d WHERE d.benefit_type = 'PERK' ORDER BY d.benefit_id""",
        {"b": booking_id, "f": flight_id},
    ).fetchall()
    return [
        {
            "id": PERK_CODE[r["benefit_id"]],
            "name": r["benefit_name"],
            "included": r["source"] is not None,
            "source": {"FARE": "fare", "TIER": "tier"}.get(r["source"] or "", ""),
            "released": r["released"],
            "bought": r["bought"],
            "releasePoints": release_points(r["release_points"], tier),  # includes the status bonus
            "redeemPoints": r["redeem_points"],  # after any sale on this flight
            "listPoints": r["list_points"],
            # false once the 300-point small-perk cap has no room for this one (the database refuses it too)
            "capRoom": r["release_points"] <= cap_left,  # base points against the base cap
        }
        for r in rows
    ]


def _undoable_view(conn: psycopg.Connection, b: dict) -> list[dict[str, Any]]:
    """Releases the traveller may still take back: accepted, check-in open, inside the 1-minute window, and (for a
    seat) not yet taken by someone else. Seconds are real time, not the pinned demo clock."""
    if b["booking_status"] != "BOOKED" or b["checkin_opened_time_utc"] is None:
        return []
    rows = conn.execute(
        """SELECT t.transaction_id, t.benefit_id, t.perkflex_points_earned AS points, d.benefit_type, d.benefit_name,
                  d.seat_class, GREATEST(0, %(w)s - extract(epoch FROM now() - t.recorded_at))::int AS left_s,
                  EXISTS (SELECT 1 FROM dim_seat s WHERE s.freed_by_booking = t.booking_id AND s.reused_by_booking IS NOT NULL) AS taken
             FROM fact_perkflex_transaction t JOIN dim_benefit d USING (benefit_id)
            WHERE t.booking_id = %(b)s AND t.action_type = 'RELEASE' AND t.transaction_status = 'ACCEPTED'
              AND now() - t.recorded_at <= make_interval(secs => %(w)s)
            ORDER BY t.recorded_at DESC""",
        {"b": b["booking_id"], "w": UNDO_SECONDS},
    ).fetchall()
    out = []
    for r in rows:
        if r["benefit_type"] == "SEAT" and r["taken"]:
            continue
        key = "bag" if r["benefit_type"] == "BAG" else "seat" if r["benefit_type"] == "SEAT" else PERK_CODE[r["benefit_id"]]
        out.append({"benefit": key, "label": r["benefit_name"], "points": r["points"], "secondsLeft": r["left_s"]})
    return out


def _reuse_view(conn: psycopg.Connection, b: dict) -> dict[str, Any] | None:
    """What happened to what this traveller released.

    seat: the seat was freed, then taken by another booking or not yet.
    bag: how many other travellers added a bag on this flight after this traveller released one. That says the bag
    capacity is being used; it does not claim that one traveller's bag became another's.
    """
    row = conn.execute(
        """SELECT seat_number, freed_time_utc, reused_by_booking, reused_time_utc
             FROM dim_seat WHERE freed_by_booking = %s ORDER BY freed_time_utc DESC LIMIT 1""",
        (b["booking_id"],),
    ).fetchone()
    seat = (
        {
            "seat": row["seat_number"],
            "reused": row["reused_by_booking"] is not None,
            "freedAt": row["freed_time_utc"].isoformat() if row["freed_time_utc"] else None,
            "reusedAt": row["reused_time_utc"].isoformat() if row["reused_time_utc"] else None,
        }
        if row
        else None
    )
    bag = None
    mine = conn.execute(
        """SELECT t.recorded_at FROM fact_perkflex_transaction t JOIN dim_benefit d USING (benefit_id)
            WHERE t.booking_id = %s AND t.action_type = 'RELEASE' AND d.benefit_type = 'BAG'
              AND t.transaction_status IN ('ACCEPTED','SETTLED') ORDER BY t.recorded_at LIMIT 1""",
        (b["booking_id"],),
    ).fetchone()
    if mine:
        n = conn.execute(
            """SELECT count(DISTINCT t.booking_id) AS n
                 FROM fact_perkflex_transaction t JOIN dim_benefit d USING (benefit_id)
                 JOIN fact_booking o ON o.booking_id = t.booking_id
                WHERE o.flight_id = %s AND o.booking_id <> %s AND t.action_type = 'REDEEM' AND d.benefit_type = 'BAG'
                  AND t.transaction_status IN ('ACCEPTED','SETTLED') AND t.recorded_at > %s""",
            (b["flight_id"], b["booking_id"], mine["recorded_at"]),
        ).fetchone()["n"]
        bag = {"othersAdded": int(n)}
    if seat is None and bag is None:
        return None
    return {"seat": seat, "bag": bag}


def _notifications_view(
    wallets: dict[str, Any], booking: dict | None, ledger: list[dict[str, Any]], extra: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """In-app messages worked out from the traveller's own data each time, so they never go stale and are never stored.
    (Email or push would need a sender such as SES or SNS, which this project does not build.)"""
    out: list[dict[str, Any]] = []
    e = wallets["perkflex"]["expiring"]
    if e["soonPoints"] and e["soonDays"] is not None and e["soonDays"] <= EXPIRY_NOTIFY_DAYS:
        out.append(
            {
                "id": "expiry",
                "kind": "expiry",
                "text": f"{e['soonPoints']:,} PerkFlex points expire on {e['soonDate']}. Spend them on this trip to keep their value.",
            }
        )
    reuse = (booking or {}).get("reuse") or {}
    if reuse.get("seat") and reuse["seat"]["reused"]:
        out.append({"id": "seat-reused", "kind": "reuse", "text": f"Seat {reuse['seat']['seat']} that you released was taken by another traveller."})
    if reuse.get("bag") and reuse["bag"]["othersAdded"]:
        n = reuse["bag"]["othersAdded"]
        out.append({"id": "bag-used", "kind": "reuse", "text": f"{n} other traveller{'s' if n != 1 else ''} added a bag on your flight after you released yours."})
    posted = [x for x in ledger if x["kind"] == "release" and x["status"] == "posted"]
    if posted:
        out.append({"id": "posted", "kind": "posted", "text": f"{sum(x['points'] for x in posted):,} PerkFlex points from released benefits have posted to your wallet."})
    bonus = [x for x in ledger if x["kind"] == "bonus"]
    if bonus:
        out.append({"id": "bonus", "kind": "posted", "text": f"A completion bonus of {sum(x['points'] for x in bonus):,} PerkFlex points was added for completing your trip."})
    return out + (extra or [])


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
        "perks": _perks_view(conn, b["booking_id"], t.tier, b["flight_id"]),
        "undoable": _undoable_view(conn, b),
        "reuse": _reuse_view(conn, b),
        # What the traveller's benefits cover once check-in is open (the frontend no longer computes this).
        "checkinEntitlements": checkin_stage.model_dump(by_alias=True),
    }


def _ledger_view(conn: psycopg.Connection, passenger_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    # Releases: pending until a matching POST row exists.
    for r in conn.execute(
        """SELECT pt.point_transaction_id, pt.booking_id, pt.points_delta, pt.transaction_time_utc,
                  d.benefit_type, d.seat_class, d.benefit_name, d.cash_addon_cents,
                  EXISTS (SELECT 1 FROM fact_point_transaction x
                           WHERE x.source_point_transaction_id = pt.point_transaction_id
                             AND x.transaction_type = 'RELEASE_POST') AS posted,
                  b.confirmation_code
             FROM fact_point_transaction pt
             JOIN fact_perkflex_transaction t ON t.transaction_id = pt.perkflex_transaction_id
             JOIN dim_benefit d ON d.benefit_id = t.benefit_id
             JOIN fact_booking b ON b.booking_id = pt.booking_id
            WHERE pt.passenger_id = %s AND pt.transaction_type = 'RELEASE_PENDING'
              AND t.transaction_status <> 'VOID'""",
        (passenger_id,),
    ):
        if r["benefit_type"] == "BAG":
            label = "Unused checked-bag allowance"
        elif r["benefit_type"] == "PERK":
            label = f"Unused {r['benefit_name'].lower()}"
        else:
            label = f"{SEAT_NAMES[SEAT_FROM_DB[r['seat_class']]]} → Standard seat"
        entries.append(
            {
                "id": r["point_transaction_id"],
                "bookingId": r["confirmation_code"],
                "kind": "release",
                "wallet": "perkflex",
                "label": label,
                "cashValue": r["cash_addon_cents"] / 100,  # what the benefit costs if bought with cash
                "points": r["points_delta"],
                "status": "posted" if r["posted"] else "pending",
                "createdAt": r["transaction_time_utc"].isoformat(),
            }
        )
    # Redemptions: one entry per purchase, even when paid from two point balances.
    for r in conn.execute(
        """SELECT pt.perkflex_transaction_id, b.confirmation_code, sum(pt.points_delta) AS points,
                  COALESCE(-sum(pt.points_delta) FILTER (WHERE pt.point_type = 'PERKFLEX'), 0) AS paid_perkflex,
                  COALESCE(-sum(pt.points_delta) FILTER (WHERE pt.point_type = 'RAPID_REWARDS'), 0) AS paid_rapid,
                  max(pt.transaction_time_utc) AS at, d.benefit_type, d.seat_class, d.bag_ordinal, d.benefit_name,
                  d.cash_addon_cents
             FROM fact_point_transaction pt
             JOIN fact_perkflex_transaction t ON t.transaction_id = pt.perkflex_transaction_id
             JOIN dim_benefit d ON d.benefit_id = t.benefit_id
             JOIN fact_booking b ON b.booking_id = pt.booking_id
            WHERE pt.passenger_id = %s AND pt.transaction_type = 'BENEFIT_DEBIT'
            GROUP BY pt.perkflex_transaction_id, b.confirmation_code, d.benefit_type, d.seat_class, d.bag_ordinal,
                      d.benefit_name, d.cash_addon_cents""",
        (passenger_id,),
    ):
        if r["benefit_type"] == "BAG":
            label = f"Checked bag {r['bag_ordinal']}"
        elif r["benefit_type"] == "PERK":
            label = r["benefit_name"]
        else:
            label = f"{SEAT_NAMES[SEAT_FROM_DB[r['seat_class']]]} seat"
        entries.append(
            {
                "id": r["perkflex_transaction_id"],
                "bookingId": r["confirmation_code"],
                "kind": "redemption",
                "wallet": "both" if r["paid_perkflex"] and r["paid_rapid"] else "perkflex" if r["paid_perkflex"] else "rapid",
                "paidPerkflex": int(r["paid_perkflex"]),
                "paidRapid": int(r["paid_rapid"]),
                "label": label,
                "cashValue": r["cash_addon_cents"] / 100,
                "points": int(r["points"]),
                "status": "posted",
                "createdAt": r["at"].isoformat(),
            }
        )
    # Expired PerkFlex points.
    for r in conn.execute(
        """SELECT point_transaction_id, points_delta, transaction_time_utc FROM fact_point_transaction
            WHERE passenger_id = %s AND transaction_type = 'EXPIRY'""",
        (passenger_id,),
    ):
        entries.append(
            {
                "id": r["point_transaction_id"],
                "bookingId": "",
                "kind": "expiry",
                "wallet": "perkflex",
                "label": "Points expired (12 months)",
                "cashValue": 0,
                "points": r["points_delta"],
                "status": "posted",
                "createdAt": r["transaction_time_utc"].isoformat(),
            }
        )
    # Completion bonuses and gifts.
    labels = {"COMPLETION_BONUS": ("bonus", "Completion bonus"), "FLIGHT_AWARD": ("bonus", "Flight award"), "GIFT_IN": ("gift", "Gift received"), "GIFT_OUT": ("gift", "Gift given")}
    for r in conn.execute(
        """SELECT point_transaction_id, transaction_type, points_delta, transaction_time_utc, award_note FROM fact_point_transaction
            WHERE passenger_id = %s AND transaction_type IN ('COMPLETION_BONUS','FLIGHT_AWARD','GIFT_IN','GIFT_OUT')""",
        (passenger_id,),
    ):
        kind, label = labels[r["transaction_type"]]
        if r["award_note"]:
            label = f"{label} ({r['award_note']})"
        entries.append(
            {
                "id": r["point_transaction_id"],
                "bookingId": "",
                "kind": kind,
                "wallet": "perkflex",
                "label": label,
                "cashValue": 0,
                "points": r["points_delta"],
                "status": "posted",
                "createdAt": r["transaction_time_utc"].isoformat(),
            }
        )
    entries.sort(key=lambda e: e["createdAt"], reverse=True)
    return entries


def _earnings_view(conn: psycopg.Connection, passenger_id: str) -> list[dict[str, Any]]:
    """Rapid Rewards points for flying: their own wallet, kept apart from PerkFlex rewards (the `ledger`).

    Pending until the trip is completed. Points of a superseded booking were voided and are not shown.
    """
    entries: list[dict[str, Any]] = []
    for r in conn.execute(
        """SELECT pt.point_transaction_id, pt.points_delta, pt.transaction_time_utc, b.confirmation_code,
                  (SELECT x.transaction_type FROM fact_point_transaction x
                    WHERE x.source_point_transaction_id = pt.point_transaction_id LIMIT 1) AS child
             FROM fact_point_transaction pt JOIN fact_booking b ON b.booking_id = pt.booking_id
            WHERE pt.passenger_id = %s AND pt.transaction_type = 'FLIGHT_EARN_PENDING' AND pt.point_type = 'RAPID_REWARDS'""",
        (passenger_id,),
    ):
        if r["child"] not in (None, "FLIGHT_EARN_POST"):
            continue
        entries.append(
            {
                "id": r["point_transaction_id"],
                "bookingId": r["confirmation_code"],
                "label": "Points for flying",
                "points": r["points_delta"],
                "status": "posted" if r["child"] == "FLIGHT_EARN_POST" else "pending",
                "createdAt": r["transaction_time_utc"].isoformat(),
            }
        )
    entries.sort(key=lambda e: e["createdAt"], reverse=True)
    return entries


def expire_due(conn: psycopg.Connection, passenger_id: str, settings: Settings) -> int:
    """Takes expired PerkFlex points out of the wallet (12 months after they posted). Safe to repeat."""
    from ..db import atomic
    from .context import clock_now

    with atomic(conn):
        r = conn.execute("SELECT pf_expire_points(%s, %s) AS r", (passenger_id, clock_now(settings))).fetchone()["r"]
    return int(r.get("expired", 0))


def _expiring_view(conn: psycopg.Connection, passenger_id: str, settings: Settings) -> dict[str, Any]:
    from .context import clock_now

    now = clock_now(settings)
    lots = conn.execute("SELECT points, posted_at, expires_at FROM pf_expiry_lots(%s) ORDER BY expires_at", (passenger_id,)).fetchall()
    soon = [x for x in lots if (x["expires_at"] - now).days <= EXPIRY_SOON_DAYS]
    first = soon[0] if soon else None
    return {
        "soonPoints": sum(x["points"] for x in soon),
        "soonDate": first["expires_at"].date().isoformat() if first else None,
        "soonDays": max(0, (first["expires_at"] - now).days) if first else None,
        "lots": [{"points": x["points"], "expiresOn": x["expires_at"].date().isoformat()} for x in lots],
    }


def _status_view(t: TravellerInfo) -> dict[str, Any]:
    """Read-only 2027 status progress. Qualifying points here are invented for the demo."""
    names = [x[0] for x in TIER_STEPS]
    here = names.index(t.tier)
    nxt = TIER_STEPS[here + 1] if here + 1 < len(TIER_STEPS) else None
    return {
        "tier": t.tier,
        "tqp": t.tqp,
        "benefits": TIER_STEPS[here][2],
        "next": {"tier": nxt[0], "at": nxt[1], "remaining": max(0, nxt[1] - t.tqp)} if nxt else None,
        "milestones": [{"at": at, "reward": r, "reached": t.tqp >= at} for at, r in MILESTONES],
        "companionPass": "Companion Pass is earned through Rapid Rewards, outside check-in. Shown for context only.",
        "synthetic": True,
    }


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

    wallets = {
        "perkflex": {
            "available": t.pf_available,
            "pending": t.pf_pending,
            "expiring": _expiring_view(conn, passenger_id, settings),
        },
        "rapidRewards": {"available": t.rr_available, "pending": t.rr_pending},
    }
    ledger = _ledger_view(conn, passenger_id)
    policy = policy_view(conn)
    award = award_for(conn, row["flight_date"] if row else None)
    rewards = release_table(conn, passenger_id)
    prices = prices_view(conn, row["flight_id"] if row else None)
    group = group_view(conn, passenger_id)
    earnings = _earnings_view(conn, passenger_id)
    pending_flying = sum(e["points"] for e in earnings if e["status"] == "pending")
    status = _status_view(t)
    status["nudge"] = status_nudge(status, t, rewards, pending_flying)

    travellers = [profile_view(other) for other in load_travellers(conn)] if settings.demo_mode else []

    return {
        "profile": profile_view(t, _needs_from_booking(row) if row else None, trip=row is not None),
        "balance": t.balance,  # what can be spent: PerkFlex plus Rapid Rewards
        "pending": t.pf_pending,  # PerkFlex rewards waiting for the flight (kept for older callers)
        # The two wallets, never mixed. A buy uses PerkFlex first, then Rapid Rewards.
        "wallets": wallets,
        # What a release pays this traveller today: the policy's base reward plus their status bonus.
        "rewards": {
            "bonusPct": TIER_RELEASE_BONUS_PCT[t.tier],  # type: ignore[index]
            "bag": rewards["bag"],
            "preferred": rewards["preferred"],
            "extra": rewards["extra"],
            "mode": policy["mode"],
            "completionBonus": policy["completionBonus"],
            "flightAward": award["points"],
            "awardNote": award["note"],
        },
        # Points prices on this flight after any sale; `list` holds the normal prices.
        "prices": prices,
        "group": group,
        "payRapidFirst": t.rapid_first,  # the spend order: false = PerkFlex first
        "status": status,
        "promos": promos_view(conn),
        "booking": booking,
        "inventory": inventory,
        "ledger": ledger,  # PerkFlex rewards: releases and purchases
        "earnings": earnings,  # Rapid Rewards for flying
        "notifications": _notifications_view(
            wallets, booking, ledger, extra_alerts(booking, prices, t.balance, group)
        ),
        "travellers": travellers,
        "demo": settings.demo_mode,
        "notice": notice,
        "error": error,
    }
