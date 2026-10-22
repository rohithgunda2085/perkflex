"""Check-in actions and booking against the real schema (each test is rolled back)."""

import pytest
from pydantic import TypeAdapter

from app.services.actions import Action, perform
from app.services.context import load_traveller
from app.services.state import build_state

pytestmark = pytest.mark.db
PARSE = TypeAdapter(Action).validate_python


def act(conn, settings, pid, payload):
    """Runs one action as the traveller and returns (outcome, state afterwards)."""
    outcome = perform(conn, load_traveller(conn, pid), PARSE(payload), settings)
    return outcome, build_state(conn, pid, settings, outcome.notice, outcome.error)


def state(conn, settings, pid):
    return build_state(conn, pid, settings)


# ---------------------------------------------------------------- releasing for points
def test_releasing_a_bag_is_pending_then_posts_once_after_the_trip(conn, test_settings):
    s0 = state(conn, test_settings, "P14")  # Rohith: 2 bags, travelling with 0
    assert (s0["balance"], s0["pending"], s0["booking"]["bags"]) == (12450, 0, 2)

    out, s = act(conn, test_settings, "P14", {"type": "release", "benefit": "bag"})
    assert not out.error and "880 points are pending" in out.notice  # 800 + 10% Silver bonus
    assert (s["balance"], s["pending"], s["booking"]["bags"], s["booking"]["released"]) == (12450, 880, 1, True)
    assert [(e["kind"], e["status"], e["points"], e["label"]) for e in s["ledger"]] == [
        ("release", "pending", 880, "Unused checked-bag allowance")
    ]

    out, _ = act(conn, test_settings, "P14", {"type": "release", "benefit": "bag"})
    assert out.error and "already accepted" in out.notice  # one reward offer per flight

    out, s = act(conn, test_settings, "P14", {"type": "checkin"})
    assert not out.error and s["booking"]["status"] == "checked-in"
    out, _ = act(conn, test_settings, "P14", {"type": "release", "benefit": "bag"})
    assert out.error  # offers close at check-in

    out, s = act(conn, test_settings, "P14", {"type": "complete"})
    assert not out.error and "+880 PerkFlex (released benefits)" in out.notice and "+50 PerkFlex (completion bonus)" in out.notice
    assert "+50 PerkFlex (flight award, Autumn off-peak x2)" in out.notice  # 22 Oct 2026 is in the off-peak season
    assert "Rapid Rewards (flying)" in out.notice
    assert s["booking"]["status"] == "flown" and s["pending"] == 0
    assert s["balance"] == 12450 + 880 + 50 + 50 + 3780  # the reward, the 50-point completion bonus, the off-peak flight award (25 x 2), and the flying points (2,700 + 40% Silver)
    assert s["ledger"][0]["status"] == "posted"

    out, s2 = act(conn, test_settings, "P14", {"type": "complete"})  # completing again posts nothing more
    assert not out.error and s2["balance"] == s["balance"]


def test_releasing_a_premium_seat_swaps_to_a_standard_seat_for_points(conn, test_settings):
    out, s = act(conn, test_settings, "P01", {"type": "release", "benefit": "seat"})  # Maya, Extra Legroom 2A
    assert not out.error and "1,500 points are pending" in out.notice
    b = s["booking"]
    assert (b["seatClass"], b["releasedSeat"], b["seatSource"], s["pending"]) == ("standard", True, "PerkFlex replacement", 1500)
    assert "2A" in s["inventory"]["seats"]["extra"]  # the released seat goes back on sale
    out, _ = act(conn, test_settings, "P01", {"type": "redeem", "benefit": "extra"})
    assert out.error and "waiver" in out.notice  # cannot take the seat straight back


def test_releasing_with_nothing_to_release_is_refused(conn, test_settings):
    out, _ = act(conn, test_settings, "P09", {"type": "release", "benefit": "bag"})  # Alex has no bag allowance
    assert out.error and "unused included bag" in out.notice
    out, _ = act(conn, test_settings, "P09", {"type": "release", "benefit": "seat"})  # and a Standard seat
    assert out.error and "not eligible" in out.notice


# ---------------------------------------------------------------- redeeming points
def test_buying_a_bag_with_points_then_checking_in(conn, test_settings):
    out, _ = act(conn, test_settings, "P02", {"type": "checkin"})  # Ravi has 1 bag but no allowance
    assert out.error and "more bags than your allowance" in out.notice

    out, s = act(conn, test_settings, "P02", {"type": "redeem", "benefit": "bag"})
    assert not out.error and "Checked bag 1 added for 3,000 Rapid Rewards points" in out.notice
    assert (s["balance"], s["booking"]["bags"], s["booking"]["redeemedBags"]) == (3000, 1, 1)
    assert [(e["kind"], e["points"], e["label"]) for e in s["ledger"]] == [("redemption", -3000, "Checked bag 1")]
    assert act(conn, test_settings, "P02", {"type": "checkin"})[0].error is False


def test_not_enough_points_changes_nothing(conn, test_settings):
    out, s = act(conn, test_settings, "P09", {"type": "redeem", "benefit": "bag"})  # Alex has 0 points
    assert out.error and "Not enough points" in out.notice
    assert s["balance"] == 0 and s["booking"]["bags"] == 0 and s["ledger"] == []


def test_upgrading_a_seat_with_points(conn, test_settings):
    out, s = act(conn, test_settings, "P04", {"type": "redeem", "benefit": "preferred"})  # Dev, 6,000 points
    assert not out.error and "Preferred seat added for 2,200 Rapid Rewards points" in out.notice
    b = s["booking"]
    assert (s["balance"], b["seatClass"], b["redeemedSeat"], b["seatSource"]) == (3800, "preferred", True, "PerkFlex redemption")
    assert "18B" in s["inventory"]["seats"]["standard"]


def test_a_seat_the_traveller_already_owns_costs_nothing(conn, test_settings):
    out, s = act(conn, test_settings, "P11", {"type": "redeem", "benefit": "extra"})  # Mahesh, Silver
    assert not out.error and out.notice == "This seat is already covered by your benefits. No points charged."
    assert (s["balance"], s["booking"]["seatClass"], s["booking"]["redeemedSeat"]) == (15000, "extra", False)


def test_you_cannot_redeem_what_you_already_have(conn, test_settings):
    assert act(conn, test_settings, "P01", {"type": "redeem", "benefit": "preferred"})[0].error  # Maya already has Extra
    assert act(conn, test_settings, "P01", {"type": "redeem", "benefit": "standard"})[0].error


def test_a_retried_request_with_the_same_key_is_applied_once(conn, test_settings):
    payload = {"type": "redeem", "benefit": "bag", "idempotencyKey": "click-1"}
    _, first = act(conn, test_settings, "P02", payload)
    out, second = act(conn, test_settings, "P02", payload)
    assert not out.error and second["balance"] == first["balance"] == 3000
    assert second["booking"]["bags"] == 1 and len(second["ledger"]) == 1


def test_an_idempotency_key_cannot_replay_another_travellers_action(conn, test_settings):
    act(conn, test_settings, "P02", {"type": "redeem", "benefit": "bag", "idempotencyKey": "shared"})
    out, s = act(conn, test_settings, "P04", {"type": "redeem", "benefit": "bag", "idempotencyKey": "shared"})
    assert not out.error and s["booking"]["bags"] == 1 and s["balance"] == 3000  # Dev paid for his own bag


# ---------------------------------------------------------------- check-in
def test_opening_check_in_is_quiet_when_there_is_nothing_to_open(conn, test_settings):
    for pid in ("P18", "P01"):  # the new traveller has no trip; Maya's check-in is already open
        out, _ = act(conn, test_settings, pid, {"type": "open-checkin"})
        assert out == type(out)()


def test_a_better_seat_covered_by_benefits_is_given_when_check_in_first_opens(conn, test_settings):
    conn.execute("UPDATE fact_booking SET checkin_opened_time_utc = NULL WHERE booking_id = 'B19'")
    assert state(conn, test_settings, "P20")["booking"]["clockAdvanced"] is False
    out, s = act(conn, test_settings, "P20", {"type": "open-checkin"})  # Dee Ann Carlin, Silver, Preferred seat
    assert not out.error and "Silver benefits already cover Extra Legroom" in out.notice
    assert (s["booking"]["seatClass"], s["booking"]["clockAdvanced"], s["balance"]) == ("extra", True, 2500)
    assert act(conn, test_settings, "P20", {"type": "open-checkin"})[0].notice == ""  # only the first time


def test_bag_count_is_validated(conn, test_settings):
    # Maya's Choice Extra fare includes 2 bags: 2 is fine, 3 is not.
    assert act(conn, test_settings, "P01", {"type": "bags", "count": 2})[1]["booking"]["actualBags"] == 2
    assert act(conn, test_settings, "P01", {"type": "bags", "count": 3})[1]["booking"]["actualBags"] == 3
    out, _ = act(conn, test_settings, "P01", {"type": "checkin"})
    assert out.error and "more bags than your allowance" in out.notice
    act(conn, test_settings, "P01", {"type": "bags", "count": 1})
    assert not act(conn, test_settings, "P01", {"type": "checkin"})[0].error


def test_completing_before_checking_in_is_refused(conn, test_settings):
    out, s = act(conn, test_settings, "P01", {"type": "complete"})
    assert out.error and "Complete check-in" in out.notice and s["booking"]["status"] == "booked"


def test_completing_one_trip_does_not_touch_other_travellers(conn, test_settings):
    act(conn, test_settings, "P14", {"type": "checkin"})
    ravi_before = state(conn, test_settings, "P02")
    act(conn, test_settings, "P14", {"type": "complete"})
    ravi_after = state(conn, test_settings, "P02")
    assert ravi_after["booking"]["status"] == "booked" and ravi_after["balance"] == ravi_before["balance"]
    assert conn.execute("SELECT rapid_rewards_pending AS p FROM fact_points_wallet WHERE passenger_id = 'P02'").fetchone()["p"] == 300


def test_actions_need_a_trip(conn, test_settings):
    for payload in ({"type": "release", "benefit": "bag"}, {"type": "checkin"}, {"type": "redeem", "benefit": "bag"}, {"type": "complete"}):
        out, _ = act(conn, test_settings, "P18", payload)
        assert out.error and "Book a flight first" in out.notice


# ---------------------------------------------------------------- booking
BOOK = {"type": "book", "fare": "basic", "flightId": "WN2418", "from": "DAL", "to": "DEN", "date": "2027-12-16", "needs": {"bags": 1}}


def test_a_new_traveller_books_a_flight(conn, test_settings):
    out, s = act(conn, test_settings, "P18", BOOK)
    assert not out.error and "Your flight is booked" in out.notice
    b = s["booking"]
    assert (b["status"], b["fare"], b["date"], b["flightId"], b["seatClass"]) == ("booked", "basic", "2027-12-16", "WN2418", "standard")
    assert len(b["id"]) == 6 and b["clockAdvanced"] is False
    assert b["total"] == 162.6 + 45 and b["bags"] == 1  # the extra bag was bought with cash
    assert b["seat"] not in s["inventory"]["seats"]["standard"]
    assert conn.execute("SELECT rapid_rewards_pending AS p FROM fact_points_wallet WHERE passenger_id = 'P18'").fetchone()["p"] == 300


def test_a_new_booking_can_be_checked_in_and_completed(conn, test_settings):
    # Choice Extra includes 2 bags; planning to bring 1 leaves one unused allowance to release.
    act(conn, test_settings, "P18", {**BOOK, "fare": "extra", "needs": {"bags": 1, "seat": "extra"}})
    assert act(conn, test_settings, "P18", {"type": "open-checkin"})[1]["booking"]["clockAdvanced"] is True
    out, s = act(conn, test_settings, "P18", {"type": "release", "benefit": "bag"})
    assert not out.error and s["pending"] == 800 and s["booking"]["bags"] == 1
    act(conn, test_settings, "P18", {"type": "checkin"})
    out, s = act(conn, test_settings, "P18", {"type": "complete"})
    assert s["balance"] == 800 + 50 + 25 + 2700 and s["pending"] == 0 and s["booking"]["status"] == "flown"


def test_a_tier_traveller_booking_is_not_charged_twice_for_what_the_tier_gives(conn, test_settings):
    conn.execute("UPDATE dim_passenger SET tier_status = 'GOLD' WHERE passenger_id = 'P18'")
    out, s = act(conn, test_settings, "P18", {**BOOK, "needs": {"bags": 2, "seat": "extra"}})
    b = s["booking"]
    assert not out.error and b["total"] == 162.6 and b["bags"] == 2 and b["seatClass"] == "extra"
    assert b["bagSource"] == "Gold benefits" and b["seatSource"] == "Gold benefits"


def test_rebooking_replaces_an_unused_trip_and_frees_its_seat(conn, test_settings):
    _, first = act(conn, test_settings, "P18", BOOK)
    old_seat = first["booking"]["seat"]
    out, second = act(conn, test_settings, "P18", {**BOOK, "fare": "choice"})
    assert not out.error and second["booking"]["fare"] == "choice" and second["booking"]["id"] != first["booking"]["id"]
    # The old seat was freed: it is either re-used by the new booking or back on sale, never left stranded.
    assert old_seat == second["booking"]["seat"] or old_seat in second["inventory"]["seats"]["standard"]
    live = conn.execute("SELECT count(*) AS n FROM fact_booking WHERE passenger_id = 'P18' AND booking_status <> 'CANCELLED'").fetchone()["n"]
    assert live == 1
    # only the new trip's pending earn counts: Choice base 190 x 6 = 1,140
    assert conn.execute("SELECT rapid_rewards_pending AS p FROM fact_points_wallet WHERE passenger_id = 'P18'").fetchone()["p"] == 1140


def test_a_trip_with_perkflex_activity_cannot_be_replaced(conn, test_settings):
    act(conn, test_settings, "P14", {"type": "release", "benefit": "bag"})
    out, s = act(conn, test_settings, "P14", {**BOOK, "needs": {}})
    assert out.error and "active trip with points activity" in out.notice and s["booking"]["id"] == "R8H6WF"


@pytest.mark.parametrize(
    "change,message",
    [
        ({"to": "DAL"}, "different departure and arrival"),
        ({"from": "XXX", "to": "DEN"}, "There is no WN 2418 flight from XXX to DEN"),
        ({"fare": "basic", "needs": {"refund": True}}, "does not meet your selected requirements"),
        ({"fare": "basic", "needs": {"budget": 100}}, "does not meet your selected requirements"),
    ],
)
def test_booking_refusals_leave_nothing_behind(conn, test_settings, change, message):
    out, s = act(conn, test_settings, "P18", {**BOOK, **change})
    assert out.error and message in out.notice and s["booking"] is None


@pytest.mark.parametrize("origin,destination", [("LAS", "PHX"), ("BNA", "DAL"), ("DEN", "DAL"), ("PHX", "BNA")])
def test_every_route_between_the_demo_airports_can_be_booked(conn, test_settings, origin, destination):
    out, s = act(conn, test_settings, "P18", {**BOOK, "from": origin, "to": destination})
    b = s["booking"]
    assert not out.error and (b["from"], b["to"], b["flightId"], b["date"]) == (origin, destination, "WN2418", "2027-12-16")
    row = conn.execute(
        "SELECT f.origin_airport o, f.destination_airport d, s.flight_id = f.flight_id AS seat_on_flight, s.seat_status "
        "FROM fact_booking k JOIN dim_flight_schedule f USING (flight_id) JOIN dim_seat s ON s.seat_id = k.seat_id "
        "WHERE k.booking_id = (SELECT booking_id FROM fact_booking WHERE passenger_id = 'P18' AND booking_status <> 'CANCELLED')"
    ).fetchone()
    assert (row["o"], row["d"], row["seat_on_flight"], row["seat_status"]) == (origin, destination, True, "ASSIGNED")


def test_seats_are_not_shared_between_routes(conn, test_settings):
    _, s = act(conn, test_settings, "P18", {**BOOK, "from": "LAS", "to": "PHX"})
    assert s["booking"]["seat"] not in s["inventory"]["seats"][s["booking"]["seatClass"]]
    taken = {
        r["flight_id"]: r["n"]
        for r in conn.execute(
            "SELECT flight_id, count(*) n FROM dim_seat WHERE flight_id LIKE %s AND seat_status <> 'AVAILABLE' "
            "GROUP BY flight_id",
            ("%-%-_",),
        )
    }
    assert taken == {"LAS-PHX-1": 1}  # one seat on the booked flight, none on any other route or departure


def test_the_nearest_flight_is_used_when_the_date_has_none(conn, test_settings):
    _, s = act(conn, test_settings, "P18", {**BOOK, "flightId": "WN968", "date": "2026-10-22"})
    assert s["booking"]["flightId"] == "WN968" and s["booking"]["date"] == "2027-12-16"
    _, s = act(conn, test_settings, "P18", {**BOOK, "flightId": "WN2418", "date": "2026-10-22"})
    assert s["booking"]["date"] == "2026-10-22"  # Rohith's flight date exists for 2418


def test_a_buy_takes_perkflex_first_then_rapid_rewards_and_the_notice_says_which(conn, test_settings):
    conn.execute("UPDATE fact_points_wallet SET perkflex_available = 400 WHERE passenger_id = 'P04'")  # Dev: 6,000 Rapid Rewards
    out, s = act(conn, test_settings, "P04", {"type": "redeem", "benefit": "preferred"})  # 2,200 points
    assert not out.error and "Preferred seat added for 400 PerkFlex + 1,800 Rapid Rewards points" in out.notice
    assert s["wallets"] == {"perkflex": {"available": 0, "pending": 0}, "rapidRewards": {"available": 4200, "pending": s["wallets"]["rapidRewards"]["pending"]}}
    redemption = next(e for e in s["ledger"] if e["kind"] == "redemption")
    assert (redemption["paidPerkflex"], redemption["paidRapid"], redemption["wallet"]) == (400, 1800, "both")


def test_a_perkflex_balance_that_covers_the_price_leaves_rapid_rewards_alone(conn, test_settings):
    conn.execute("UPDATE fact_points_wallet SET perkflex_available = 3000 WHERE passenger_id = 'P02'")  # Ravi
    out, s = act(conn, test_settings, "P02", {"type": "redeem", "benefit": "bag"})  # 3,000 points
    assert "added for 3,000 PerkFlex points" in out.notice
    assert (s["wallets"]["perkflex"]["available"], s["wallets"]["rapidRewards"]["available"]) == (0, 6000)
