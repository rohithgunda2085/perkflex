"""Readable examples of the pricing rules (the same scenarios as the original TypeScript engine tests)."""

from app.rules.pricing import (
    DEFAULT_NEEDS,
    Needs,
    Traveller,
    entitlements,
    quote_fares,
    recommended_quote,
    sanitize_needs,
)

MEMBER = Traveller("Member", "None")


def test_extra_legroom_and_refundability_make_choice_extra_cheaper_than_preferred_plus_seat():
    needs = Needs(seat="extra", refund=True)
    quotes = quote_fares(MEMBER, needs, "WN2418")
    assert recommended_quote(quotes).fare == "extra"
    assert recommended_quote(quotes).total == 282.6
    assert next(q for q in quotes if q.fare == "preferred").total == 322.6


def test_light_traveller_gets_basic_not_an_upsell():
    assert recommended_quote(quote_fares(MEMBER, DEFAULT_NEEDS, "WN2418")).fare == "basic"


def test_gold_benefits_make_preferred_enough_for_a_refundable_comfort_trip():
    quotes = quote_fares(Traveller("Gold", "None"), Needs(bags=2, seat="extra", refund=True), "WN2418")
    best = recommended_quote(quotes)
    assert best.fare == "preferred"
    assert best.addons == []  # Gold already covers both bags and Extra Legroom: nothing charged twice


def test_fare_tier_and_card_bags_overlap_instead_of_stacking():
    e = entitlements(Traveller("Gold", "Plus"), "extra")
    assert e.bags == 2  # max(fare 2, Gold 2, card 1), not 5


def test_silver_extra_legroom_arrives_at_check_in():
    silver = Traveller("Silver", "None")
    assert entitlements(silver, "choice", "booking").seat == "preferred"
    assert entitlements(silver, "choice", "checkin").seat == "extra"


def test_an_impossible_budget_has_no_recommendation():
    assert recommended_quote(quote_fares(MEMBER, Needs(seat="extra", refund=True, budget=160), "WN2418")) is None


def test_totals_are_exact_to_the_cent():
    quotes = quote_fares(MEMBER, DEFAULT_NEEDS, "WN968")
    assert [q.total for q in quotes] == [182.6, 222.6, 262.6, 302.6]


def test_sanitize_needs_clamps_and_falls_back():
    n = sanitize_needs({"bags": 99, "seat": "nonsense", "refund": "yes", "budget": 5, "early": True}, DEFAULT_NEEDS)
    assert n.bags == 3 and n.seat == "any" and n.refund is False and n.budget == 100 and n.early is True
    assert sanitize_needs(None, DEFAULT_NEEDS) == DEFAULT_NEEDS
    assert sanitize_needs({"bags": True, "budget": float("nan")}, DEFAULT_NEEDS) == DEFAULT_NEEDS


def test_quote_serialises_to_camel_case_for_the_frontend():
    q = quote_fares(MEMBER, DEFAULT_NEEDS, "WN2418")[0].model_dump(by_alias=True)
    assert {"seatSource", "bagSource", "addons", "issues", "points"} <= set(q)
