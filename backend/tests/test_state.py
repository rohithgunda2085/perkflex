"""The state view for the seeded travellers, and its agreement with the pricing rules."""

import pytest

from app.rules.pricing import Traveller, entitlements
from app.services.state import build_state

pytestmark = pytest.mark.db

ALL_PASSENGERS = [f"P{n:02d}" for n in range(1, 29)]


@pytest.mark.parametrize("pid", ALL_PASSENGERS)
def test_every_traveller_has_a_coherent_view(conn, test_settings, pid):
    s = build_state(conn, pid, test_settings)
    profile, booking = s["profile"], s["booking"]
    assert profile["name"] and profile["initials"] and profile["tier"] in ("Member", "Silver", "Gold", "Platinum")
    assert s["balance"] == profile["points"] >= 0
    assert s["demo"] is True and len(s["travellers"]) == 28
    if pid == "P18":  # Michael Rankin: the new traveller
        assert booking is None and s["inventory"] is None and profile["hasTrip"] is False
        return
    assert profile["hasTrip"] is True
    assert booking["status"] == "booked" and booking["profileId"] == profile["id"]
    assert booking["seatClass"] in ("standard", "preferred", "extra") and booking["seat"]
    assert booking["flightId"] in ("WN2418", "WN968", "WN1820")
    assert s["inventory"]["flightId"] == booking["flightId"]
    # The seat the traveller holds is not offered to anyone else.
    assert booking["seat"] not in s["inventory"]["seats"][booking["seatClass"]]


@pytest.mark.parametrize("pid", [p for p in ALL_PASSENGERS if p != "P18"])
def test_seeded_bag_allowance_matches_the_pricing_rules(conn, test_settings, pid):
    """The SQL seed data and the Python pricing rules must agree on what each traveller's bags are."""
    s = build_state(conn, pid, test_settings)
    b, p = s["booking"], s["profile"]
    expected = entitlements(Traveller(p["tier"], p["card"]), b["fare"], "booking").bags
    assert b["bags"] == expected, f"{p['name']}: database {b['bags']} vs rules {expected}"


def test_rohith_keeps_his_demo_trip(conn, test_settings):
    s = build_state(conn, "P14", test_settings)
    b = s["booking"]
    assert s["profile"]["id"] == "rohith" and s["profile"]["name"] == "Rohith Gunda"
    assert (b["id"], b["fare"], b["date"], b["seat"], b["seatClass"], b["bags"]) == ("R8H6WF", "extra", "2026-10-22", "3A", "extra", 2)
    assert s["balance"] == 12450 and s["pending"] == 0 and s["ledger"] == []


def test_needs_come_from_the_trip_preferences_and_default_for_a_new_traveller(conn, test_settings):
    maya = build_state(conn, "P01", test_settings)["profile"]["needs"]
    assert maya["seat"] == "extra" and maya["refund"] is True and maya["budget"] == 450
    new = build_state(conn, "P18", test_settings)["profile"]["needs"]
    assert new == {"bags": 0, "seat": "any", "refund": False, "flexible": False, "seatNow": False, "early": False, "budget": 450}


def test_checkin_entitlements_are_included_for_the_frontend(conn, test_settings):
    e = build_state(conn, "P19", test_settings)["booking"]["checkinEntitlements"]  # Mahesh, Silver
    assert e["seat"] == "extra" and e["bags"] == 1 and "seatSource" in e and "chooseNow" in e


def test_the_switcher_is_empty_outside_demo_mode(conn, test_settings):
    s = build_state(conn, "P01", test_settings.model_copy(update={"demo_mode": False}))
    assert s["travellers"] == [] and s["demo"] is False


def test_avatars_are_stable_and_distinct_by_tier(conn, test_settings):
    people = {t["id"]: t for t in build_state(conn, "P01", test_settings)["travellers"]}
    assert people["leena"]["color"] == "gold" and people["kabir"]["color"] == "silver"
    assert people["deeann.carlin"]["initials"] == "DC" and people["michael.hanna"]["initials"] == "MH"


def test_the_eight_added_travellers_cover_every_kind_of_status_and_card(conn, test_settings):
    kinds = {
        "P21": ("Member", "None"), "P22": ("Silver", "None"), "P23": ("Gold", "None"), "P24": ("Platinum", "None"),
        "P25": ("Member", "Plus"), "P26": ("Member", "Premier"), "P27": ("Member", "Priority"), "P28": ("Silver", "Priority"),
    }
    for pid, (tier, card) in kinds.items():
        s = build_state(conn, pid, test_settings)
        assert (s["profile"]["tier"], s["profile"]["card"]) == (tier, card), pid
        assert s["booking"]["flightId"] in ("WN968", "WN1820")
