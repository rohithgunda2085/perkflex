"""Queues mail. Called inside the same transaction as the action, so a rolled-back action sends nothing."""

import logging

import psycopg

from ..db import atomic
from .templates import body_text, subject_for

log = logging.getLogger("perkflex.email")

# Which actions send an email (the action's `type`), when the traveller has confirmed an address and turned it on.
EMAIL_KIND_BY_ACTION = {"book": "BOOKED", "release": "RELEASE", "redeem": "PURCHASE", "complete": "COMPLETE"}


def queue(conn: psycopg.Connection, passenger_id: str, kind: str, to: str, notice: str = "", link: str = "", dedupe_key: str | None = None) -> bool:
    """Adds one email. Returns False when it was a duplicate. Never raises: mail trouble must not undo an action."""
    try:
        with atomic(conn):  # a savepoint: a failure here rolls back only the email row
            row = conn.execute(
                """INSERT INTO fact_email_outbox (passenger_id, kind, to_address, subject, body_text, dedupe_key)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (dedupe_key) DO NOTHING RETURNING email_id""",
                (passenger_id, kind, to, subject_for(kind), body_text(kind, notice, link), dedupe_key),
            ).fetchone()
        return row is not None
    except Exception as error:  # noqa: BLE001
        log.warning("email.queue_failed %s", str(error)[:200])
        return False


def queue_for_traveller(conn: psycopg.Connection, passenger_id: str, kind: str, notice: str, dedupe_key: str | None) -> bool:
    """Queues an email only if the traveller has a confirmed address and has notifications turned on."""
    try:
        row = conn.execute(
            "SELECT email FROM dim_user_account WHERE passenger_id = %s AND email_verified_flag AND email_opt_in_flag AND email IS NOT NULL",
            (passenger_id,),
        ).fetchone()
    except Exception as error:  # noqa: BLE001
        log.warning("email.lookup_failed %s", str(error)[:200])
        return False
    return bool(row) and queue(conn, passenger_id, kind, row["email"], notice=notice, dedupe_key=dedupe_key)
