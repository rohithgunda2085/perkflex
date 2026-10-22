"""The airline's view: what the reward programme is costing and doing, flight by flight. Read only."""

from typing import Any

import psycopg

from ..rules.data import SEAT_CASH
from .mapping import SEAT_FROM_DB, flight_code

FLIGHTS_SQL = """
SELECT f.flight_id, f.flight_number, f.flight_date, f.origin_airport, f.destination_airport, f.flight_status,
       c.reward_budget_points AS budget, c.budget_reserved_points AS reserved, c.budget_settled_points AS settled,
       c.budget_remaining_points AS remaining, c.assumed_cost_per_point_cents AS cents_per_point,
       count(DISTINCT b.booking_id) AS bookings,
       count(DISTINCT b.booking_id) FILTER (WHERE b.booking_status IN ('CHECKED_IN','FLOWN')) AS checked_in
  FROM dim_flight_schedule f
  JOIN fact_flight_campaign c USING (flight_id)
  JOIN fact_booking b USING (flight_id)
 WHERE b.booking_status <> 'CANCELLED'
 GROUP BY f.flight_id, f.flight_number, f.flight_date, f.origin_airport, f.destination_airport, f.flight_status,
          c.reward_budget_points, c.budget_reserved_points, c.budget_settled_points, c.budget_remaining_points,
          c.assumed_cost_per_point_cents
 ORDER BY f.flight_date, f.flight_number, f.flight_id
"""

ACTIVITY_SQL = """
SELECT b.flight_id, d.benefit_type, t.action_type, count(*) AS n,
       COALESCE(sum(t.perkflex_points_earned), 0) AS earned,
       COALESCE(sum(t.perkflex_points_used), 0) AS spent_perkflex,
       COALESCE(sum(t.rapid_rewards_points_used), 0) AS spent_rapid
  FROM fact_perkflex_transaction t
  JOIN fact_booking b USING (booking_id)
  JOIN dim_benefit d USING (benefit_id)
 WHERE t.transaction_status IN ('ACCEPTED','SETTLED') AND t.action_type IN ('RELEASE','REDEEM')
 GROUP BY b.flight_id, d.benefit_type, t.action_type
"""

# Each benefit on each flight: how many were released and how many were bought (redeemed) with points.
BENEFITS_SQL = """
SELECT b.flight_id, d.benefit_id, d.benefit_name, d.benefit_type, t.action_type, count(*) AS n,
       COALESCE(sum(t.perkflex_points_earned), 0) AS earned,
       COALESCE(sum(t.perkflex_points_used), 0) + COALESCE(sum(t.rapid_rewards_points_used), 0) AS spent
  FROM fact_perkflex_transaction t
  JOIN fact_booking b USING (booking_id)
  JOIN dim_benefit d USING (benefit_id)
 WHERE t.transaction_status IN ('ACCEPTED','SETTLED') AND t.action_type IN ('RELEASE','REDEEM')
 GROUP BY b.flight_id, d.benefit_id, d.benefit_name, d.benefit_type, t.action_type
 ORDER BY b.flight_id, d.benefit_type, d.benefit_name
"""

# Rapid Rewards promised for flying (pending until flown). Not part of the reward budget: a separate wallet.
RAPID_SQL = """
SELECT b.flight_id, COALESCE(sum(pt.points_delta), 0) AS pending
  FROM fact_point_transaction pt JOIN fact_booking b USING (booking_id)
 WHERE pt.transaction_type = 'FLIGHT_EARN_PENDING' AND pt.point_type = 'RAPID_REWARDS'
   AND NOT EXISTS (SELECT 1 FROM fact_point_transaction x WHERE x.source_point_transaction_id = pt.point_transaction_id)
 GROUP BY b.flight_id
"""

# Seats given up by travellers, and how many of those were then taken by someone else.
SEAT_SQL = """
SELECT flight_id, count(*) FILTER (WHERE freed_by_booking IS NOT NULL OR reused_by_booking IS NOT NULL) AS freed,
       count(*) FILTER (WHERE reused_by_booking IS NOT NULL) AS reused
  FROM dim_seat GROUP BY flight_id
"""

# The benefits inventory pool, per flight. Seats by class: how many exist, how many are free to take now (never
# assigned, or given back), how many of those were given back by a traveller and are waiting for a buyer, and how many
# given-back seats another traveller has already taken. Bag grants come from the flight's campaign row.
POOL_SQL = """
SELECT flight_id, seat_type, count(*) AS total,
       count(*) FILTER (WHERE seat_status IN ('AVAILABLE','RELEASED')) AS free,
       count(*) FILTER (WHERE freed_by_booking IS NOT NULL AND reused_by_booking IS NULL
                         AND seat_status IN ('AVAILABLE','RELEASED')) AS given_back,
       count(*) FILTER (WHERE reused_by_booking IS NOT NULL) AS reused
  FROM dim_seat GROUP BY flight_id, seat_type
"""

BAGS_SQL = """
SELECT flight_id, bag_grants_total, bag_grants_remaining FROM fact_flight_campaign
"""

# Trips worth a second look. These are prompts for a person, never automatic penalties.
# 1. Several releases undone on one trip (the database stops the 4th).  2. A benefit released and then bought back
# on the same trip (a bag for a bag, a seat for a seat), which earns points for nothing.
FLAGS_SQL = """
SELECT 'UNDO' AS kind, b.confirmation_code, f.flight_number, f.flight_date, count(*) AS n, '' AS detail
  FROM fact_perkflex_transaction t
  JOIN fact_booking b USING (booking_id) JOIN dim_flight_schedule f ON f.flight_id = b.flight_id
 WHERE t.transaction_status = 'VOID' AND t.action_type = 'RELEASE'
 GROUP BY b.confirmation_code, f.flight_number, f.flight_date HAVING count(*) >= 2
UNION ALL
SELECT 'RELEASE_AND_BUY', b.confirmation_code, f.flight_number, f.flight_date, count(*), d.benefit_type
  FROM fact_booking b JOIN dim_flight_schedule f ON f.flight_id = b.flight_id
  JOIN fact_perkflex_transaction r ON r.booking_id = b.booking_id AND r.action_type = 'RELEASE'
       AND r.transaction_status IN ('ACCEPTED','SETTLED')
  JOIN dim_benefit d ON d.benefit_id = r.benefit_id AND d.benefit_type IN ('BAG','SEAT')
  JOIN fact_perkflex_transaction y ON y.booking_id = b.booking_id AND y.action_type = 'REDEEM'
       AND y.transaction_status IN ('ACCEPTED','SETTLED')
  JOIN dim_benefit e ON e.benefit_id = y.benefit_id AND e.benefit_type = d.benefit_type
 GROUP BY b.confirmation_code, f.flight_number, f.flight_date, d.benefit_type
 ORDER BY 3, 4, 2
"""

# Reused seats by the class of the seat that was given up (its list price is what resale is valued at).
SEAT_VALUE_SQL = """
SELECT flight_id, seat_type, count(*) AS n FROM dim_seat WHERE reused_by_booking IS NOT NULL GROUP BY flight_id, seat_type
"""

ASSUMPTIONS = [
    "A seat that another traveller takes is valued at its list add-on price (Standard $15, Preferred $35, Extra Legroom $80).",
    "Reward cost is the points owed and paid, at each flight's assumed cost per point.",
    "Released bags and small perks are not valued as revenue, so this is a cautious estimate.",
    "Without PerkFlex nothing is released, so neither the cost nor the resale exists.",
]

KIND = {"BAG": "bag", "SEAT": "seat", "PERK": "perk"}


def overview(conn: psycopg.Connection) -> dict[str, Any]:
    flights: dict[str, dict[str, Any]] = {}
    for r in conn.execute(FLIGHTS_SQL).fetchall():
        flights[r["flight_id"]] = {
            "flightId": flight_code(r["flight_number"]),
            "date": r["flight_date"].isoformat(),
            "from": r["origin_airport"],
            "to": r["destination_airport"],
            "status": r["flight_status"].lower(),
            "bookings": r["bookings"],
            "checkedIn": r["checked_in"],
            "budget": r["budget"],
            "reserved": r["reserved"],  # promised to travellers, posts after the flight
            "settled": r["settled"],  # already paid out
            "remaining": r["remaining"],
            "dollarsPerPoint": r["cents_per_point"] / 100,
            "releases": {"bag": 0, "seat": 0, "perk": 0},
            "pointsEarned": 0,
            "redemptions": {"bag": 0, "seat": 0, "perk": 0},
            "pointsSpent": 0,
            "pointsSpentPerkflex": 0,
            "pointsSpentRapid": 0,
            "rapidPending": 0,
            "seatsFreed": 0,
            "seatsReused": 0,
            "seatResale": 0,
        }
    for r in conn.execute(ACTIVITY_SQL).fetchall():
        f = flights.get(r["flight_id"])
        if f is None:
            continue
        kind = KIND[r["benefit_type"]]
        if r["action_type"] == "RELEASE":
            f["releases"][kind] += r["n"]
            f["pointsEarned"] += int(r["earned"])
        else:
            f["redemptions"][kind] += r["n"]
            f["pointsSpentPerkflex"] += int(r["spent_perkflex"])
            f["pointsSpentRapid"] += int(r["spent_rapid"])
            f["pointsSpent"] += int(r["spent_perkflex"]) + int(r["spent_rapid"])
    for r in conn.execute(RAPID_SQL).fetchall():
        if r["flight_id"] in flights:
            flights[r["flight_id"]]["rapidPending"] = int(r["pending"])

    for r in conn.execute(SEAT_SQL).fetchall():
        if r["flight_id"] in flights:
            flights[r["flight_id"]]["seatsFreed"] = int(r["freed"])
            flights[r["flight_id"]]["seatsReused"] = int(r["reused"])

    for r in conn.execute(SEAT_VALUE_SQL).fetchall():
        f = flights.get(r["flight_id"])
        if f is not None:
            f["seatResale"] = round(f.get("seatResale", 0) + r["n"] * SEAT_CASH[SEAT_FROM_DB[r["seat_type"]]], 2)  # type: ignore[index]

    per_benefit: dict[str, dict[str, dict[str, Any]]] = {}
    for r in conn.execute(BENEFITS_SQL).fetchall():
        if r["flight_id"] not in flights:
            continue
        row = per_benefit.setdefault(r["flight_id"], {}).setdefault(
            r["benefit_id"],
            {"name": r["benefit_name"], "kind": KIND[r["benefit_type"]], "released": 0, "bought": 0, "pointsEarned": 0, "pointsSpent": 0},
        )
        if r["action_type"] == "RELEASE":
            row["released"] += int(r["n"])
            row["pointsEarned"] += int(r["earned"])
        else:
            row["bought"] += int(r["n"])
            row["pointsSpent"] += int(r["spent"])
    for fid, f in flights.items():
        f["benefits"] = list(per_benefit.get(fid, {}).values())
    for f in flights.values():
        f["pool"] = {
            "seats": {k: {"total": 0, "free": 0, "givenBack": 0, "reused": 0} for k in ("standard", "preferred", "extra")},
            "bagGrants": {"total": 0, "remaining": 0},
        }
    for r in conn.execute(POOL_SQL).fetchall():
        f = flights.get(r["flight_id"])
        if f is not None:
            f["pool"]["seats"][SEAT_FROM_DB[r["seat_type"]]] = {
                "total": int(r["total"]),
                "free": int(r["free"]),
                "givenBack": int(r["given_back"]),
                "reused": int(r["reused"]),
            }
    for r in conn.execute(BAGS_SQL).fetchall():
        f = flights.get(r["flight_id"])
        if f is not None:
            f["pool"]["bagGrants"] = {"total": int(r["bag_grants_total"]), "remaining": int(r["bag_grants_remaining"])}

    flags = []
    for r in conn.execute(FLAGS_SQL).fetchall():
        if r["kind"] == "UNDO":
            text = f"Undid {r['n']} releases" + (" (the limit)" if r["n"] >= 3 else "")
        else:
            text = f"Released and then bought a {r['detail'].lower()} on the same trip"
        flags.append(
            {
                "kind": r["kind"].lower().replace("_", "-"),
                "booking": r["confirmation_code"],
                "flightId": flight_code(r["flight_number"]),
                "date": r["flight_date"].isoformat(),
                "text": text,
            }
        )

    rows = list(flights.values())
    reserved = sum(f["reserved"] for f in rows)
    settled = sum(f["settled"] for f in rows)
    cost = sum((f["reserved"] + f["settled"]) * f["dollarsPerPoint"] for f in rows)
    resale = round(sum(f["seatResale"] for f in rows), 2)
    cost_total = round(cost, 2)
    return {
        "model": {
            "with": {"rewardCost": cost_total, "seatResale": resale, "net": round(resale - cost_total, 2)},
            "without": {"rewardCost": 0, "seatResale": 0, "net": 0},
            "assumptions": ASSUMPTIONS,
        },
        "totals": {
            "flights": len(rows),
            "budget": sum(f["budget"] for f in rows),
            "owed": reserved,  # PerkFlex rewards: a liability until the flights are flown
            "paid": settled,
            "estimatedCost": round(cost, 2),
            "releases": sum(sum(f["releases"].values()) for f in rows),
            "redemptions": sum(sum(f["redemptions"].values()) for f in rows),
            "pointsSpent": sum(f["pointsSpent"] for f in rows),
            "pointsSpentPerkflex": sum(f["pointsSpentPerkflex"] for f in rows),
            "pointsSpentRapid": sum(f["pointsSpentRapid"] for f in rows),
            "seatsFreed": sum(f["seatsFreed"] for f in rows),
            "seatsReused": sum(f["seatsReused"] for f in rows),
            "rapidPending": sum(f["rapidPending"] for f in rows),  # owed for flying, separate from PerkFlex
        },
        "flights": rows,
        "flags": flags,
    }
