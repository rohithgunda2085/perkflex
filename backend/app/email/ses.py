"""Sends queued mail through Amazon SES and keeps the outbox honest (sent, retry later, or failed for good)."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from ..config import Settings
from ..db import request_connection
from .templates import body_html

log = logging.getLogger("perkflex.email")
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (60, 300, 900, 3600)  # after the 1st, 2nd, 3rd, 4th failure


def backoff(attempts: int) -> int:
    """Seconds to wait before the next try, after `attempts` failures."""
    return BACKOFF_SECONDS[min(max(attempts, 1), len(BACKOFF_SECONDS)) - 1]


def ses_client(settings: Settings) -> Any:
    import boto3

    return boto3.client("sesv2", region_name=settings.aws_region)


def send_one(client: Any, settings: Settings, row: dict) -> None:
    """One SES call. Raises on any failure."""
    params: dict[str, Any] = {
        "FromEmailAddress": settings.email_from,
        "Destination": {"ToAddresses": [row["to_address"]]},
        "Content": {
            "Simple": {
                "Subject": {"Data": row["subject"], "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": row["body_text"], "Charset": "UTF-8"},
                    "Html": {"Data": body_html(row["body_text"]), "Charset": "UTF-8"},
                },
            }
        },
    }
    if settings.email_configuration_set:
        params["ConfigurationSetName"] = settings.email_configuration_set
    client.send_email(**params)


def deliver(rows: list[dict], send: Callable[[dict], None]) -> list[tuple[int, str | None]]:
    """Tries each row. Returns (email_id, error) pairs: error is None when it was sent."""
    out: list[tuple[int, str | None]] = []
    for row in rows:
        try:
            send(row)
            out.append((row["email_id"], None))
        except Exception as error:  # noqa: BLE001
            out.append((row["email_id"], str(error)[:300] or error.__class__.__name__))
    return out


def run_once(settings: Settings, client: Any | None = None, limit: int = 10) -> int:
    """Sends up to `limit` due emails. Safe to run on several tasks at once (rows are locked with SKIP LOCKED)."""
    if not (settings.email_enabled and settings.email_from):
        return 0
    client = client or ses_client(settings)
    with request_connection() as conn:
        rows = conn.execute(
            """SELECT email_id, to_address, subject, body_text, attempts FROM fact_email_outbox
                WHERE status = 'PENDING' AND next_attempt_utc <= now()
                ORDER BY email_id LIMIT %s FOR UPDATE SKIP LOCKED""",
            (limit,),
        ).fetchall()
        attempts = {r["email_id"]: r["attempts"] for r in rows}
        results = deliver(rows, lambda r: send_one(client, settings, r))
        for email_id, error in results:
            if error is None:
                conn.execute("UPDATE fact_email_outbox SET status='SENT', attempts=attempts+1, sent_time_utc=now(), last_error=NULL WHERE email_id=%s", (email_id,))
                continue
            n = attempts[email_id] + 1
            if n >= MAX_ATTEMPTS:
                conn.execute("UPDATE fact_email_outbox SET status='FAILED', attempts=%s, last_error=%s WHERE email_id=%s", (n, error, email_id))
            else:
                conn.execute(
                    "UPDATE fact_email_outbox SET attempts=%s, last_error=%s, next_attempt_utc=now()+make_interval(secs => %s) WHERE email_id=%s",
                    (n, error, backoff(n), email_id),
                )
            log.warning("email.send_failed id=%s attempt=%s", email_id, n)
    return sum(1 for _, e in results if e is None)


async def worker_loop(settings: Settings, every_seconds: float = 10.0) -> None:
    """Background loop started with the API when email is enabled. It never stops on an error."""
    while True:
        try:
            await asyncio.to_thread(run_once, settings)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            log.warning("email.worker_error %s", str(error)[:200])
        await asyncio.sleep(every_seconds)
