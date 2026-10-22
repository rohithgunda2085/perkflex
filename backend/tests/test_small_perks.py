"""Small perks (priority boarding, premium drink, priority lane) in the advisor. No database, no network.

The rule these tests protect: small perks sit beside the one rewarded release. They never use that slot, and the
validator still allows only one bag-or-seat release per flight.
"""

import pytest

from app.advisor.advisor import AdviceRejected, deterministic_advice, nudge, validate_submission
from app.advisor.offers import build_context

from .advisor_support import perk, state


def ctx(**kw):
    return build_context(state(**kw))


def ids(context):
    return [o.id for o in context.offers]


ALL_INCLUDED = [perk("boarding", included=True), perk("drink", included=True), perk("lane", included=True)]
NONE_INCLUDED = [perk("boarding"), perk("drink"), perk("lane")]


def test_included_perks_can_be_released_for_the_seeded_points():
    c = ctx(perks=ALL_INCLUDED)
    assert {o.id: o.points for o in c.offers if o.id.startswith("RELEASE_") and o.id not in ("RELEASE_BAG", "RELEASE_SEAT")} == {
        "RELEASE_BOARDING": 100,
        "RELEASE_DRINK": 150,
        "RELEASE_LANE": 50,
    }
    assert sum(o.points for o in c.offers if o.id in ("RELEASE_BOARDING", "RELEASE_DRINK", "RELEASE_LANE")) == 300  # the cap


def test_perks_the_traveller_lacks_can_be_bought_except_the_lane():
    c = ctx(perks=NONE_INCLUDED, balance=1000)
    assert ids(c).count("REDEEM_BOARDING") == 1 and ids(c).count("REDEEM_DRINK") == 1
    assert "REDEEM_LANE" not in ids(c) and "RELEASE_LANE" not in ids(c)
    boarding = c.offer("REDEEM_BOARDING")
    assert boarding.points == 900 and boarding.affordable
    drink_short = ctx(perks=NONE_INCLUDED, balance=500).offer("REDEEM_DRINK")
    assert not drink_short.affordable and drink_short.shortfall == 100


def test_released_or_bought_perks_are_not_offered_again():
    c = ctx(perks=[perk("drink", included=True, released=True), perk("boarding", bought=True), perk("lane", included=True)])
    assert "RELEASE_DRINK" not in ids(c) and "REDEEM_DRINK" not in ids(c)
    assert "REDEEM_BOARDING" not in ids(c) and "RELEASE_BOARDING" not in ids(c)
    assert "RELEASE_LANE" in ids(c)


def test_a_small_release_does_not_need_the_rewarded_slot_and_is_still_offered_after_it_is_used():
    c = ctx(perks=ALL_INCLUDED, released=True, bags=0, seat_class="standard", entitled="standard")
    assert "RELEASE_BAG" not in ids(c) and "RELEASE_DRINK" in ids(c)


def test_small_releases_stop_when_the_flight_budget_cannot_cover_them():
    c = ctx(perks=ALL_INCLUDED, budget=120)
    assert "RELEASE_BOARDING" in ids(c) and "RELEASE_LANE" in ids(c) and "RELEASE_DRINK" not in ids(c)


def test_closed_checkin_offers_nothing():
    assert ctx(perks=ALL_INCLUDED, status="checked-in").offers == ()


def test_validator_allows_small_perks_beside_one_big_release():
    c = ctx(perks=ALL_INCLUDED, planned=0, seat_class="standard", entitled="standard", bags=1)
    r = validate_submission(
        {
            "summary": "Release your unused bag and a drink.",
            "picks": [
                {"offerId": "RELEASE_BAG", "why": "You are not checking a bag."},
                {"offerId": "RELEASE_DRINK", "why": "Earn 150 points."},
                {"offerId": "RELEASE_LANE", "why": "Earn 50 points."},
            ],
        },
        c,
    )
    assert [p.offer_id for p in r.picks] == ["RELEASE_BAG", "RELEASE_DRINK", "RELEASE_LANE"]


def test_validator_still_rejects_two_big_releases_and_too_many_picks():
    c = ctx(perks=ALL_INCLUDED, planned=0, bags=1)
    with pytest.raises(AdviceRejected):
        validate_submission(
            {"summary": "x", "picks": [{"offerId": "RELEASE_BAG", "why": "a"}, {"offerId": "RELEASE_SEAT", "why": "b"}]}, c
        )
    c2 = ctx(perks=NONE_INCLUDED + [], balance=5000, planned=0, bags=1)
    five = [{"offerId": i, "why": "ok"} for i in ("RELEASE_BAG", "REDEEM_BOARDING", "REDEEM_DRINK", "REDEEM_BAG", "REDEEM_EXTRA")]
    with pytest.raises(AdviceRejected):
        validate_submission({"summary": "x", "picks": five}, c2)


def test_validator_rejects_an_invented_points_amount_for_a_perk():
    c = ctx(perks=ALL_INCLUDED)
    with pytest.raises(AdviceRejected):
        validate_submission({"summary": "x", "picks": [{"offerId": "RELEASE_DRINK", "why": "Earn 999 points."}]}, c)


def test_fallback_suggests_small_releases_and_never_two_big_ones():
    c = ctx(perks=ALL_INCLUDED, planned=0, bags=1)
    picks = [p.offer_id for p in deterministic_advice(c).picks]
    assert sum(p in ("RELEASE_BAG", "RELEASE_SEAT") for p in picks) == 1
    assert "RELEASE_DRINK" in picks and len(picks) <= 4


def test_someone_who_wants_early_boarding_keeps_it_and_may_buy_it():
    kept = ctx(perks=ALL_INCLUDED, early=True)
    assert "RELEASE_BOARDING" in ids(kept)  # still on the list of offers...
    assert "RELEASE_BOARDING" not in [p.offer_id for p in deterministic_advice(kept).picks]  # ...but never suggested
    buy = ctx(perks=NONE_INCLUDED, early=True, balance=1000)
    assert "REDEEM_BOARDING" in [p.offer_id for p in deterministic_advice(buy).picks]
    poor = ctx(perks=NONE_INCLUDED, early=True, balance=100)
    assert "REDEEM_BOARDING" not in [p.offer_id for p in deterministic_advice(poor).picks]


def test_the_nudge_can_point_at_a_small_perk_when_nothing_bigger_exists():
    c = ctx(perks=[perk("lane", included=True)], bags=0, seat_class="standard", entitled="standard")
    n = nudge(c)
    assert n is not None and n.offer_id == "RELEASE_LANE" and "50 points" in n.text


def test_the_advisor_sees_both_wallets_and_may_quote_either():
    state_ = state(balance=1000)
    state_["wallets"] = {"perkflex": {"available": 300, "pending": 0}, "rapidRewards": {"available": 700, "pending": 400}}
    c = build_context(state_)
    assert (c.perkflex, c.rapid_rewards, c.balance) == (300, 700, 1000)
    d = c.to_dict()
    assert d["perkflexPoints"] == 300 and d["rapidRewardsPoints"] == 700 and "PerkFlex first" in d["paymentOrder"]
    validate_submission({"summary": "You have 300 points in PerkFlex.", "picks": []}, c)
    with pytest.raises(AdviceRejected):
        validate_submission({"summary": "You have 301 points in PerkFlex.", "picks": []}, c)


def test_without_wallet_data_everything_counts_as_rapid_rewards():
    c = build_context(state(balance=1200))
    assert (c.perkflex, c.rapid_rewards) == (0, 1200)
