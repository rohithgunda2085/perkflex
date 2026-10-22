"""Passwords and session cookies, including compatibility with values produced by the earlier Node API (so existing password hashes and cookies keep working)."""

import base64
import json

import pytest

from app.config import Settings
from app.security import passwords, session

# Produced by the original Node implementation (since removed) with the secret below.
NODE_HASH = (
    "scrypt$16384$8$1$02d/7QAD5CA6YnF4a/CXNQ==$"
    "MUbEP8zEK4GwgNkJY6NTZKwAjGxTtXlUg9vQ46MyG3vAk+IZ2Q3R2Hyk1jf1WQ+s7x3AeHg0bMy+ax+driesag=="
)
NODE_SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef"
NODE_TOKEN = (
    "eyJ1c2VySWQiOiJVMDEiLCJsb2dpbklkIjoibWF5YSIsInBhc3NlbmdlcklkIjoiUDAxIiwicHJvZmlsZUlkIjoibWF5YSIsImV4cCI6MTc5MjYzMzg0Mn0"
    ".nscqWSbZj2kNv9Q07BRXo9uRf72iENqpzfnCPPwr5sA"
)
NODE_TOKEN_EXP = 1792633842
MAYA = session.Session(user_id="U01", login_id="maya", passenger_id="P01", profile_id="maya")


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(session, "get_settings", lambda: Settings(session_secret=NODE_SECRET))


# ---- passwords ----
def test_a_hash_made_by_node_verifies_in_python():
    assert passwords.verify_password("PF-TEST-1234", NODE_HASH)
    assert not passwords.verify_password("PF-TEST-1235", NODE_HASH)


def test_python_hashes_round_trip_and_are_salted():
    a, b = passwords.hash_password("PF-TEST-1234"), passwords.hash_password("PF-TEST-1234")
    assert a != b
    assert passwords.verify_password("PF-TEST-1234", a) and not passwords.verify_password("nope", a)
    assert a.startswith("scrypt$16384$8$1$")


@pytest.mark.parametrize(
    "stored",
    [
        "DEMO-HASH-REPLACE-AT-DEPLOY",  # the seed placeholder must never authenticate
        "",
        "scrypt$16384$8$1$onlyfive",
        "bcrypt$16384$8$1$AAAA$AAAA",
        "scrypt$notanumber$8$1$AAAA$AAAA",
        "scrypt$4294967296$8$1$AAAA$AAAA",  # absurd cost parameter is refused, not computed
        "scrypt$16384$8$1$!!!!$AAAA",
    ],
)
def test_malformed_or_placeholder_hashes_never_verify(stored):
    assert passwords.verify_password("DEMO-HASH-REPLACE-AT-DEPLOY", stored) is False


def test_demo_passwords_are_readable_and_random():
    pw = passwords.generate_demo_password()
    assert len(pw) == 12 and pw.startswith("PF-") and pw[7] == "-"
    assert pw != passwords.generate_demo_password()


# ---- sessions ----
def test_a_cookie_issued_by_node_is_accepted():
    got = session.read_token(NODE_TOKEN, now=NODE_TOKEN_EXP - 3600)
    assert got == MAYA


def test_a_node_cookie_expires():
    assert session.read_token(NODE_TOKEN, now=NODE_TOKEN_EXP + 1) is None


def test_round_trip_and_node_compatible_payload():
    token = session.create_token(MAYA, now=1_000_000)
    assert session.read_token(token, now=1_000_100) == MAYA
    body = token.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert set(payload) == {"userId", "loginId", "passengerId", "profileId", "exp"}  # same keys Node writes


def test_tampering_is_rejected():
    token = session.create_token(MAYA, now=1_000_000)
    body, sig = token.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"userId": "U10", "loginId": "airline", "passengerId": None, "profileId": None, "exp": 9_999_999_999}).encode()).rstrip(b"=").decode()
    assert session.read_token(f"{forged}.{sig}", now=1_000_100) is None  # valid signature of a different body
    assert session.read_token(f"{body}.{sig[:-2]}AA", now=1_000_100) is None
    assert session.read_token(body, now=1_000_100) is None
    assert session.read_token("", now=1_000_100) is None and session.read_token(None) is None


def test_a_token_signed_with_another_secret_is_rejected(monkeypatch):
    token = session.create_token(MAYA, now=1_000_000)
    monkeypatch.setattr(session, "get_settings", lambda: Settings(session_secret="x" * 40))
    assert session.read_token(token, now=1_000_100) is None


def test_a_short_secret_is_refused(monkeypatch):
    monkeypatch.setattr(session, "get_settings", lambda: Settings(session_secret="short"))
    with pytest.raises(RuntimeError):
        session.create_token(MAYA)
