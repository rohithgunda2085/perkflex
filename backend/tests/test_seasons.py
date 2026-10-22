"""Seasonal and festival PerkFlex against the real schema: the flight award is multiplied by the rule for the flight date."""

from datetime import date

import pytest
from pydantic import TypeAdapter

from app.services.actions import Action, perform
from app.services.context import load_traveller
from app.services.controls import controls_view
from app.services.seasons import SeasonError, add_rule, award_for, remove_rule
from app.services.state import build_state

pytestmark = pytest.mark.db
PARSE = TypeAdapter(Action).validate_python


def fly(conn, settings, pid):
    for payload in ({"type": "open-checkin"}, {"type": "checkin"}, {"type": "complete"}):
        out = perform(conn, load_traveller(conn, pid), PARSE(payload), settings)
    return out, build_state(conn, pid, settings)


def test_award_for_dates(conn):
    normal = award_for(conn, date(2027, 12, 16))
    assert (normal["points"], normal["multiplier"], normal["note"]) == (25, 1.0, None)
    off_peak = award_for(conn, date(2026, 10, 22))
    assert (off_peak["points"], off_peak["note"]) == (50, "Autumn off-peak x2")
    festival = award_for(conn, date(2026, 11, 26))
    assert (festival["points"], festival["label"]) == (50, "Thanksgiving")
    assert award_for(conn, None)["points"] == 25


def test_overlapping_rules_use_the_higher_multiplier_never_both(conn):
    add_rule(conn, "airline", "FESTIVAL", "Big weekend", date(2026, 10, 20), date(2026, 10, 25), 3)
    assert award_for(conn, date(2026, 10, 22))["points"] == 75  # x3, not 2 x 3
    add_rule(conn, "airline", "SEASON", "Another x3", date(2026, 10, 20), date(2026, 10, 25), 3)
    assert award_for(conn, date(2026, 10, 22))["label"] == "Big weekend"  # a tie goes to the festival


def test_a_completed_flight_on_a_festival_date_posts_the_multiplied_award_with_its_reason(conn, test_settings):
    out, s = fly(conn, test_settings, "P14")  # Rohith, 22 Oct 2026: off-peak
    assert "+50 PerkFlex (flight award, Autumn off-peak x2)" in out.notice
    assert any(e["label"] == "Flight award (Autumn off-peak x2)" and e["points"] == 50 for e in s["ledger"])


def test_the_booking_screen_numbers_match_what_completion_posts(conn, test_settings):
    s = build_state(conn, "P14", test_settings)
    assert s["rewards"]["flightAward"] == 50 and s["rewards"]["awardNote"] == "Autumn off-peak x2"
    s = build_state(conn, "P05", test_settings)
    assert s["rewards"]["flightAward"] == 25 and s["rewards"]["awardNote"] is None


def test_rules_are_checked_and_removing_one_returns_to_the_base_award(conn):
    with pytest.raises(SeasonError):
        add_rule(conn, "airline", "FESTIVAL", "x", date(2027, 1, 1), date(2027, 1, 2), 2)
    with pytest.raises(SeasonError):
        add_rule(conn, "airline", "FESTIVAL", "Backwards", date(2027, 1, 5), date(2027, 1, 2), 2)
    with pytest.raises(SeasonError):
        add_rule(conn, "airline", "FESTIVAL", "Too long", date(2027, 1, 1), date(2027, 8, 1), 2)
    with pytest.raises(SeasonError):
        add_rule(conn, "airline", "FESTIVAL", "Too big", date(2027, 1, 1), date(2027, 1, 2), 4)
    view = controls_view(conn)["seasonRules"]
    rule = next(r for r in view if r["name"] == "Autumn off-peak" and r["start"] == "2026-10-05")
    remove_rule(conn, "airline", rule["id"])
    assert award_for(conn, date(2026, 10, 22))["points"] == 25
    with pytest.raises(SeasonError):
        remove_rule(conn, "airline", rule["id"])
    assert any("rule" in a["setting"] for a in controls_view(conn)["audit"])


def test_the_promo_strip_lists_active_and_upcoming_boosts_soonest_first(conn):
    from app.services.seasons import promos_view

    promos = promos_view(conn)
    assert 1 <= len(promos) <= 3
    assert all(p["multiplier"] > 1 and p["points"] == round(25 * p["multiplier"]) for p in promos)
    assert [p["start"] for p in promos] == sorted(p["start"] for p in promos)


def test_a_nearby_better_flight_is_suggested_only_when_one_is_scheduled(conn):
    from app.services.seasons import nearby_better

    flight = conn.execute("SELECT * FROM dim_flight_schedule WHERE flight_id = 'F01'").fetchone()
    assert nearby_better(conn, flight, 25) is None  # the other flights on this route are on the same date
    conn.execute(
        """INSERT INTO dim_flight_schedule (flight_id, carrier_code, flight_number, flight_date, origin_airport, destination_airport,
             departure_time_utc, arrival_time_utc, checkin_open_time_utc, fare_offset_cents, aircraft_type, aircraft_capacity, distance_miles, flight_status)
           VALUES ('F99', 'PF', '2418', '2027-12-19', 'DAL', 'DEN', '2027-12-19T15:30:00Z', '2027-12-19T18:00:00Z', '2027-12-18T15:30:00Z', 0, '73H', 175, 651, 'SCHEDULED')"""
    )
    hint = nearby_better(conn, flight, 25)
    assert hint and hint["date"] == "2027-12-19" and hint["points"] == 50 and hint["label"] == "Christmas and New Year"
    assert nearby_better(conn, flight, 50) is None  # nothing better than 50


def test_each_rule_shows_how_many_open_bookings_fall_in_its_window(conn):
    from app.services.seasons import rules_view

    rules = {(r["name"], r["start"]): r["bookings"] for r in rules_view(conn)}
    assert rules[("Autumn off-peak", "2026-10-05")] >= 1  # Rohith's 22 Oct 2026 trip
    assert rules[("Memorial Day", "2027-05-28")] == 0
