"""Status bonuses: extra Rapid Rewards points for flying and extra PerkFlex points for a release."""

import pytest

from app.rules.data import (
    FARES,
    RELEASE_POINTS,
    TIER_FLYING_BONUS_PCT,
    TIER_RELEASE_BONUS_PCT,
    flying_points,
    release_points,
    with_bonus,
)
from app.rules.pricing import Needs, Traveller, quote_fares


def test_rounding_is_half_up_like_the_database():
    assert with_bonus(75, 10) == 83  # 82.5 rounds up
    assert with_bonus(800, 30) == 1040 and with_bonus(100, 0) == 100


def test_release_rewards_follow_status():
    assert [release_points(800, t) for t in ("Member", "Silver", "Gold", "Platinum")] == [800, 880, 960, 1040]
    assert release_points(RELEASE_POINTS["extra"], "Silver") == 1650


def test_flying_points_are_fare_rate_times_base_fare_plus_the_status_bonus():
    assert flying_points(190, 6, "Member") == 1140  # Choice: $190 x 6
    assert flying_points(190, 6, "Silver") == 1596  # + 40%
    assert flying_points(270, 10, "Platinum") == 5940  # + 120%


@pytest.mark.parametrize("tier", ["Member", "Silver", "Gold", "Platinum"])
def test_a_quote_says_how_its_points_were_worked_out(tier):
    quotes = quote_fares(Traveller(tier, "None"), Needs(), "WN2418")
    for q, fare in zip(quotes, FARES):
        assert q.rate == fare.multiplier and q.status_bonus == TIER_FLYING_BONUS_PCT[tier]
        assert q.points == flying_points(q.base, fare.multiplier, tier)


def test_the_bonus_never_makes_a_lower_status_earn_more():
    order = ["Member", "Silver", "Gold", "Platinum"]
    assert [TIER_FLYING_BONUS_PCT[t] for t in order] == sorted(TIER_FLYING_BONUS_PCT.values())
    assert [TIER_RELEASE_BONUS_PCT[t] for t in order] == sorted(TIER_RELEASE_BONUS_PCT.values())


# ---- the database holds the same rates (these need PostgreSQL) ----
@pytest.mark.db
def test_the_database_rates_match_the_python_settings(conn):
    from app.rules.data import TIER_FLYING_BONUS_PCT as fly
    from app.services.mapping import TIER_FROM_DB

    rows = conn.execute("SELECT tier_status, flying_bonus_pct, release_bonus_pct FROM dim_tier_bonus").fetchall()
    assert {TIER_FROM_DB[r["tier_status"]]: (r["flying_bonus_pct"], r["release_bonus_pct"]) for r in rows} == {
        t: (fly[t], TIER_RELEASE_BONUS_PCT[t]) for t in fly
    }


@pytest.mark.db
def test_the_database_pays_the_same_release_points_as_python(conn):
    for passenger, tier in (("P13", "Member"), ("P14", "Silver"), ("P06", "Gold"), ("P07", "Platinum")):
        for benefit, key in (("BAG1", "bag"), ("SEAT_PREF", "preferred"), ("SEAT_XL", "extra")):
            got = conn.execute("SELECT pf_release_points(%s, %s) AS n", (passenger, benefit)).fetchone()["n"]
            assert got == release_points(RELEASE_POINTS[key], tier), (passenger, benefit)


@pytest.mark.db
def test_pending_flying_points_of_travellers_with_status_include_their_bonus(conn):
    row = conn.execute(
        "SELECT points_delta FROM fact_point_transaction WHERE passenger_id = 'P14' AND transaction_type = 'FLIGHT_EARN_PENDING'"
    ).fetchone()
    assert row["points_delta"] == flying_points(270, 10, "Silver")  # Rohith: Choice Extra $270 x 10, +40%


# ---- the next-status nudge and the round-6 notifications (pure functions, no database) ----
def _traveller(tier="Silver"):
    from app.services.context import TravellerInfo

    return TravellerInfo("P14", "rohith", "Rohith Gunda", "", tier, "None", 0, 0, 0, 0, False, 38000)


STATUS = {"next": {"tier": "Gold", "at": 65000, "remaining": 27000}}
REWARDS = {"bag": 880, "preferred": 770, "extra": 1650, "bag_base": 800, "preferred_base": 700, "extra_base": 1500}


def test_the_nudge_shows_what_the_next_level_would_pay_on_the_next_trip():
    from app.services.extras import status_nudge

    n = status_nudge(STATUS, _traveller(), REWARDS, 3780)  # 2,700 base + 40% Silver
    assert (n["tier"], n["remaining"], n["near"]) == ("Gold", 27000, False)
    assert (n["bagNow"], n["bagNext"]) == (880, 960)  # +10% becomes +20% on 800
    assert (n["flyingNow"], n["flyingNext"]) == (3780, 4320)  # 2,700 + 60% Gold


def test_the_nudge_is_near_inside_20000_points_and_absent_at_the_top():
    from app.services.extras import status_nudge

    assert status_nudge({"next": {"tier": "Gold", "at": 65000, "remaining": 20000}}, _traveller(), REWARDS, 0)["near"] is True
    assert status_nudge({"next": None}, _traveller("Platinum"), REWARDS, 0) is None
    assert status_nudge(STATUS, _traveller(), REWARDS, 0)["flyingNext"] == 0  # nothing pending, so no promise


def _booking(seat_class="standard", bags=0, perks=()):
    return {"status": "booked", "seatClass": seat_class, "bags": bags, "perks": list(perks)}


PRICES = {
    "bag1": 2400, "bag2": 3500, "preferred": 1650, "extra": 4500,
    "list": {"bag1": 3000, "bag2": 3500, "preferred": 2200, "extra": 4500},
    "sales": {"bag": 20, "preferred": 25},
}
NO_GROUP = {"invites": [], "gifts": []}


def test_a_sale_on_the_travellers_flight_becomes_a_message_with_what_is_missing():
    from app.services.extras import extra_alerts

    out = extra_alerts(_booking(), PRICES, 2000, NO_GROUP)
    texts = {a["id"]: a["text"] for a in out}
    assert "25% off" in texts["drop-preferred"] and "1,650 points instead of 2,200" in texts["drop-preferred"]
    assert "You have enough points." in texts["drop-preferred"]
    assert "2,400 points instead of 3,000" in texts["drop-bag"] and "You need 400 more points." in texts["drop-bag"]


def test_no_message_without_a_sale_or_for_what_is_already_held():
    from app.services.extras import extra_alerts

    assert extra_alerts(_booking(), {**PRICES, "sales": {}}, 9000, NO_GROUP) == []  # nothing on sale
    assert extra_alerts(_booking("preferred"), {**PRICES, "sales": {"preferred": 25}}, 9000, NO_GROUP) == []  # already holds that seat
    flown = {**_booking(), "status": "flown"}
    assert extra_alerts(flown, PRICES, 9000, NO_GROUP) == []
    bought = _booking(perks=[{"id": "drink", "included": False, "bought": True, "redeemPoints": 450, "listPoints": 600}])
    assert extra_alerts(bought, {**PRICES, "sales": {"drink": 25}}, 9000, NO_GROUP) == []


def test_invitations_and_a_gift_just_received_become_messages_even_without_a_trip():
    from app.services.extras import extra_alerts

    group = {"invites": [{"group": "kabir", "from": "Kabir Sethi"}], "gifts": [{"direction": "in", "other": "Manish Galigini", "points": 500, "at": "x"}]}
    texts = [a["text"] for a in extra_alerts(None, PRICES, 0, group)]
    assert "Kabir Sethi invited you to a travel group." in texts and "Manish Galigini gave you 500 PerkFlex points." in texts
