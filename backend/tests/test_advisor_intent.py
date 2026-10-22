"""The rules-only advisor reads the traveller's message. It can only narrow the advice, never widen it."""

from app.advisor.advisor import deterministic_advice, validate_submission
from app.advisor.intent import parse_intent
from app.advisor.offers import build_context

from .advisor_support import perk, state

NONE = [perk(i) for i in ("boarding", "drink", "lane", "standby", "overweight")]


def picks(message="", **kw):
    c = build_context(state(**kw))
    r = deterministic_advice(c, message)
    validate_submission({"summary": r.summary, "picks": [{"offerId": p.offer_id, "why": p.why} for p in r.picks]}, c)
    return [p.offer_id for p in r.picks]


def test_no_message_changes_nothing():
    assert picks("", planned=0, seat_class="extra") == picks("   ", planned=0, seat_class="extra")


def test_traveling_light_prefers_the_bag_over_the_seat():
    assert picks("I only have a backpack", planned=0, seat_class="extra", entitled="extra", bags=2)[0] == "RELEASE_BAG"


def test_keeping_the_bag_drops_the_bag_release():
    assert "RELEASE_BAG" not in picks("I need my bags, keep my bag", planned=0, bags=2, seat_class="preferred", entitled="preferred")


def test_a_tall_traveller_does_not_release_their_legroom_seat():
    got = picks("I'm tall and need legroom", planned=2, bags=2, seat_class="extra", entitled="extra")
    assert "RELEASE_SEAT" not in got


def test_asking_for_early_boarding_picks_it_if_it_exists_and_is_affordable():
    got = picks("I want to board early", perks=NONE, balance=2000, planned=2, bags=2, seat_class="standard", entitled="standard")
    assert "REDEEM_BOARDING" in got
    assert "REDEEM_BOARDING" not in picks("I want to board early", perks=NONE, balance=100, planned=2, bags=2, seat_class="standard", entitled="standard")


def test_a_message_cannot_create_an_offer():
    got = picks("overweight bag and standby", perks=[perk("boarding")], balance=20000, planned=2, bags=2, seat_class="standard", entitled="standard")
    assert "REDEEM_OVERWEIGHT" not in got and "REDEEM_STANDBY" not in got  # not in the offers, so never picked


def test_heavy_bag_and_standby_are_picked_when_offered_and_affordable():
    got = picks("my bag is heavy and I may need to change flights", perks=NONE, balance=20000, planned=2, bags=2, seat_class="standard", entitled="standard")
    assert "REDEEM_OVERWEIGHT" in got and "REDEEM_STANDBY" in got


def test_saving_points_skips_optional_purchases():
    got = picks("I want to save my points, board early", perks=NONE, balance=20000, planned=2, bags=2, seat_class="standard", entitled="standard")
    assert all(not g.startswith("REDEEM_") for g in got)


def test_parse_flags():
    i = parse_intent("Tall, with an overweight bag; want a drink and standby, front seat please")
    assert i.wants_extra_seat and i.heavy_bag and i.wants_drink and i.wants_standby and i.wants_front_seat
    assert not parse_intent("hello").any
