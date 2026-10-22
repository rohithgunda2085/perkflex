"""Round 6 views and helpers: reward policy, sale prices, travel groups, gifts, status nudge.

Everything here is worked out from the database on each request (nothing is stored for the view), the same way the
notifications are.
"""

from typing import Any

import psycopg

from ..rules.data import TIER_FLYING_BONUS_PCT, TIER_RELEASE_BONUS_PCT, with_bonus
from .context import TravellerInfo

SALE_KEYS = ("bag", "preferred", "extra", "boarding", "drink", "standby", "overweight")
SALE_NAMES = {
    "bag": "Checked bag",
    "preferred": "Preferred seat",
    "extra": "Extra Legroom seat",
    "boarding": "Priority boarding",
    "drink": "Premium drink",
    "standby": "Same-day standby",
    "overweight": "Overweight bag allowance",
}
GIFT_MIN, GIFT_MAX, GIFT_DAILY = 100, 2000, 3000  # pf_gift_points enforces the same numbers
GROUP_MAX = 6


def policy_view(conn: psycopg.Connection) -> dict[str, Any]:
    r = conn.execute("SELECT * FROM dim_reward_policy WHERE policy_id = 1").fetchone()
    return {
        "mode": r["release_mode"],
        "valuePercent": r["value_percent"],
        "centsPerPoint": float(r["cents_per_point"]),
        "completionBonus": r["completion_bonus"],
    }


def release_table(conn: psycopg.Connection, passenger_id: str) -> dict[str, int]:
    """What a release pays this traveller today (policy and status bonus included), straight from the database."""
    r = conn.execute(
        """SELECT pf_release_points(%(p)s, 'BAG1') AS bag, pf_release_points(%(p)s, 'SEAT_PREF') AS preferred,
                  pf_release_points(%(p)s, 'SEAT_XL') AS extra,
                  pf_release_base('BAG1') AS bag_base, pf_release_base('SEAT_PREF') AS preferred_base,
                  pf_release_base('SEAT_XL') AS extra_base""",
        {"p": passenger_id},
    ).fetchone()
    return {k: int(v) for k, v in r.items()}


def prices_view(conn: psycopg.Connection, flight_id: str | None) -> dict[str, Any]:
    """Points prices on this flight, after any sale. `sales` maps a benefit key to its discount percent."""
    f = flight_id or ""
    r = conn.execute(
        """SELECT pf_redeem_price(%(f)s, 'BAG1') AS bag1, pf_redeem_price(%(f)s, 'BAG2') AS bag2,
                  pf_redeem_price(%(f)s, 'SEAT_PREF') AS preferred, pf_redeem_price(%(f)s, 'SEAT_XL') AS extra""",
        {"f": f},
    ).fetchone()
    lst = conn.execute(
        """SELECT max(perkflex_redeem_points) FILTER (WHERE benefit_id = 'BAG1') AS bag1,
                  max(perkflex_redeem_points) FILTER (WHERE benefit_id = 'BAG2') AS bag2,
                  max(perkflex_redeem_points) FILTER (WHERE benefit_id = 'SEAT_PREF') AS preferred,
                  max(perkflex_redeem_points) FILTER (WHERE benefit_id = 'SEAT_XL') AS extra FROM dim_benefit"""
    ).fetchone()
    sales = {
        s["benefit_key"]: s["discount_pct"]
        for s in conn.execute("SELECT benefit_key, discount_pct FROM fact_price_sale WHERE flight_id = %s", (f,)).fetchall()
    }
    return {**{k: int(v) for k, v in r.items()}, "list": {k: int(v) for k, v in lst.items()}, "sales": sales}


def status_nudge(status: dict[str, Any], t: TravellerInfo, rewards: dict[str, int], pending_flying: int) -> dict[str, Any] | None:
    """What the next status level would be worth to this traveller on their next trip."""
    nxt = status.get("next")
    if not nxt:
        return None
    tier = nxt["tier"]
    cur_fly = TIER_FLYING_BONUS_PCT[t.tier]  # type: ignore[index]
    fly_base = round(pending_flying * 100 / (100 + cur_fly)) if pending_flying else 0
    return {
        "tier": tier,
        "remaining": nxt["remaining"],
        "near": nxt["remaining"] <= 20000,
        "releaseBonusPct": TIER_RELEASE_BONUS_PCT[tier],  # type: ignore[index]
        "flyingBonusPct": TIER_FLYING_BONUS_PCT[tier],  # type: ignore[index]
        "bagNow": rewards["bag"],
        "bagNext": with_bonus(rewards["bag_base"], TIER_RELEASE_BONUS_PCT[tier]),  # type: ignore[index]
        "flyingNow": pending_flying,
        "flyingNext": with_bonus(fly_base, TIER_FLYING_BONUS_PCT[tier]) if fly_base else 0,  # type: ignore[index]
    }


def group_view(conn: psycopg.Connection, passenger_id: str) -> dict[str, Any]:
    """The traveller's travel group, invitations, recent gifts, and what they may still give today."""
    mine = conn.execute(
        "SELECT group_id FROM fact_group_member WHERE passenger_id = %s AND status = 'ACTIVE'", (passenger_id,)
    ).fetchone()
    members: list[dict[str, Any]] = []
    pending: list[str] = []
    if mine:
        rows = conn.execute(
            """SELECT g.passenger_id, g.status, p.passenger_name, p.tier_status, u.login_id,
                      bk.booking_status, bk.reward_release_used_flag, bk.flight_date, bk.origin_airport,
                      bk.destination_airport, bk.flight_number
                 FROM fact_group_member g
                 JOIN dim_passenger p ON p.passenger_id = g.passenger_id
                 JOIN dim_user_account u ON u.passenger_id = g.passenger_id
                 LEFT JOIN LATERAL (
                      SELECT b.booking_status, b.reward_release_used_flag, f.flight_date, f.origin_airport,
                             f.destination_airport, f.flight_number
                        FROM fact_booking b JOIN dim_flight_schedule f USING (flight_id)
                       WHERE b.passenger_id = g.passenger_id AND b.booking_status <> 'CANCELLED'
                       ORDER BY (b.booking_status = 'FLOWN'), b.booking_date_utc DESC LIMIT 1) bk ON true
                WHERE g.group_id = %s ORDER BY (g.group_id = g.passenger_id) DESC, p.passenger_name""",
            (mine["group_id"],),
        ).fetchall()
        for r in rows:
            if r["status"] == "INVITED":
                pending.append(r["passenger_name"])
                continue
            members.append(
                {
                    "id": r["login_id"],
                    "name": r["passenger_name"],
                    "tier": {"NONE": "Member", "SILVER": "Silver", "GOLD": "Gold", "PLATINUM": "Platinum"}[r["tier_status"]],
                    "you": r["passenger_id"] == passenger_id,
                    "organiser": r["passenger_id"] == mine["group_id"],
                    "trip": (
                        {
                            "route": f"{r['origin_airport']} → {r['destination_airport']}",
                            "date": r["flight_date"].isoformat(),
                            "status": r["booking_status"],
                            "released": bool(r["reward_release_used_flag"]),
                        }
                        if r["booking_status"]
                        else None
                    ),
                }
            )
    invites = [
        {"group": r["login_id"], "from": r["passenger_name"]}
        for r in conn.execute(
            """SELECT u.login_id, p.passenger_name FROM fact_group_member g
                 JOIN dim_passenger p ON p.passenger_id = g.group_id
                 JOIN dim_user_account u ON u.passenger_id = g.group_id
                WHERE g.passenger_id = %s AND g.status = 'INVITED' ORDER BY g.invited_at""",
            (passenger_id,),
        ).fetchall()
    ]
    gifts = [
        {
            "direction": "out" if r["from_passenger"] == passenger_id else "in",
            "other": r["other_name"],
            "points": r["points"],
            "at": r["recorded_at"].isoformat(),
        }
        for r in conn.execute(
            """SELECT g.from_passenger, g.points, g.recorded_at,
                      p.passenger_name AS other_name
                 FROM fact_gift g
                 JOIN dim_passenger p ON p.passenger_id = CASE WHEN g.from_passenger = %(p)s THEN g.to_passenger ELSE g.from_passenger END
                WHERE g.from_passenger = %(p)s OR g.to_passenger = %(p)s ORDER BY g.recorded_at DESC LIMIT 6""",
            {"p": passenger_id},
        ).fetchall()
    ]
    given = int(
        conn.execute(
            "SELECT COALESCE(sum(points), 0) AS n FROM fact_gift WHERE from_passenger = %s AND recorded_at > now() - interval '24 hours'",
            (passenger_id,),
        ).fetchone()["n"]
    )
    received_lock = bool(
        conn.execute(
            "SELECT EXISTS (SELECT 1 FROM fact_gift WHERE to_passenger = %s AND recorded_at > now() - interval '24 hours') AS x",
            (passenger_id,),
        ).fetchone()["x"]
    )
    return {
        "inGroup": mine is not None,
        "organiser": bool(mine and mine["group_id"] == passenger_id),
        "members": members,
        "pendingInvites": pending,
        "invites": invites,
        "gifts": gifts,
        "limits": {
            "min": GIFT_MIN,
            "max": GIFT_MAX,
            "daily": GIFT_DAILY,
            "givenToday": given,
            "left": max(0, GIFT_DAILY - given),
            "locked": received_lock,  # points received in the last 24 hours cannot be passed on yet
            "groupMax": GROUP_MAX,
        },
    }


def extra_alerts(
    booking: dict[str, Any] | None, prices: dict[str, Any], balance: int, group: dict[str, Any]
) -> list[dict[str, Any]]:
    """Notifications for round 6: points sales on this flight, group invitations, gifts just received."""
    out: list[dict[str, Any]] = []
    for inv in group["invites"]:
        out.append({"id": f"invite-{inv['group']}", "kind": "group", "text": f"{inv['from']} invited you to a travel group."})
    recent_in = [g for g in group["gifts"] if g["direction"] == "in"][:1]
    for g in recent_in:
        out.append({"id": "gift-in", "kind": "gift", "text": f"{g['other']} gave you {g['points']:,} PerkFlex points."})
    if not booking or booking["status"] == "flown":
        return out
    sales: dict[str, int] = prices.get("sales", {})
    perks = {p["id"]: p for p in booking.get("perks", [])}
    rank = {"standard": 0, "preferred": 1, "extra": 2}
    for key, pct in sales.items():
        if not pct or key not in SALE_NAMES:
            continue
        if key in ("preferred", "extra"):
            if rank[booking["seatClass"]] >= rank[key]:
                continue
            now_price, list_price = prices[key], prices["list"][key]
        elif key == "bag":
            slot = "bag1" if booking["bags"] == 0 else "bag2"
            now_price, list_price = prices[slot], prices["list"][slot]
        else:
            perk = perks.get(key)
            if not perk or perk["included"] or perk["bought"]:
                continue
            now_price, list_price = perk["redeemPoints"], perk["listPoints"]
        gap = max(0, now_price - balance)
        tail = "You have enough points." if gap == 0 else f"You need {gap:,} more points."
        out.append(
            {
                "id": f"drop-{key}",
                "kind": "price-drop",
                "text": f"Sale: {SALE_NAMES[key]} is {pct}% off on your flight, {now_price:,} points instead of {list_price:,}. {tail}",
            }
        )
    return out
