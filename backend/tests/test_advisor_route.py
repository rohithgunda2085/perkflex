"""The advisor's HTTP handlers without a database or the network: the route functions are called directly with the
traveller's state and the model replaced by a fake. (tests/test_api.py covers the same endpoints end to end.)"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.advisor.advisor import advise as real_advise
from app.advisor.agent import AdvisorResult
from app.advisor.types import AdviceRequest
from app.routes import advisor as route
from app.security.session import Session

from .advisor_support import state

SETTINGS = SimpleNamespace()


def session(user="U1", passenger="P1"):
    return Session(user_id=user, login_id="maya", passenger_id=passenger, profile_id="maya")


GOOD = {
    "summary": "You can earn points by releasing a seat you do not need.",
    "picks": [{"offerId": "RELEASE_SEAT", "why": "Earn 1,500 points, pending until you fly."}],
}


class Harness:
    """Replaces the connection and the state read, and records the order of events."""

    def __init__(self, st=None, missing=False):
        self.st, self.missing, self.events = st if st is not None else state(), missing, []

    @contextmanager
    def connection(self):
        self.events.append("open")
        try:
            yield object()
        finally:
            self.events.append("closed")

    def build_state(self, conn, passenger_id, settings):
        self.events.append(f"state:{passenger_id}")
        if self.missing:
            raise LookupError(passenger_id)
        return self.st

    def patches(self, agent=None):
        def fake_advise(ctx, body):
            self.events.append("model")
            return real_advise(ctx, body, agent) if agent else real_advise(ctx, body)

        return (
            patch.object(route, "request_connection", self.connection),
            patch.object(route, "build_state", self.build_state),
            patch.object(route, "advise", fake_advise),
        )


def call(harness, fn, *args, agent=None):
    a, b, c = harness.patches(agent)
    with a, b, c:
        return fn(*args)


def test_both_endpoints_are_registered():
    paths = {(next(iter(r.methods)), r.path) for r in route.router.routes}
    assert ("POST", "/api/assistant/perk-advice") in paths and ("GET", "/api/assistant/perk-nudge") in paths


def test_advice_is_returned_in_camel_case_with_the_rules_offers():
    route.advisor_limiter._hits.clear()
    h = Harness()
    body = call(h, route.perk_advice, AdviceRequest(message="backpack only"), session(), SETTINGS, agent=lambda inp: AdvisorResult(GOOD, 1))
    assert body["source"] == "ai" and body["picks"] == [{"offerId": "RELEASE_SEAT", "why": GOOD["picks"][0]["why"]}]
    assert [o["id"] for o in body["offers"]] == ["RELEASE_BAG", "RELEASE_SEAT", "REDEEM_BAG"]
    assert body["offers"][1]["points"] == 1500 and "shortfall" in body["offers"][2]


def test_the_database_connection_is_released_before_the_model_is_called():
    route.advisor_limiter._hits.clear()
    h = Harness()
    call(h, route.perk_advice, AdviceRequest(), session(), SETTINGS, agent=lambda inp: AdvisorResult(GOOD, 1))
    assert h.events == ["open", "state:P1", "closed", "model"]


def test_advice_is_for_the_signed_in_traveller_only():
    route.advisor_limiter._hits.clear()
    h = Harness()
    call(h, route.perk_advice, AdviceRequest(), session(passenger="P7"), SETTINGS, agent=lambda inp: AdvisorResult(GOOD, 1))
    assert "state:P7" in h.events  # the request body has no traveller field to choose another


def test_a_bad_model_answer_or_a_failing_model_still_returns_rules_only_advice():
    route.advisor_limiter._hits.clear()
    bad = {"summary": "Worth $50.", "picks": []}
    assert call(Harness(), route.perk_advice, AdviceRequest(), session(), SETTINGS, agent=lambda inp: AdvisorResult(bad, 1))["source"] == "fallback"

    def broken(inp):
        raise TimeoutError("bedrock down")

    assert call(Harness(), route.perk_advice, AdviceRequest(), session(), SETTINGS, agent=broken)["source"] == "fallback"


def test_no_model_call_when_check_in_is_closed():
    route.advisor_limiter._hits.clear()
    h = Harness(state(clock=False))

    def never(inp):
        raise AssertionError("model called")

    body = call(h, route.perk_advice, AdviceRequest(), session(), SETTINGS, agent=never)
    assert body["source"] == "fallback" and body["offers"] == [] and "not opened" in body["summary"]


def test_an_unknown_traveller_is_a_404():
    route.advisor_limiter._hits.clear()
    with pytest.raises(HTTPException) as e:
        call(Harness(missing=True), route.perk_advice, AdviceRequest(), session(), SETTINGS)
    assert e.value.status_code == 404


def test_advice_is_rate_limited_per_traveller():
    route.advisor_limiter._hits.clear()
    agent = lambda inp: AdvisorResult(GOOD, 1)  # noqa: E731
    for _ in range(12):
        call(Harness(), route.perk_advice, AdviceRequest(), session(), SETTINGS, agent=agent)
    with pytest.raises(HTTPException) as e:
        call(Harness(), route.perk_advice, AdviceRequest(), session(), SETTINGS, agent=agent)
    assert e.value.status_code == 429
    call(Harness(), route.perk_advice, AdviceRequest(), session(user="U2", passenger="P2"), SETTINGS, agent=agent)  # others unaffected


def test_the_nudge_is_a_rules_only_hint_in_camel_case():
    h = Harness()
    body = call(h, route.perk_nudge, session(), SETTINGS)
    assert body["nudge"]["offerId"] == "RELEASE_SEAT" and body["nudge"]["points"] == 1500
    assert "pending until you fly" in body["nudge"]["text"] and "model" not in h.events


def test_no_nudge_when_there_is_nothing_to_suggest_or_check_in_is_closed():
    assert call(Harness(state(clock=False)), route.perk_nudge, session(), SETTINGS) == {"nudge": None}
    assert call(Harness(state(seat_class="standard", entitled="standard", bags=0, balance=0)), route.perk_nudge, session(), SETTINGS) == {"nudge": None}


def test_the_nudge_needs_no_model_and_is_not_model_rate_limited():
    route.advisor_limiter._hits.clear()
    for _ in range(30):
        assert call(Harness(), route.perk_nudge, session(), SETTINGS)["nudge"] is not None
