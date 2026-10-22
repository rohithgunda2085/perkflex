"""Operator commands.   cd backend && ../../.venv/bin/python -m app.cli <command>

  check                test the database connection
  inspect              list tables, columns and row counts (read only)
  migrate              apply pending SQL migrations
  seed-users [--reset] set passwords for accounts that still have the placeholder hash (or all, with --reset)
  demo-reset --yes     DESTRUCTIVE: drop every table in the demo schema, rebuild it from the migrations (fresh
                       seeded travellers, trips, wallets and ledger) and issue new demo passwords
"""

import argparse
import re
import sys
import time

from psycopg import sql

from .config import BACKEND, get_settings
from .db import connect
from .migrations import run_migrations
from .security.passwords import generate_demo_password, hash_password

PLACEHOLDER = "DEMO-HASH-REPLACE-AT-DEPLOY"
CREDENTIALS_FILE = BACKEND / "db" / "demo-credentials.local.md"


def cmd_check(_: argparse.Namespace) -> int:
    started = time.time()
    with connect() as conn:
        row = conn.execute(
            """SELECT version() AS version, current_database() AS db, current_user AS usr,
                      (SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()) AS ssl"""
        ).fetchone()
    print("Connected to Postgres")
    print(f"  database : {row['db']}\n  user     : {row['usr']}\n  TLS      : {'yes' if row['ssl'] else 'no'}")
    print(f"  server   : {row['version']}\n  latency  : {int((time.time() - started) * 1000)} ms (includes connect)")
    return 0


def cmd_inspect(_: argparse.Namespace) -> int:
    with connect() as conn:
        tables = conn.execute(
            """SELECT table_schema, table_name FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_type = 'BASE TABLE'
                ORDER BY 1, 2"""
        ).fetchall()
        for t in tables:
            ref = f'"{t["table_schema"]}"."{t["table_name"]}"'
            count = conn.execute(f"SELECT count(*) AS n FROM {ref}").fetchone()["n"]
            print(f"\n{t['table_schema']}.{t['table_name']}  rows: {count}")
            for c in conn.execute(
                """SELECT column_name, data_type, is_nullable FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position""",
                (t["table_schema"], t["table_name"]),
            ):
                print(f"  {c['column_name']:<30} {c['data_type']}{' NOT NULL' if c['is_nullable'] == 'NO' else ''}")
        fns = conn.execute(
            """SELECT routine_name FROM information_schema.routines
                WHERE routine_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1"""
        ).fetchall()
        print("\nFunctions:", ", ".join(f["routine_name"] for f in fns) or "none")
    return 0


def cmd_migrate(_: argparse.Namespace) -> int:
    with connect(autocommit=True) as conn:
        print(f"Target database: {conn.execute('SELECT current_database() AS d').fetchone()['d']}")
        run_migrations(conn)
    print("Migrations complete.")
    return 0


def cmd_seed_users(args: argparse.Namespace) -> int:
    with connect() as conn:
        rows = conn.execute(
            """SELECT u.user_id, u.login_id, u.user_role, p.passenger_name, u.password_hash
                 FROM dim_user_account u LEFT JOIN dim_passenger p USING (passenger_id) ORDER BY u.user_id"""
        ).fetchall()
        targets = [r for r in rows if args.reset or r["password_hash"] == PLACEHOLDER]
        if not targets:
            print("Nothing to do: every account already has a password. Use --reset to regenerate.")
            return 0
        issued = []
        for r in targets:
            password = generate_demo_password()
            conn.execute("UPDATE dim_user_account SET password_hash = %s WHERE user_id = %s", (hash_password(password), r["user_id"]))
            issued.append((r["login_id"], r["passenger_name"] or "Airline admin", r["user_role"], password))
        conn.commit()

    # Keep earlier accounts' passwords in the file; newly issued ones replace their own rows.
    lines: dict[str, str] = {}
    if CREDENTIALS_FILE.exists():
        for line in CREDENTIALS_FILE.read_text().splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 6 and cells[1] and cells[1] not in ("Username",) and not cells[1].startswith("---"):
                lines[cells[1]] = line
    for login, name, role, password in issued:
        lines[login] = f"| {login} | {name} | {role} | {password} |"
    body = ["# PerkFlex demo credentials (local only, do not commit)", "", "| Username | Name | Role | Password |", "| --- | --- | --- | --- |", *lines.values(), ""]
    CREDENTIALS_FILE.write_text("\n".join(body))
    CREDENTIALS_FILE.chmod(0o600)
    print(f"Updated {len(issued)} account(s). Saved to backend/db/demo-credentials.local.md")
    return 0


def cmd_demo_reset(args: argparse.Namespace) -> int:
    """Puts the demo back to its starting state. The ledger is append-only by design, so the only honest reset is to
    drop the schema and rebuild it. Guarded: it needs --yes, demo mode, and a named schema unless --allow-public."""
    settings = get_settings()
    if not args.yes:
        print("demo-reset deletes ALL data in the demo schema. Re-run with --yes to confirm.", file=sys.stderr)
        return 2
    if not settings.demo_mode:
        print("Refusing: DEMO_MODE is off. demo-reset only runs against a demo.", file=sys.stderr)
        return 2
    schema = settings.db_schema or "public"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", schema):
        print(f"Refusing: {schema!r} is not a plain schema name.", file=sys.stderr)
        return 2
    if schema == "public" and not args.allow_public:
        print(
            "Refusing to reset the 'public' schema. Set DB_SCHEMA to a schema used only for the demo, "
            "or pass --allow-public if this database holds nothing else.",
            file=sys.stderr,
        )
        return 2
    with connect(autocommit=True) as conn:
        db = conn.execute("SELECT current_database() AS d").fetchone()["d"]
        print(f"Resetting schema {schema!r} in database {db!r} ...")
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        run_migrations(conn)
    cmd_seed_users(argparse.Namespace(reset=True))
    print("Demo reset complete. New passwords are in backend/db/demo-credentials.local.md")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("inspect").set_defaults(func=cmd_inspect)
    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    seed = sub.add_parser("seed-users")
    seed.add_argument("--reset", action="store_true")
    seed.set_defaults(func=cmd_seed_users)
    reset = sub.add_parser("demo-reset")
    reset.add_argument("--yes", action="store_true", help="confirm that all data in the demo schema is deleted")
    reset.add_argument("--allow-public", action="store_true", help="allow resetting the 'public' schema")
    reset.set_defaults(func=cmd_demo_reset)
    args = parser.parse_args(argv)
    get_settings()
    try:
        return args.func(args)
    except Exception as error:  # operator-facing: print a clean message instead of a traceback
        print(f"{args.command} failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
