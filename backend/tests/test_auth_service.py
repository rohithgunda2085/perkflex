import pytest

from app.services.auth import authenticate, user_by_login

from .conftest import TEST_PASSWORD

pytestmark = pytest.mark.db


def test_a_traveller_signs_in_and_last_login_is_recorded(conn):
    user = authenticate(conn, "maya", TEST_PASSWORD)
    assert user and user.passenger_id == "P01" and user.profile_id == "maya" and user.name == "Maya Patel"
    assert conn.execute("SELECT last_login_time_utc AS t FROM dim_user_account WHERE login_id = 'maya'").fetchone()["t"]


def test_login_ids_are_case_and_space_insensitive(conn):
    assert authenticate(conn, "  Michael.Rankin ", TEST_PASSWORD).passenger_id == "P18"


@pytest.mark.parametrize("login,password", [("maya", "wrong"), ("nobody", TEST_PASSWORD), ("maya", ""), ("", "")])
def test_bad_credentials_return_nothing(conn, login, password):
    assert authenticate(conn, login, password) is None


def test_the_airline_admin_signs_in_but_has_no_traveller_profile(conn):
    admin = authenticate(conn, "airline", TEST_PASSWORD)
    assert admin and admin.role == "AIRLINE_ADMIN" and admin.profile_id is None


def test_a_deactivated_account_cannot_sign_in(conn):
    conn.execute("UPDATE dim_user_account SET is_active_flag = false WHERE login_id = 'ravi'")
    assert authenticate(conn, "ravi", TEST_PASSWORD) is None
    assert user_by_login(conn, "ravi") is None


def test_the_seed_placeholder_hash_never_authenticates(conn):
    conn.execute("UPDATE dim_user_account SET password_hash = 'DEMO-HASH-REPLACE-AT-DEPLOY' WHERE login_id = 'neha'")
    assert authenticate(conn, "neha", "DEMO-HASH-REPLACE-AT-DEPLOY") is None
