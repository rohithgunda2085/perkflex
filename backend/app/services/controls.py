"""Airline controls: the reward policy and points sales. Every change is written to fact_policy_audit."""

from typing import Any

import psycopg

from ..db import atomic
from .extras import SALE_KEYS, SALE_NAMES, policy_view
from .mapping import flight_code
from .seasons import rules_view


class ControlError(Exception):
    """A refusal written for the airline user."""


def controls_view(conn: psycopg.Connection) -> dict[str, Any]:
    flights = conn.execute(
        "SELECT flight_id, flight_number, flight_date, origin_airport, destination_airport FROM dim_flight_schedule ORDER BY flight_date, flight_id"
    ).fetchall()
    sales = conn.execute(
        "SELECT flight_id, benefit_key, discount_pct, set_by, set_at FROM fact_price_sale ORDER BY set_at DESC"
    ).fetchall()
    audit = conn.execute(
        "SELECT changed_at, changed_by, setting, old_value, new_value FROM fact_policy_audit ORDER BY audit_id DESC LIMIT 10"
    ).fetchall()
    return {
        "policy": policy_view(conn),
        "seasonRules": rules_view(conn),
        "flights": [
            {
                "id": f["flight_id"],
                "label": f"{flight_code(f['flight_number'])} {f['origin_airport']} → {f['destination_airport']}, {f['flight_date'].isoformat()}",
            }
            for f in flights
        ],
        "benefits": [{"key": k, "name": SALE_NAMES[k]} for k in SALE_KEYS],
        "sales": [
            {"flightId": s["flight_id"], "benefit": s["benefit_key"], "discountPct": s["discount_pct"], "setBy": s["set_by"], "at": s["set_at"].isoformat()}
            for s in sales
        ],
        "audit": [
            {"at": a["changed_at"].isoformat(), "by": a["changed_by"], "setting": a["setting"], "from": a["old_value"], "to": a["new_value"]}
            for a in audit
        ],
    }


def _audit(conn: psycopg.Connection, who: str, setting: str, old: object, new: object) -> None:
    conn.execute(
        "INSERT INTO fact_policy_audit (changed_by, setting, old_value, new_value) VALUES (%s, %s, %s, %s)",
        (who, setting, None if old is None else str(old), None if new is None else str(new)),
    )


def update_policy(
    conn: psycopg.Connection,
    who: str,
    *,
    mode: str | None = None,
    value_percent: int | None = None,
    cents_per_point: float | None = None,
    completion_bonus: int | None = None,
) -> None:
    with atomic(conn):
        old = policy_view(conn)
        changes = {
            "release_mode": (mode, old["mode"]),
            "value_percent": (value_percent, old["valuePercent"]),
            "cents_per_point": (cents_per_point, old["centsPerPoint"]),
            "completion_bonus": (completion_bonus, old["completionBonus"]),
        }
        for column, (new, previous) in changes.items():
            if new is None or new == previous:
                continue
            conn.execute(f"UPDATE dim_reward_policy SET {column} = %s, updated_at = now() WHERE policy_id = 1", (new,))  # noqa: S608 (fixed names)
            _audit(conn, who, column, previous, new)


def set_sale(conn: psycopg.Connection, who: str, flight_id: str, benefit: str, discount_pct: int) -> str:
    """discount_pct 0 ends the sale. Returns a sentence for the airline user."""
    if benefit not in SALE_KEYS:
        raise ControlError("Unknown benefit.")
    if conn.execute("SELECT 1 FROM dim_flight_schedule WHERE flight_id = %s", (flight_id,)).fetchone() is None:
        raise ControlError("Unknown flight.")
    with atomic(conn):
        old = conn.execute(
            "SELECT discount_pct FROM fact_price_sale WHERE flight_id = %s AND benefit_key = %s", (flight_id, benefit)
        ).fetchone()
        if discount_pct == 0:
            conn.execute("DELETE FROM fact_price_sale WHERE flight_id = %s AND benefit_key = %s", (flight_id, benefit))
        else:
            conn.execute(
                """INSERT INTO fact_price_sale (flight_id, benefit_key, discount_pct, set_by) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (flight_id, benefit_key) DO UPDATE SET discount_pct = EXCLUDED.discount_pct,
                     set_by = EXCLUDED.set_by, set_at = now()""",
                (flight_id, benefit, discount_pct, who),
            )
        _audit(conn, who, f"sale {flight_id} {benefit}", f"{old['discount_pct']}%" if old else None, f"{discount_pct}%" if discount_pct else "ended")
    return f"{SALE_NAMES[benefit]} sale {'ended' if discount_pct == 0 else f'set to {discount_pct}% off'} on {flight_id}."
