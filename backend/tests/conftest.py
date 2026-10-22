"""Shared fixtures.

Database tests (marked `db`) create a throwaway schema on the database from .env, apply every migration into it,
and drop it at the end. Each test then runs inside a transaction that is rolled back, so tests never see each
other's changes and your real data is never touched. HTTP tests commit for real, so they get a schema of their own.
"""

import secrets
from contextlib import contextmanager

import pytest

from app.config import get_settings
from app.db import connect
from app.migrations import run_migrations
from app.security.passwords import hash_password

TEST_PASSWORD = "PF-TEST-1234"


def pytest_collection_modifyitems(config, items):
    settings = get_settings()
    configured = all([settings.db_host, settings.db_name, settings.db_user, settings.db_password])
    if configured:
        return
    skip = pytest.mark.skip(reason="database settings are not configured in .env")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@contextmanager
def throwaway_schema():
    """Settings pointing at a fresh, fully migrated schema (every account's password is TEST_PASSWORD)."""
    base = get_settings()
    schema = f"pf_test_{secrets.token_hex(4)}"
    admin = connect(base, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    settings = base.model_copy(update={"db_schema": schema})
    try:
        with connect(settings, autocommit=True) as migrating:
            run_migrations(migrating, log=lambda _: None)
            migrating.execute("UPDATE dim_user_account SET password_hash = %s", (hash_password(TEST_PASSWORD),))
        yield settings
    finally:
        admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        admin.close()


@pytest.fixture(scope="session")
def test_settings():
    with throwaway_schema() as settings:
        yield settings


@pytest.fixture(scope="session")
def _shared_connection(test_settings):
    # One connection for the whole run: opening a TLS connection to RDS from a laptop costs seconds.
    connection = connect(test_settings)
    yield connection
    connection.close()


@pytest.fixture
def conn(_shared_connection):
    """A connection inside the throwaway schema; everything done with it is rolled back after the test."""
    _shared_connection.rollback()
    yield _shared_connection
    _shared_connection.rollback()
