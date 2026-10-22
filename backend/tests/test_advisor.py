"""The check-in perk advisor without a database or the network: a fake model drives the real loop, validator and
fallback, and the offers are computed from hand-built state dictionaries shaped like GET /api/state."""

from unittest.mock import patch

import pytest

from app.advisor import tools as advisor_tools
from app.advisor.advisor import (
    AdviceRejected,
    advise,
    allowed_points,
    clean,
    deterministic_advice,
    validate_submission,
)
from app.advisor.agent import AdvisorInput, AdvisorResult, run_advisor
from app.advisor.offers import build_context
from app.advisor.types import AdviceRequest
from app.rules.data import REDEEM_POINTS, RELEASE_POINTS

from .advisor_support import state


def ids(ctx):
    return [o.id for o in ctx.offers]


def request(message=None):
    return AdviceRequest(message=message)


# ------------------------------------------------------------------ offers
def test_offers_are_closed_without_a_trip_after_check_in_or_before_it_opens():
    assert not build_context(state(booking=False)).open
    assert "complete" in build_context(state(status="checked-in")).reason_closed
    assert "not opened" in build_context(state(clock=False)).reason_closed
    assert build_context(state(clock=False)).offers == ()


def test_unused_bag_and_premium_seat_can_both_be_released_with_rule_values():
    ctx = build_context(state())
    assert ids(ctx) == ["RELEASE_BAG", "RELEASE_SEAT", "REDEEM_BAG"]
    assert ctx.offer("RELEASE_BAG").points == RELEASE_POINTS["bag"] == 800
    assert ctx.offer("RELEASE_SEAT").points == RELEASE_POINTS["extra"] == 1500


def test_a_bag_the_traveller_plans_to_use_cannot_be_released():
    assert "RELEASE_BAG" not in ids(build_context(state(bags=2, planned=2)))


def test_release_offers_disappear_when_the_budget_is_gone_or_the_reward_was_used():
    assert not [o for o in build_context(state(budget=500)).offers if o.kind == "release"]
    assert not [o for o in build_context(state(released=True)).offers if o.kind == "release"]


def test_a_released_seat_cannot_be_released_again_and_needs_a_standard_replacement():
    assert "RELEASE_SEAT" not in ids(build_context(state(redeemed_seat=True)))
    assert "RELEASE_SEAT" not in ids(build_context(state(seats=(0, 3, 2))))
    assert "RELEASE_SEAT" not in ids(build_context(state(seat_class="standard", entitled="standard")))


def test_redeem_bag_prices_follow_the_rules_and_show_the_shortfall():
    first = build_context(state(bags=0, balance=1000, seat_class="standard", entitled="standard")).offer("REDEEM_BAG")
    assert first.points == REDEEM_POINTS["bag1"] and not first.affordable and first.shortfall == 2000
    second = build_context(state(bags=1, balance=5000, seat_class="standard", entitled="standard")).offer("REDEEM_BAG")
    assert second.points == REDEEM_POINTS["bag2"] and second.affordable and second.shortfall == 0
    assert build_context(state(bags=3)).offer("REDEEM_BAG") is None
    assert build_context(state(grants=0)).offer("REDEEM_BAG") is None


def test_seats_above_the_current_one_are_offered_and_included_ones_cost_nothing():
    ctx = build_context(state(seat_class="standard", entitled="extra", balance=0))
    extra = ctx.offer("REDEEM_EXTRA")
    assert extra.included and extra.points == 0 and extra.affordable
    paid = build_context(state(seat_class="standard", entitled="standard", balance=100)).offer("REDEEM_PREFERRED")
    assert not paid.included and paid.points == REDEEM_POINTS["preferred"] and paid.shortfall == 2100


def test_no_seat_upgrade_when_none_is_free_or_the_seat_was_released():
    assert build_context(state(seat_class="standard", entitled="standard", seats=(3, 0, 0))).offer("REDEEM_PREFERRED") is None
    assert build_context(state(seat_class="standard", entitled="standard", released_seat=True)).offer("REDEEM_EXTRA") is None


# ------------------------------------------------------------------ fallback advice
def test_fallback_picks_one_release_and_says_the_reward_is_pending():
    r = deterministic_advice(build_context(state()))
    assert r.source == "fallback"
    releases = [p for p in r.picks if p.offer_id.startswith("RELEASE")]
    assert len(releases) == 1 and releases[0].offer_id == "RELEASE_SEAT"  # 1,500 beats 800
    assert "pending" in releases[0].why and "1,500" in releases[0].why


def test_fallback_keeps_a_seat_the_traveller_wants_and_releases_the_bag_instead():
    r = deterministic_advice(build_context(state(seat_pref="extra")))
    assert [p.offer_id for p in r.picks] == ["RELEASE_BAG"]


def test_fallback_suggests_the_bag_the_traveller_needs_if_affordable():
    r = deterministic_advice(build_context(state(bags=1, planned=2, balance=6000, seat_class="standard", entitled="standard")))
    assert [p.offer_id for p in r.picks] == ["REDEEM_BAG"]


def test_fallback_says_how_far_a_needed_bag_is_when_unaffordable():
    r = deterministic_advice(build_context(state(bags=1, planned=2, balance=1000, seat_class="standard", entitled="standard")))
    assert r.picks == [] and "2,500 points away" in r.summary


def test_fallback_uses_an_included_seat_before_spending_points():
    r = deterministic_advice(build_context(state(seat_class="standard", entitled="preferred", bags=0, balance=0)))
    assert [p.offer_id for p in r.picks] == ["REDEEM_PREFERRED"] and "already cover" in r.picks[0].why


def test_fallback_explains_when_closed_or_when_there_is_nothing_to_do():
    assert deterministic_advice(build_context(state(booking=False))).summary.startswith("You have no trip")
    quiet = deterministic_advice(build_context(state(seat_class="standard", entitled="standard", bags=0, grants=0, seats=(3, 0, 0))))
    assert quiet.picks == [] and "nothing" in quiet.summary.lower()


def test_every_fallback_text_passes_the_same_validator_as_model_text():
    for kwargs in (
        {}, {"seat_pref": "extra"}, {"pending": 800, "balance": 5000},
        {"bags": 1, "planned": 2, "balance": 6000, "seat_class": "standard", "entitled": "standard"},
        {"seat_class": "standard", "entitled": "standard", "balance": 100, "seat_pref": "front"},
    ):
        ctx = build_context(state(**kwargs))
        r = deterministic_advice(ctx)
        sub = {"summary": r.summary, "picks": [{"offerId": p.offer_id, "why": p.why} for p in r.picks]}
        validate_submission(sub, ctx)


# ------------------------------------------------------------------ validator
def good(ctx_state=None):
    ctx = build_context(ctx_state or state())
    sub = {"summary": "You can earn points by releasing a seat you do not need.", "picks": [{"offerId": "RELEASE_SEAT", "why": "Earn 1,500 points, pending until you fly."}]}
    return ctx, sub


def test_a_correct_answer_is_accepted_and_carries_the_rules_offers():
    ctx, sub = good()
    r = validate_submission(sub, ctx)
    assert r.source == "ai" and [p.offer_id for p in r.picks] == ["RELEASE_SEAT"]
    assert [o.id for o in r.offers] == ids(ctx)  # numbers come from the rules, not the model


def test_an_invented_or_unavailable_offer_is_rejected():
    ctx, sub = good()
    sub["picks"][0]["offerId"] = "REDEEM_EXTRA"  # a traveller already in Extra has no such offer
    with pytest.raises(AdviceRejected):
        validate_submission(sub, ctx)
    sub["picks"][0]["offerId"] = "GIVE_ME_POINTS"
    with pytest.raises(AdviceRejected):
        validate_submission(sub, ctx)


def test_an_unaffordable_purchase_is_rejected():
    ctx = build_context(state(bags=1, planned=2, balance=1000, seat_class="standard", entitled="standard"))
    with pytest.raises(AdviceRejected):
        validate_submission({"summary": "Add a bag.", "picks": [{"offerId": "REDEEM_BAG", "why": "You need it."}]}, ctx)


def test_two_releases_and_duplicates_are_rejected():
    ctx = build_context(state())
    two = {"summary": "Release both.", "picks": [{"offerId": "RELEASE_BAG", "why": "a"}, {"offerId": "RELEASE_SEAT", "why": "b"}]}
    with pytest.raises(AdviceRejected, match="one rewarded release"):
        validate_submission(two, ctx)
    dup = {"summary": "Twice.", "picks": [{"offerId": "RELEASE_BAG", "why": "a"}, {"offerId": "RELEASE_BAG", "why": "b"}]}
    with pytest.raises(AdviceRejected, match="duplicate"):
        validate_submission(dup, ctx)


def test_dollar_amounts_and_unknown_points_amounts_are_rejected():
    ctx, sub = good()
    for bad in ("It is worth $20.", "Roughly 20 dollars.", "You will earn 5,000 points.", "Earn 9999 pts."):
        with pytest.raises(AdviceRejected):
            validate_submission({**sub, "summary": bad}, ctx)
    with pytest.raises(AdviceRejected):
        validate_submission({**sub, "picks": [{"offerId": "RELEASE_SEAT", "why": "Earn 700 points."}]}, ctx)


def test_amounts_from_the_offers_balances_and_shortfalls_are_allowed():
    ctx = build_context(state(balance=5000, bags=1, planned=2, seat_class="standard", entitled="standard"))
    assert {5000, 3500, 1500} <= allowed_points(ctx)  # balance, bag cost, balance after buying
    validate_submission({"summary": "You have 5,000 points and the bag costs 3,500 points, leaving 1,500 points.", "picks": []}, ctx)


def test_a_closed_context_accepts_no_ai_answer():
    with pytest.raises(AdviceRejected):
        validate_submission({"summary": "Hello.", "picks": []}, build_context(state(status="checked-in")))


def test_clean_strips_control_characters_and_caps_length():
    assert clean("a\x00b\n  c", 10) == "a b c" and len(clean("x" * 999, 50)) == 50 and clean(None, 5) == ""


# ------------------------------------------------------------------ advise (fake agent)
def test_advise_returns_the_models_answer_when_it_validates():
    ctx, sub = good()
    r = advise(ctx, request("I only carry a backpack"), agent=lambda inp: AdvisorResult(sub, 1))
    assert r.source == "ai"


def test_advise_falls_back_when_the_agent_fails_or_answers_badly():
    ctx, _ = good()
    def boom(inp):
        raise TimeoutError("slow")
    assert advise(ctx, request(), agent=boom).source == "fallback"
    bad = {"summary": "Worth $50.", "picks": []}
    assert advise(ctx, request(), agent=lambda inp: AdvisorResult(bad, 1)).source == "fallback"


def test_advise_does_not_call_the_model_when_there_is_nothing_to_choose():
    def never(inp):
        raise AssertionError("model called")
    assert advise(build_context(state(clock=False)), request(), agent=never).source == "fallback"
    quiet = build_context(state(seat_class="standard", entitled="standard", bags=0, grants=0, seats=(3, 0, 0)))
    assert advise(quiet, request(), agent=never).source == "fallback"


# ------------------------------------------------------------------ tools and the Bedrock loop (fake client)
def test_the_advisor_has_no_tool_that_can_change_anything():
    names = [t["toolSpec"]["name"] for t in advisor_tools.TOOL_CONFIG["tools"]]
    assert names == ["explain_rule", "submit_advice"]
    assert advisor_tools.run_tool("explain_rule", {"topic": "pending"})["rule"].startswith("Points earned")
    for bad in ("redeem", "release", "book"):
        with pytest.raises(ValueError):
            advisor_tools.run_tool(bad, {})
    with pytest.raises(ValueError):
        advisor_tools.run_tool("explain_rule", {"topic": "nope"})


class FakeBedrock:
    """Replays scripted model turns and records what the loop sent back."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # the loop keeps appending to its list
        return {"output": {"message": {"role": "assistant", "content": self.turns.pop(0)}}}


def use(name, payload, uid="t1"):
    return {"toolUse": {"toolUseId": uid, "name": name, "input": payload}}


class Settings:
    bedrock_model_id = "test-model"


def run(turns, ctx, check=None):
    client = FakeBedrock(turns)
    with patch("app.config.get_settings", lambda: Settings()):
        result = run_advisor(AdvisorInput(message="hi", ctx=ctx, check=check), client=client)
    return result, client


def test_the_loop_looks_up_a_rule_then_submits_and_the_first_message_holds_the_offers():
    ctx, sub = good()
    result, client = run([[use("explain_rule", {"topic": "pending"})], [use("submit_advice", sub, "t2")]], ctx)
    assert result.submission == sub and result.tool_calls == 2
    first = client.calls[0]["messages"][0]["content"][0]["text"]
    assert "RELEASE_SEAT" in first and '"balance": 1200' in first
    assert client.calls[0]["toolConfig"] is advisor_tools.TOOL_CONFIG


def test_a_rejected_submission_gets_one_retry_then_the_loop_raises():
    ctx, sub = good()
    check = lambda s: validate_submission(s, ctx)
    bad = {"summary": "Worth $50.", "picks": []}
    result, client = run([[use("submit_advice", bad)], [use("submit_advice", sub, "t2")]], ctx, check)
    assert result.submission == sub
    sent_back = client.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert sent_back["status"] == "error" and "Rejected" in sent_back["content"][0]["text"]
    with pytest.raises(AdviceRejected):
        run([[use("submit_advice", bad)], [use("submit_advice", bad, "t2")]], ctx, check)


def test_the_loop_raises_when_the_model_never_submits():
    ctx, _ = good()
    with pytest.raises(RuntimeError):
        run([[{"text": "I think you should release it."}]], ctx)
