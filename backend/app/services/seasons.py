"""Seasonal and festival PerkFlex: the flight award is multiplied by the airline's rule for the flight's date."""

from datetime import date
from typing import Any

import psycopg

from ..db import atomic


class SeasonError(Exception):
    """A refusal written for the airline user."""


def _fmt(multiplier: float) -> str:
    return f"{multiplier:g}"


def award_for(conn: psycopg.Connection, on: date | None) -> dict[str, Any]:
    """What a completed flight on this date earns in PerkFlex points, and why (the same numbers pf_complete_booking posts)."""
    base = conn.execute("SELECT flight_award FROM dim_reward_policy WHERE policy_id = 1").fetchone()["flight_award"]
    rule = conn.execute("SELECT multiplier, label FROM pf_season_award(%s)", (on,)).fetchone() if on else None
    mult = float(rule["multiplier"]) if rule and rule["multiplier"] is not None else 1.0
    label = rule["label"] if rule and mult > 1 else None
    return {
        "base": base,
        "points": round(base * mult),
        "multiplier": mult,
        "label": label,
        "note": f"{label} x{_fmt(mult)}" if label else None,
    }


def rules_view(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT r.rule_id, r.kind, r.name, r.start_date, r.end_date, r.multiplier,
                  (SELECT count(*) FROM fact_booking b JOIN dim_flight_schedule f USING (flight_id)
                    WHERE b.booking_status IN ('BOOKED','CHECKED_IN')
                      AND f.flight_date BETWEEN r.start_date AND r.end_date) AS bookings
             FROM dim_season_rule r WHERE r.active_flag ORDER BY r.start_date, r.rule_id"""
    ).fetchall()
    return [
        {
            "id": r["rule_id"],
            "kind": r["kind"],
            "name": r["name"],
            "start": r["start_date"].isoformat(),
            "end": r["end_date"].isoformat(),
            "multiplier": float(r["multiplier"]),
            "bookings": r["bookings"],  # open bookings on flights in this window: who the offer reaches today
        }
        for r in rows
    ]


def promos_view(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Active and upcoming boosts (up to 3, soonest first) for the promo strip. The rules decide; nothing is written by a model."""
    base = conn.execute("SELECT flight_award FROM dim_reward_policy WHERE policy_id = 1").fetchone()["flight_award"]
    rows = conn.execute(
        """SELECT kind, name, start_date, end_date, multiplier FROM dim_season_rule
            WHERE active_flag AND multiplier > 1 AND end_date >= CURRENT_DATE
            ORDER BY start_date, rule_id LIMIT 3"""
    ).fetchall()
    return [
        {
            "kind": r["kind"],
            "name": r["name"],
            "start": r["start_date"].isoformat(),
            "end": r["end_date"].isoformat(),
            "multiplier": float(r["multiplier"]),
            "points": round(base * float(r["multiplier"])),
        }
        for r in rows
    ]


def nearby_better(conn: psycopg.Connection, flight: dict[str, Any], current_points: int) -> dict[str, Any] | None:
    """A scheduled flight on the same route and number within two weeks that earns more PerkFlex points, if one exists.

    Only real scheduled flights are suggested; a date with no flight is never offered.
    """
    rows = conn.execute(
        """SELECT flight_id, flight_date FROM dim_flight_schedule
            WHERE flight_number = %s AND origin_airport = %s AND destination_airport = %s
              AND flight_status = 'SCHEDULED' AND flight_id <> %s
              AND flight_date BETWEEN %s::date - 14 AND %s::date + 14""",
        (flight["flight_number"], flight["origin_airport"], flight["destination_airport"], flight["flight_id"],
         flight["flight_date"], flight["flight_date"]),
    ).fetchall()
    best = None
    for r in rows:
        a = award_for(conn, r["flight_date"])
        if a["points"] > current_points and (best is None or a["points"] > best["points"]):
            best = {"date": r["flight_date"].isoformat(), "points": a["points"], "label": a["label"], "multiplier": a["multiplier"]}
    return best


def add_rule(conn: psycopg.Connection, who: str, kind: str, name: str, start: date, end: date, multiplier: float) -> None:
    from .controls import _audit

    name = " ".join(name.split())
    if not 2 <= len(name) <= 60:
        raise SeasonError("Give the rule a name of 2 to 60 characters.")
    if end < start:
        raise SeasonError("The end date must not be before the start date.")
    if (end - start).days > 120:
        raise SeasonError("A rule can cover at most 120 days.")
    if not 1 <= multiplier <= 3:
        raise SeasonError("The multiplier is between 1 and 3.")
    with atomic(conn):
        conn.execute(
            "INSERT INTO dim_season_rule (kind, name, start_date, end_date, multiplier, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
            (kind, name, start, end, round(multiplier, 1), who),
        )
        _audit(conn, who, f"{kind.lower()} rule", None, f"{name} {start} to {end} x{_fmt(multiplier)}")


def remove_rule(conn: psycopg.Connection, who: str, rule_id: int) -> None:
    from .controls import _audit

    with atomic(conn):
        row = conn.execute(
            "UPDATE dim_season_rule SET active_flag = false WHERE rule_id = %s AND active_flag RETURNING name, start_date, end_date",
            (rule_id,),
        ).fetchone()
        if row is None:
            raise SeasonError("That rule was not found.")
        _audit(conn, who, "rule removed", f"{row['name']} {row['start_date']} to {row['end_date']}", None)
