"""Creates (or drops) a throwaway, fully migrated schema for manual end-to-end runs, so the real data is never touched.

    cd backend && ../../.venv/bin/python scripts/e2e_schema.py create     # prints the schema name
    cd backend && ../../.venv/bin/python scripts/e2e_schema.py drop <name>

Every account in the new schema has the password PF-TEST-1234. Run the API against it with DB_SCHEMA=<name>.
"""

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.migrations import run_migrations  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402


def create() -> str:
    base = get_settings()
    schema = f"pf_e2e_{secrets.token_hex(4)}"
    with connect(base, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
    with connect(base.model_copy(update={"db_schema": schema}), autocommit=True) as conn:
        run_migrations(conn, log=lambda _: None)
        conn.execute("UPDATE dim_user_account SET password_hash = %s", (hash_password("PF-TEST-1234"),))
    return schema


def drop(schema: str) -> None:
    if not schema.startswith("pf_e2e_"):
        raise SystemExit("Refusing to drop a schema that this script did not create.")
    with connect(get_settings(), autocommit=True) as admin:
        admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "create":
        print(create())
    elif len(sys.argv) == 3 and sys.argv[1] == "drop":
        drop(sys.argv[2])
        print("dropped", sys.argv[2])
    else:
        raise SystemExit(__doc__)
