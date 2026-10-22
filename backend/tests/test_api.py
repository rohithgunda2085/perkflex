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
    assert r.status_code == 200 and s["error"] is False and "1,040 points are pending" in s["notice"]
    assert client.get("/api/state").json()["pending"] == 1040  # committed (Platinum: 800 + 30% bonus), not just returned
    again = client.post("/api/actions", json={"type": "release", "benefit": "bag"}).json()
    assert again["error"] is True and "already accepted" in again["notice"] and again["pending"] == 1040


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


# ------------------------------------------------------------------ perk advisor endpoints (fake model: free, offline)
from app.advisor.advisor import advise as real_advise  # noqa: E402
from app.advisor.agent import AdvisorResult  # noqa: E402
from app.advisor.offers import build_context  # noqa: E402
from app.routes import advisor as advisor_route  # noqa: E402


def with_fake_advisor(monkeypatch, behaviour):
    monkeypatch.setattr(advisor_route, "advise", lambda ctx, body: real_advise(ctx, body, behaviour))
    advisor_route.advisor_limiter._hits.clear()


def start_check_in(client, login="kabir"):
    """Signs in and opens check-in (what visiting the Check in page does). Returns the advisor's view of the traveller."""
    sign_in(client, login)
    assert client.post("/api/actions", json={"type": "open-checkin"}).status_code == 200
    return build_context(client.get("/api/state").json())


def release_submission(offer):
    return {"summary": "Releasing it earns points.", "picks": [{"offerId": offer.id, "why": f"Earn {offer.points:,} points, pending until you fly."}]}


def test_the_advisor_endpoints_need_a_traveller_session(client):
    assert client.post("/api/assistant/perk-advice", json={}).status_code == 401
    assert client.get("/api/assistant/perk-nudge").status_code == 401
    sign_in(client, "airline")  # the airline account has no traveller view
    assert client.post("/api/assistant/perk-advice", json={}).status_code == 403
    assert client.get("/api/assistant/perk-nudge").status_code == 403


def test_the_advisor_answers_for_the_signed_in_traveller_and_the_offers_come_from_the_rules(client, monkeypatch):
    ctx = start_check_in(client)
    assert ctx.open and ctx.offers
    release = next(o for o in ctx.offers if o.kind == "release")
    with_fake_advisor(monkeypatch, lambda inp: AdvisorResult(release_submission(release), 1))
    body = client.post("/api/assistant/perk-advice", json={"message": "I only carry a backpack"}).json()
    assert body["source"] == "ai" and body["picks"][0]["offerId"] == release.id
    assert [o["id"] for o in body["offers"]] == [o.id for o in ctx.offers]
    assert next(o for o in body["offers"] if o["id"] == release.id)["points"] == release.points


def test_a_model_that_makes_up_numbers_or_offers_gets_rules_only_advice(client, monkeypatch):
    ctx = start_check_in(client)
    release = next(o for o in ctx.offers if o.kind == "release")
    bad = {"summary": "This is worth $50.", "picks": [{"offerId": release.id, "why": "Good value."}]}
    with_fake_advisor(monkeypatch, lambda inp: AdvisorResult(bad, 1))
    assert client.post("/api/assistant/perk-advice", json={}).json()["source"] == "fallback"

    def broken(inp):
        raise TimeoutError("bedrock down")

    with_fake_advisor(monkeypatch, broken)
    r = client.post("/api/assistant/perk-advice", json={})
    assert r.status_code == 200 and r.json()["source"] == "fallback"


def test_after_taking_a_release_the_advisor_no_longer_offers_one(client, monkeypatch):
    ctx = start_check_in(client)
    release = next(o for o in ctx.offers if o.kind == "release")
    benefit = "bag" if release.id == "RELEASE_BAG" else "seat"
    assert client.post("/api/actions", json={"type": "release", "benefit": benefit}).json()["error"] is False
    with_fake_advisor(monkeypatch, lambda inp: AdvisorResult(release_submission(release), 1))
    body = client.post("/api/assistant/perk-advice", json={}).json()
    assert not [o for o in body["offers"] if o["id"] in ("RELEASE_BAG", "RELEASE_SEAT")]  # the one rewarded release is used
    assert body["source"] == "fallback"  # and a model answer that picks one is refused


def test_the_nudge_is_rules_only_and_never_calls_the_model(client, monkeypatch):
    ctx = start_check_in(client)

    def never(c, body):
        raise AssertionError("model called")

    monkeypatch.setattr(advisor_route, "advise", never)
    body = client.get("/api/assistant/perk-nudge").json()
    assert set(body) == {"nudge"}
    if ctx.offers:
        n = body["nudge"]
        assert n is None or (n["offerId"] in [o.id for o in ctx.offers] and n["text"])


def test_the_nudge_is_empty_before_check_in_opens(client):
    sign_in(client, "neha")  # nothing has opened neha's check-in yet (the app does that when she visits Check in)
    booking = client.get("/api/state").json()["booking"]
    if booking is None or booking["clockAdvanced"]:
        pytest.skip("this traveller's check-in was already opened by another test")
    assert client.get("/api/assistant/perk-nudge").json() == {"nudge": None}


def test_the_advisor_is_rate_limited_and_rejects_bad_input(client, monkeypatch):
    ctx = start_check_in(client)
    release = next(o for o in ctx.offers if o.kind == "release")
    with_fake_advisor(monkeypatch, lambda inp: AdvisorResult(release_submission(release), 1))
    for bad in [{"message": "x" * 501}, {"extra": 1}, {"message": 5}]:
        assert client.post("/api/assistant/perk-advice", json=bad).status_code == 422
    codes = [client.post("/api/assistant/perk-advice", json={}).status_code for _ in range(13)]
    assert codes[:12] == [200] * 12 and codes[12] == 429


# ---- small perks (priority boarding, premium drink, priority lane) ----
def perks_by_id(client):
    return {p["id"]: p for p in client.get("/api/state").json()["booking"]["perks"]}


def test_state_reports_which_small_perks_the_fare_and_status_include(client):
    start_check_in(client, "kabir")  # Platinum
    perks = perks_by_id(client)
    assert set(perks) == {"boarding", "drink", "lane", "standby", "overweight", "meal"}
    assert perks["lane"]["included"] and perks["drink"]["included"] and perks["boarding"]["included"]
    assert perks["drink"]["releasePoints"] == 195  # 150 + 30% Platinum bonus and perks["lane"]["redeemPoints"] == 0


def test_a_small_release_is_pending_and_does_not_use_the_one_bag_or_seat_release(client):
    start_check_in(client, "kabir")
    first = client.post("/api/actions", json={"type": "release", "benefit": "drink"}).json()
    assert first["error"] is False and "195 points are pending" in first["notice"]
    assert first["pending"] == 195 and first["booking"]["released"] is False
    bag = client.post("/api/actions", json={"type": "release", "benefit": "bag"}).json()
    assert bag["error"] is False and bag["pending"] == 1235  # the bag-or-seat reward is still available
    again = client.post("/api/actions", json={"type": "release", "benefit": "drink"}).json()
    assert again["error"] is True and "already released" in again["notice"] and again["pending"] == 1235


def test_small_releases_stop_at_the_300_point_cap_and_the_page_hides_what_no_longer_fits(client):
    start_check_in(client, "kabir")  # Platinum (+30%): boarding 130 + drink 195 + lane 65; the 300 cap counts base points (100 + 150 + 50)
    for perk in ("boarding", "drink", "lane"):
        assert client.post("/api/actions", json={"type": "release", "benefit": perk}).json()["error"] is False
    state = client.get("/api/state").json()
    assert state["pending"] == 390 and perks_by_id(client)["standby"]["capRoom"] is False
    over = client.post("/api/actions", json={"type": "release", "benefit": "standby"}).json()
    assert over["error"] is True and "at most 300" in over["notice"] and over["pending"] == 390


def test_standby_and_the_overweight_allowance_can_be_bought(client):
    start_check_in(client, "ravi")  # Basic fare, no status
    bought = client.post("/api/actions", json={"type": "redeem", "benefit": "standby"}).json()
    assert bought["error"] is False and "1,800" in bought["notice"]
    assert perks_by_id(client)["standby"]["bought"] is True
    assert client.post("/api/actions", json={"type": "release", "benefit": "overweight"}).status_code == 422  # not releasable


def test_the_airport_meal_voucher_can_be_bought_but_not_released(client):
    start_check_in(client, "ravi")
    assert perks_by_id(client)["meal"]["included"] is False
    bought = client.post("/api/actions", json={"type": "redeem", "benefit": "meal"}).json()
    assert bought["error"] is False
    assert perks_by_id(client)["meal"]["bought"] is True
    assert client.post("/api/actions", json={"type": "release", "benefit": "meal"}).status_code == 422


# ---- undo, spend order, status, expiry ----
def test_a_release_can_be_undone_within_the_window_and_pending_points_go_back(client):
    start_check_in(client, "kabir")
    client.post("/api/actions", json={"type": "release", "benefit": "drink"})
    state = client.get("/api/state").json()
    undo = [u for u in state["booking"]["undoable"] if u["benefit"] == "drink"]
    assert undo and 0 < undo[0]["secondsLeft"] <= 60
    back = client.post("/api/actions", json={"type": "undo", "benefit": "drink"}).json()
    assert back["error"] is False and back["pending"] == 0 and "undone" in back["notice"].lower()
    assert not any(e["label"].lower().startswith("unused premium") for e in back["ledger"])  # the voided row is hidden
    assert perks_by_id(client)["drink"]["released"] is False
    again = client.post("/api/actions", json={"type": "undo", "benefit": "drink"}).json()
    assert again["error"] is True  # nothing left to undo


def test_the_spend_order_can_be_switched_to_rapid_rewards_first(client):
    start_check_in(client, "manish")  # 1,500 PerkFlex and 25,000 Rapid Rewards at the start
    s = client.post("/api/actions", json={"type": "payment-order", "rapidFirst": True}).json()
    assert s["error"] is False and s["payRapidFirst"] is True
    bought = client.post("/api/actions", json={"type": "redeem", "benefit": "boarding"}).json()
    assert bought["error"] is False and "900 Rapid Rewards" in bought["notice"] and "PerkFlex" not in bought["notice"].split("for")[-1]
    assert bought["wallets"]["perkflex"]["available"] == 1500


def test_state_has_status_and_expiring_points(client):
    sign_in(client, "manish")
    s = client.get("/api/state").json()
    assert s["status"]["synthetic"] is True and s["status"]["tier"] == "Member"
    assert [m["at"] for m in s["status"]["milestones"]] == [20000, 95000]
    exp = s["wallets"]["perkflex"]["expiring"]
    assert exp["soonPoints"] == 1500 and exp["soonDays"] is not None and exp["soonDays"] <= 60


def test_a_perk_the_traveller_lacks_is_bought_with_points_and_cannot_be_released(client):
    start_check_in(client, "ravi")  # Basic fare, no status: none of the three is included
    assert not any(p["included"] for p in perks_by_id(client).values())
    refused = client.post("/api/actions", json={"type": "release", "benefit": "drink"}).json()
    assert refused["error"] is True and "nothing to release" in refused["notice"]
    before = client.get("/api/state").json()["balance"]
    bought = client.post("/api/actions", json={"type": "redeem", "benefit": "drink"}).json()
    assert bought["error"] is False and "600 Rapid Rewards points" in bought["notice"] and bought["balance"] == before - 600
    assert perks_by_id(client)["drink"]["bought"] is True
    twice = client.post("/api/actions", json={"type": "redeem", "benefit": "drink"}).json()
    assert twice["error"] is True and twice["balance"] == before - 600
    assert client.post("/api/actions", json={"type": "redeem", "benefit": "lane"}).status_code == 422  # not for sale


# ---- demo reset ----
def test_demo_reset_needs_a_session_and_is_off_outside_demo_mode(client, monkeypatch):
    assert client.post("/api/demo/reset", json={}).status_code == 401
    sign_in(client, "kabir")
    monkeypatch.setenv("DEMO_MODE", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert client.post("/api/demo/reset", json={}).status_code == 404
    finally:
        monkeypatch.delenv("DEMO_MODE")
        get_settings.cache_clear()


def test_demo_reset_puts_trips_points_and_rewards_back_and_keeps_the_session(client):
    sign_in(client, "kabir")
    before = client.get("/api/state").json()
    assert client.post("/api/actions", json={"type": "open-checkin"}).status_code == 200
    assert client.post("/api/actions", json={"type": "release", "benefit": "drink"}).json()["pending"] == 195
    r = client.post("/api/demo/reset", json={})
    assert r.status_code == 200 and "Demo reset" in r.json()["notice"]
    after = client.get("/api/state").json()  # still signed in
    assert after["pending"] == before["pending"] == 0
    assert after["booking"]["clockAdvanced"] is False and after["ledger"] == before["ledger"]
    assert all(not p["released"] for p in after["booking"]["perks"])
    again = client.post("/api/actions", json={"type": "open-checkin"})  # and it can be played again
    assert again.status_code == 200


# ---- airline overview and wallet value ----
def test_the_airline_overview_is_for_the_airline_only(client):
    assert client.get("/api/admin/overview").status_code == 401
    sign_in(client, "kabir")
    assert client.get("/api/admin/overview").status_code == 403  # a traveller never sees programme totals
    assert client.get("/api/auth/me").json()["user"]["role"] == "PASSENGER"


def test_the_airline_sees_budget_owed_and_releases_per_flight(client):
    sign_in(client, "kabir")
    start_check_in(client, "kabir")
    assert client.post("/api/actions", json={"type": "release", "benefit": "bag"}).json()["error"] is False
    assert client.post("/api/actions", json={"type": "release", "benefit": "drink"}).json()["error"] is False
    sign_in(client, "airline")
    assert client.get("/api/auth/me").json()["user"]["role"] == "AIRLINE_ADMIN"
    body = client.get("/api/admin/overview").json()
    assert body["totals"]["owed"] >= 1235 and body["totals"]["releases"] >= 2
    flight = next(f for f in body["flights"] if f["releases"]["bag"] >= 1 and f["releases"]["perk"] >= 1)
    assert flight["reserved"] == flight["pointsEarned"] >= 1235
    assert flight["budget"] - flight["reserved"] - flight["settled"] == flight["remaining"]


def test_ledger_entries_carry_the_cash_value_of_the_benefit(client):
    start_check_in(client, "kabir")
    client.post("/api/actions", json={"type": "release", "benefit": "bag"})
    entry = client.get("/api/state").json()["ledger"][0]
    assert entry["kind"] == "release" and entry["cashValue"] == 45.0


# ---- two wallets ----
def test_state_keeps_the_two_wallets_apart_and_lists_flying_points_separately(client):
    sign_in(client, "kabir")
    s = client.get("/api/state").json()
    w = s["wallets"]
    assert set(w) == {"perkflex", "rapidRewards"} and set(w["perkflex"]) == {"available", "pending", "expiring"}
    assert s["balance"] == w["perkflex"]["available"] + w["rapidRewards"]["available"]
    assert s["pending"] == w["perkflex"]["pending"]  # PerkFlex only
    assert all("wallet" in e for e in s["ledger"])
    assert [e["label"] for e in s["earnings"]] == ["Points for flying"] and s["earnings"][0]["status"] == "pending"


def test_a_trade_goes_to_perkflex_and_flying_goes_to_rapid_rewards(client):
    start_check_in(client, "kabir")
    before = client.get("/api/state").json()["wallets"]
    client.post("/api/actions", json={"type": "release", "benefit": "bag"})
    mid = client.get("/api/state").json()["wallets"]
    assert mid["perkflex"]["pending"] == before["perkflex"]["pending"] + 1040
    assert mid["rapidRewards"] == before["rapidRewards"]  # trading never touches Rapid Rewards
    client.post("/api/actions", json={"type": "checkin"})
    done = client.post("/api/actions", json={"type": "complete"}).json()
    assert "+1,040 PerkFlex (released benefits)" in done["notice"] and "+50 PerkFlex (completion bonus)" in done["notice"]
    assert "Rapid Rewards (flying)" in done["notice"]
    after = done["wallets"]
    assert after["perkflex"]["available"] == before["perkflex"]["available"] + 1040 + 50 + 25  # the release, the completion bonus and the flight award
    assert after["rapidRewards"]["available"] > before["rapidRewards"]["available"]  # flying points posted there
    assert after["perkflex"]["pending"] == 0 and after["rapidRewards"]["pending"] == 0


def test_perkflex_points_that_posted_stay_in_the_wallet_for_the_next_trip(client):
    start_check_in(client, "kabir")
    client.post("/api/actions", json={"type": "release", "benefit": "bag"})
    client.post("/api/actions", json={"type": "checkin"})
    client.post("/api/actions", json={"type": "complete"})  # 1,040 PerkFlex now available
    sign_in(client, "kabir")
    w = client.get("/api/state").json()["wallets"]
    assert w["perkflex"]["available"] >= 1040


def test_the_fourth_undo_on_one_trip_is_refused(client):
    start_check_in(client, "kabir")
    for i in range(3):
        assert client.post("/api/actions", json={"type": "release", "benefit": "lane"}).json()["error"] is False
        assert client.post("/api/actions", json={"type": "undo", "benefit": "lane"}).json()["error"] is False
    client.post("/api/actions", json={"type": "release", "benefit": "lane"})
    last = client.post("/api/actions", json={"type": "undo", "benefit": "lane"}).json()
    assert last["error"] is True and "3 releases" in last["notice"]


def test_state_lists_notifications_for_points_about_to_expire(client):
    sign_in(client, "manish")  # 1,500 PerkFlex points expire 12 days after the demo clock
    notes = client.get("/api/state").json()["notifications"]
    assert any(n["kind"] == "expiry" and "1,500 PerkFlex points expire" in n["text"] for n in notes)


def test_the_airline_overview_flags_a_trip_that_undid_releases(client):
    start_check_in(client, "kabir")
    for _ in range(2):
        client.post("/api/actions", json={"type": "release", "benefit": "lane"})
        client.post("/api/actions", json={"type": "undo", "benefit": "lane"})
    client.post("/api/auth/logout")
    sign_in(client, "airline")
    flags = client.get("/api/admin/overview").json()["flags"]
    assert any(f["kind"] == "undo" and "Undid 2 releases" in f["text"] for f in flags)
    assert all(set(f) == {"kind", "booking", "flightId", "date", "text"} for f in flags)


def test_simulated_travellers_take_a_released_seat_then_add_a_bag(client):
    start_check_in(client, "leena")
    assert client.post("/api/actions", json={"type": "release", "benefit": "seat"}).json()["error"] is False
    first = client.post("/api/demo/simulate", json={}).json()
    assert "was given seat" in first["notice"] and first["booking"]["reuse"]["seat"]["reused"] is True
    assert any(n["id"] == "seat-reused" for n in first["notifications"])
    second = client.post("/api/demo/simulate", json={}).json()
    assert "added a checked bag" in second["notice"]
    undo = client.post("/api/actions", json={"type": "undo", "benefit": "seat"}).json()
    assert undo["error"] is True and "taken that seat" in undo["notice"]  # the seat is gone, so the release stays


def test_simulation_needs_a_session_and_is_off_outside_demo_mode(client, monkeypatch):
    assert client.post("/api/demo/simulate", json={}).status_code == 401
    sign_in(client, "kabir")
    monkeypatch.setenv("DEMO_MODE", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert client.post("/api/demo/simulate", json={}).status_code == 404
    finally:
        monkeypatch.delenv("DEMO_MODE")
        get_settings.cache_clear()


def test_the_airline_overview_has_a_with_and_without_model(client):
    sign_in(client, "airline")
    m = client.get("/api/admin/overview").json()["model"]
    assert m["without"] == {"rewardCost": 0, "seatResale": 0, "net": 0}
    assert set(m["with"]) == {"rewardCost", "seatResale", "net"} and len(m["assumptions"]) >= 3


# ---- email notifications (Amazon SES) ----
def test_email_settings_need_a_traveller_and_reject_a_bad_address(client):
    assert client.get("/api/me/email").status_code == 401
    sign_in(client, "maya")
    assert client.get("/api/me/email").json() == {"email": "", "verified": False, "enabled": False, "available": False}  # no SES in tests
    assert client.post("/api/me/email", json={"email": "not an email", "enabled": True}).status_code == 422


def test_a_new_address_starts_unconfirmed_and_the_confirm_link_works_once(client):
    sign_in(client, "maya")
    saved = client.post("/api/me/email", json={"email": "Maya@Example.com ", "enabled": True}).json()
    assert saved["email"] == "maya@example.com" and saved["verified"] is False and saved["enabled"] is True
    assert client.get("/api/email/confirm?token=short").status_code == 400
    assert client.get("/api/email/confirm?token=" + "x" * 43).status_code == 400  # unknown token
    cleared = client.post("/api/me/email", json={"email": "", "enabled": True}).json()
    assert cleared["email"] == "" and cleared["enabled"] is False
