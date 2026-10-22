"""The HTTP API end to end, against its own throwaway schema (these tests commit)."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import close_pool
from app.main import app
from app.routes.auth import failed_logins

from .conftest import TEST_PASSWORD, throwaway_schema

pytestmark = pytest.mark.db

ROUTE = {"from": "DAL", "to": "DEN"}


@pytest.fixture(scope="module")
def api_schema():
    with throwaway_schema() as settings:
        yield settings


@pytest.fixture
def client(api_schema, monkeypatch):
    monkeypatch.setenv("DB_SCHEMA", api_schema.db_schema)
    get_settings.cache_clear()
    close_pool()
    failed_logins._hits.clear()
    with TestClient(app) as c:
        yield c
    close_pool()
    get_settings.cache_clear()


def sign_in(client, login="maya", password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"loginId": login, "password": password})


# ------------------------------------------------------------------ sign-in and sessions
def test_the_api_is_reachable_and_unauthenticated_calls_are_rejected(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/quotes", json={"flightId": "WN2418"}).status_code == 401
    assert client.post("/api/actions", json={"type": "checkin"}).status_code == 401
    assert client.get("/api/state").json() == {"error": "Please sign in again."}


def test_signing_in_sets_a_locked_down_cookie(client):
    r = sign_in(client)
    assert r.status_code == 200 and r.json()["user"]["profileId"] == "maya"
    cookie = r.headers["set-cookie"]
    assert "pf_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert client.get("/api/auth/me").json()["user"]["loginId"] == "maya"


def test_wrong_passwords_get_one_generic_answer(client):
    for login, pw in [("maya", "nope"), ("nobody", TEST_PASSWORD)]:
        r = sign_in(client, login, pw)
        assert r.status_code == 401 and r.json() == {"error": "The username or password is incorrect. Please try again."}
        assert "set-cookie" not in r.headers


def test_repeated_failures_are_blocked_but_other_users_are_not(client):
    for _ in range(10):
        assert sign_in(client, "neha", "bad").status_code == 401
    assert sign_in(client, "neha", TEST_PASSWORD).status_code == 429  # even the right password waits
    assert sign_in(client, "ravi").status_code == 200


def test_a_forged_or_tampered_cookie_is_rejected(client):
    sign_in(client)
    token = client.cookies.get("pf_session")
    client.cookies.set("pf_session", token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB"))
    assert client.get("/api/state").status_code == 401
    client.cookies.set("pf_session", "e30.AAAA")
    assert client.get("/api/auth/me").status_code == 401


def test_signing_out_clears_the_cookie(client):
    sign_in(client)
    r = client.post("/api/auth/logout")
    assert r.status_code == 200 and "pf_session=" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    assert client.get("/api/state").status_code == 401


def test_the_airline_admin_has_no_traveller_view(client):
    assert sign_in(client, "airline").status_code == 200
    assert client.get("/api/state").status_code == 403


# ------------------------------------------------------------------ state, quotes, actions
def test_state_is_the_signed_in_travellers_own(client):
    sign_in(client, "leena")
    s = client.get("/api/state").json()
    assert s["profile"]["id"] == "leena" and s["profile"]["tier"] == "Gold"
    assert s["booking"]["seatClass"] == "extra" and s["booking"]["bags"] == 2
    assert set(s) >= {"profile", "balance", "pending", "booking", "inventory", "ledger", "travellers", "demo", "notice", "error"}


def test_quotes_are_priced_by_the_server_for_this_traveller(client):
    sign_in(client, "maya")
    r = client.post("/api/quotes", json={**ROUTE, "flightId": "WN2418", "date": "2027-12-16", "needs": {"seat": "extra", "refund": True}})
    body = r.json()
    assert r.status_code == 200 and body["best"] == "extra"
    assert next(q for q in body["quotes"] if q["fare"] == "extra")["total"] == 282.6
    assert body["flight"] == {"id": "WN2418", "date": "2027-12-16", "from": "DAL", "to": "DEN"}
    assert set(body["entitlements"]) == {"basic", "choice", "preferred", "extra"}
    assert body["entitlements"]["extra"]["bags"] == 2 and "flexible" in body["entitlements"]["basic"]


def test_quotes_clamp_hostile_needs_and_reject_unknown_flights(client):
    sign_in(client, "maya")
    r = client.post("/api/quotes", json={**ROUTE, "flightId": "WN2418", "needs": {"bags": 999, "budget": -5, "seat": "<script>"}})
    assert r.status_code == 200 and r.json()["needs"]["bags"] == 3 and r.json()["needs"]["budget"] == 100
    assert client.post("/api/quotes", json={**ROUTE, "flightId": "WN9999"}).status_code == 422
    assert client.post("/api/quotes", json={**ROUTE, "flightId": "WN2418; DROP TABLE x"}).status_code == 422
    assert client.post("/api/quotes", json={"flightId": "WN2418"}).status_code == 422  # the route is required
    assert client.post("/api/quotes", json={**ROUTE, "from": "dal'; --", "flightId": "WN2418"}).status_code == 422


def test_quotes_follow_the_route_and_use_that_flights_seats(client):
    sign_in(client, "maya")
    r = client.post("/api/quotes", json={"flightId": "WN968", "from": "LAS", "to": "PHX", "date": "2027-12-16", "needs": {}})
    assert r.status_code == 200
    assert r.json()["flight"] == {"id": "WN968", "date": "2027-12-16", "from": "LAS", "to": "PHX"}
    assert client.post("/api/quotes", json={"flightId": "WN968", "from": "XXX", "to": "PHX", "needs": {}}).status_code == 404


def test_an_action_changes_state_and_the_change_is_still_there_on_the_next_request(client):
    sign_in(client, "kabir")  # Kabir: Platinum covers 3 bags, he brings 2
    r = client.post("/api/actions", json={"type": "release", "benefit": "bag"})
    s = r.json()
    assert r.status_code == 200 and s["error"] is False and "800 points are pending" in s["notice"]
    assert client.get("/api/state").json()["pending"] == 800  # committed, not just returned
    again = client.post("/api/actions", json={"type": "release", "benefit": "bag"}).json()
    assert again["error"] is True and "already accepted" in again["notice"] and again["pending"] == 800


def test_unknown_or_hostile_actions_are_rejected_without_echoing_input(client):
    sign_in(client, "sara")
    for bad in [{"type": "nope"}, {"type": "bags", "count": 99}, {"type": "checkin", "profileId": "alex"}, {"type": "release", "benefit": "<img onerror=x>"}]:
        r = client.post("/api/actions", json=bad)
        assert r.status_code == 422 and r.json()["error"] == "Invalid request."
        assert "<img" not in r.text and "alex" not in r.text


def test_a_traveller_cannot_act_for_someone_else(client):
    sign_in(client, "alex")
    s = client.post("/api/actions", json={"type": "redeem", "benefit": "bag"}).json()  # Alex has 0 points
    assert s["error"] is True and s["profile"]["id"] == "alex"
    assert client.post("/api/actions", json={"type": "redeem", "benefit": "bag", "profileId": "kabir"}).status_code == 422


def test_a_new_traveller_can_book_through_the_api(client):
    sign_in(client, "michael.rankin")
    assert client.get("/api/state").json()["booking"] is None
    body = {"type": "book", "fare": "basic", "flightId": "WN2418", "from": "DAL", "to": "DEN", "date": "2027-12-16", "needs": {}}
    s = client.post("/api/actions", json=body).json()
    assert s["error"] is False and s["booking"]["status"] == "booked" and s["profile"]["hasTrip"] is True


def test_oversized_bodies_are_refused(client):
    sign_in(client, "maya")
    r = client.post("/api/quotes", content=b"x" * 20000, headers={"content-type": "application/json"})
    assert r.status_code == 413


# ------------------------------------------------------------------ demo switch
def test_the_demo_switch_moves_to_another_traveller(client):
    sign_in(client, "maya")
    r = client.post("/api/demo/switch", json={"profileId": "kabir"})
    assert r.status_code == 200
    assert client.get("/api/state").json()["profile"]["id"] == "kabir"
    assert client.post("/api/demo/switch", json={"profileId": "airline"}).status_code == 404
    assert client.post("/api/demo/switch", json={"profileId": "nobody"}).status_code == 404


def test_the_demo_switch_needs_a_session_and_is_off_outside_demo_mode(client, monkeypatch):
    assert client.post("/api/demo/switch", json={"profileId": "kabir"}).status_code == 401
    sign_in(client, "maya")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    assert client.post("/api/demo/switch", json={"profileId": "kabir"}).status_code == 404
    assert client.get("/api/state").json()["travellers"] == []


# ------------------------------------------------------------------ assistant endpoint (fake model: free, offline)
from app.assistant.agent import AgentResult  # noqa: E402
from app.assistant.best_fare import best_fare as real_best_fare  # noqa: E402
from app.routes import assistant as assistant_route  # noqa: E402


def with_fake_model(monkeypatch, behaviour):
    monkeypatch.setattr(assistant_route, "best_fare", lambda ctx, body: real_best_fare(ctx, body, behaviour))
    assistant_route.assistant_limiter._hits.clear()


GOOD = {
    "needs": {"bags": 0, "seat": "extra", "refund": True, "flexible": False, "seatNow": False, "early": False, "budget": 450},
    "fare": "extra",
    "reasons": ["Refundable with Extra Legroom."],
    "explanation": "Choice Extra fits at $282.60.",
}
ASK = {**ROUTE, "flightId": "WN2418", "needs": GOOD["needs"], "date": "2027-12-16"}


def test_the_assistant_needs_a_session(client):
    assert client.post("/api/assistant/best-fare", json=ASK).status_code == 401


def test_the_assistant_answers_and_every_number_comes_from_the_engine(client, monkeypatch):
    with_fake_model(monkeypatch, lambda inp: AgentResult(GOOD, 1))
    sign_in(client, "maya")
    body = client.post("/api/assistant/best-fare", json=ASK).json()
    assert body["source"] == "ai" and body["recommendation"]["fare"] == "extra" and body["recommendation"]["total"] == 282.6
    assert [q["fare"] for q in body["quotes"]] == ["basic", "choice", "preferred", "extra"]
    assert body["understood"]["seat"] == "extra"


def test_a_bad_model_answer_falls_back_to_the_rules(client, monkeypatch):
    with_fake_model(monkeypatch, lambda inp: AgentResult({**GOOD, "explanation": "Only $1.00!"}, 1))
    sign_in(client, "maya")
    body = client.post("/api/assistant/best-fare", json=ASK).json()
    assert body["source"] == "fallback" and body["recommendation"]["total"] == 282.6


def test_a_failing_model_does_not_break_the_endpoint(client, monkeypatch):
    def broken(inp):
        raise TimeoutError("bedrock down")

    with_fake_model(monkeypatch, broken)
    sign_in(client, "maya")
    r = client.post("/api/assistant/best-fare", json=ASK)
    assert r.status_code == 200 and r.json()["source"] == "fallback"


def test_the_assistant_is_rate_limited_per_traveller(client, monkeypatch):
    with_fake_model(monkeypatch, lambda inp: AgentResult(GOOD, 1))
    sign_in(client, "maya")
    codes = [client.post("/api/assistant/best-fare", json=ASK).status_code for _ in range(13)]
    assert codes[:12] == [200] * 12 and codes[12] == 429
    client.post("/api/auth/logout")
    sign_in(client, "ravi")
    assert client.post("/api/assistant/best-fare", json=ASK).status_code == 200  # another traveller is unaffected


def test_the_assistant_rejects_bad_input(client, monkeypatch):
    with_fake_model(monkeypatch, lambda inp: AgentResult(GOOD, 1))
    sign_in(client, "maya")
    for bad in [{"flightId": "WN9999"}, {"flightId": "x; DROP TABLE"}, {**ASK, "message": "x" * 501}, {**ASK, "extra": 1}, {}]:
        assert client.post("/api/assistant/best-fare", json=bad).status_code in (400, 422)
