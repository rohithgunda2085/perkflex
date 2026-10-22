"""PostgreSQL access: one shared connection pool, plus a plain connection helper for scripts and tests.

Services take an open connection and never commit. The caller owns the transaction: the API opens one per
request (committed on success, rolled back on error), and tests roll back after every test.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import DEFAULT_CA, Settings, get_settings

_pool: ConnectionPool | None = None


def conninfo(settings: Settings) -> dict:
    missing = [n for n in ("db_host", "db_name", "db_user", "db_password") if not getattr(settings, n)]
    if missing:
        raise RuntimeError(
            f"Missing database settings: {', '.join(m.upper() for m in missing)}. Copy .env.example to .env and fill it in."
        )
    mode = settings.db_ssl.strip() or "verify"
    if mode == "verify":
        ssl = {"sslmode": "verify-full", "sslrootcert": settings.db_ssl_ca or str(DEFAULT_CA)}
    elif mode == "no-verify":
        ssl = {"sslmode": "require"}
    elif mode == "disable":
        ssl = {"sslmode": "disable"}
    else:
        raise RuntimeError(f"DB_SSL must be verify, no-verify or disable (got {mode!r}).")
    info = {
        "host": settings.db_host,
        "port": settings.db_port,
        "dbname": settings.db_name,
        "user": settings.db_user,
        "password": settings.db_password,
        "connect_timeout": 10,
        "application_name": "perkflex-api",
        **ssl,
    }
    if settings.db_schema:
        info["options"] = f"-c search_path={settings.db_schema}"
    return info


def connect(settings: Settings | None = None, autocommit: bool = False) -> psycopg.Connection:
    """A standalone connection (scripts and tests). With autocommit off, commit or roll back yourself."""
    return psycopg.connect(**conninfo(settings or get_settings()), row_factory=dict_row, autocommit=autocommit)


def open_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            kwargs={**conninfo(settings), "row_factory": dict_row},
            min_size=1,
            max_size=settings.db_pool_max,
            open=False,
            # A connection can be dropped by RDS or a network blip while idle; check it before handing it out.
            check=ConnectionPool.check_connection,
        )
        _pool.open(wait=False)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def atomic(conn: psycopg.Connection) -> Iterator[None]:
    """All-or-nothing block that never commits on its own.

    psycopg's transaction() commits when it is the outermost block. Services must not commit (the request or the
    test owns the transaction), so open the outer transaction first and let this block be a savepoint.
    """
    if conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE:
        conn.execute("SELECT 1")
    with conn.transaction():
        yield


@contextmanager
def request_connection() -> Iterator[psycopg.Connection]:
    """One transaction per API request: commits when the block ends normally, rolls back on any exception."""
    with open_pool().connection(timeout=15) as conn:
        yield conn
