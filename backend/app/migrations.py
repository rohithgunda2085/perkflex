"""Applies backend/db/sql/*.sql in order, recording each file in schema_migrations (shared with the Node runner).

Files 01-03 are the original schema, seed and functions; 10 and up are additive migrations. Files 04-06 use
psql-only commands and are not applied here. Each file is sent as one multi-statement query, so it is atomic:
either the whole file applies or none of it does.
"""

import re
from collections.abc import Callable

import psycopg

from .config import SQL_DIR

MIGRATION = re.compile(r"^(0[1-3]|[1-9]\d)_.*\.sql$")


def migration_files() -> list[str]:
    return sorted(p.name for p in SQL_DIR.iterdir() if MIGRATION.match(p.name))


def run_migrations(conn: psycopg.Connection, log: Callable[[str], None] = print) -> list[str]:
    """Applies pending migrations. `conn` must be in autocommit mode. Returns the files applied."""
    if not conn.autocommit:
        raise ValueError("run_migrations needs an autocommit connection (files manage their own transactions)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
             filename   text PRIMARY KEY,
             applied_at timestamptz NOT NULL DEFAULT now())"""
    )
    applied = {r["filename"] for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()}

    # Refuse to layer a fresh schema on top of tables this runner did not create.
    if not applied and conn.execute("SELECT to_regclass('dim_passenger') AS t").fetchone()["t"]:
        raise RuntimeError(
            "Tables already exist in this database but were not created by the migration runner. "
            "Point DB_NAME at an empty database, or drop the existing tables first."
        )

    done: list[str] = []
    for name in migration_files():
        if name in applied:
            log(f"skip   {name} (already applied)")
            continue
        conn.execute((SQL_DIR / name).read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (name,))
        log(f"apply  {name}")
        done.append(name)
    return done
