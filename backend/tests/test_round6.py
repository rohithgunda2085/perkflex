"""Round 6 against the real schema: reward policy, completion bonus, travel groups and gifts, sales."""

import pytest
from pydantic import TypeAdapter

from app.services.actions import Action, perform
from app.services.context import load_traveller
from app.services.controls import set_sale, update_policy
from app.services.state import build_state

from .test_api import sign_in, start_check_in

pytestmark = pytest.mark.db
PARSE = TypeAdapter(Action).validate_python


def act(conn, settings, pid, payload):
    outcome = perform(conn, load_traveller(conn, pid), PARSE(payload), settings)
    return outcome, build_state(conn, pid, settings, outcome.notice, outcome.error)


def state(conn, settings, pid):
    return build_state(conn, pid, settings)


# ---------------------------------------------------------------- reward policy
def test_flat_is_the_default_and_value_mode_pays_a_percent_of_the_cash_price(conn, test_settings):
    s = state(conn, test_settings, "P13")  # a Member: no status bonus
    assert (s["rewards"]["mode"], s["rewards"]["bag"], s["rewards"]["preferred"], s["rewards"]["extra"]) == ("FLAT", 800, 700, 1500)
    update_policy(conn, "airline", mode="VALUE")  # 18% of $45 / $35 / $80 at 1 cent per point
    s = state(conn, test_settings, "P13")
    assert (s["rewards"]["mode"], s["rewards"]["bag"], s["rewards"]["preferred"], s["rewards"]["extra"]) == ("VALUE", 810, 630, 1440)
    assert state(conn, test_settings, "P07")["rewards"]["bag"] == 1053  # Platinum: 810 + 30%


def test_the_value_percent_and_value_of_a_point_move_the_reward(conn, test_settings):
    update_policy(conn, "airline", mode="VALUE", value_percent=20, cents_per_point=1.5)
    assert state(conn, test_settings, "P13")["rewards"]["bag"] == 600  # 4500 x 20% / 1.5


def test_a_release_pays_the_policy_amount_and_small_perks_stay_flat(conn, test_settings):
    update_policy(conn, "airline", mode="VALUE")
    act(conn, test_settings, "P07", {"type": "open-checkin"})
    out, s = act(conn, test_settings, "P07", {"type": "release", "benefit": "bag"})
    assert not out.error and s["pending"] == 1053
    out, s = act(conn, test_settings, "P07", {"type": "release", "benefit": "drink"})
    assert not out.error and s["pending"] == 1053 + 195  # 150 flat + 30% Platinum


def test_every_policy_change_is_written_to_the_log(conn):
    update_policy(conn, "airline", mode="VALUE", completion_bonus=75)
    update_policy(conn, "airline", completion_bonus=75)  # unchanged: no new row
    rows = conn.execute("SELECT setting, old_value, new_value, changed_by FROM fact_policy_audit ORDER BY audit_id").fetchall()
    assert [(r["setting"], r["old_value"], r["new_value"]) for r in rows] == [
        ("release_mode", "FLAT", "VALUE"),
        ("completion_bonus", "50", "75"),
    ]
    assert {r["changed_by"] for r in rows} == {"airline"}


# ---------------------------------------------------------------- completion bonus
def _fly(conn, settings, pid, release=True):
    act(conn, settings, pid, {"type": "open-checkin"})
    if release:
        act(conn, settings, pid, {"type": "release", "benefit": "bag"})
    act(conn, settings, pid, {"type": "checkin"})
    return act(conn, settings, pid, {"type": "complete"})


def test_completing_a_trip_with_a_posted_release_adds_the_bonus_once(conn, test_settings):
    before = state(conn, test_settings, "P07")["wallets"]["perkflex"]["available"]
    out, s = _fly(conn, test_settings, "P07")
    assert "+50 PerkFlex (completion bonus)" in out.notice
    assert s["wallets"]["perkflex"]["available"] == before + 1040 + 50
    assert any(e["kind"] == "bonus" and e["points"] == 50 for e in s["ledger"])
    assert any("completion bonus of 50" in n["text"] for n in s["notifications"])
    _, again = act(conn, test_settings, "P07", {"type": "complete"})
    assert again["wallets"]["perkflex"]["available"] == before + 1040 + 50  # completing again adds nothing


def test_no_release_means_no_bonus_and_zero_switches_it_off(conn, test_settings):
    out, s = _fly(conn, test_settings, "P05", release=False)
    assert "completion bonus" not in out.notice
    update_policy(conn, "airline", completion_bonus=0)
    out, _ = _fly(conn, test_settings, "P07")
    assert "completion bonus" not in out.notice


def test_the_bonus_is_paid_from_the_flights_budget_and_skipped_when_it_has_no_room(conn, test_settings):
    act(conn, test_settings, "P07", {"type": "open-checkin"})
    act(conn, test_settings, "P07", {"type": "release", "benefit": "bag"})
    act(conn, test_settings, "P07", {"type": "checkin"})
    conn.execute("UPDATE fact_flight_campaign SET reward_budget_points = budget_reserved_points + budget_settled_points + 20")
    out, _ = act(conn, test_settings, "P07", {"type": "complete"})
    assert not out.error and "completion bonus" not in out.notice  # 20 points left, the bonus is 50


def test_bonus_points_expire_like_other_points_after_12_months(conn, test_settings):
    _fly(conn, test_settings, "P07")
    lots = conn.execute("SELECT points FROM pf_expiry_lots('P07') ORDER BY points").fetchall()
    assert [r["points"] for r in lots] == [50, 1040]


# ---------------------------------------------------------------- travel groups and gifts
def _group(conn, settings):
    assert not act(conn, settings, "P13", {"type": "group-invite", "companion": "kabir"})[0].error
    assert not act(conn, settings, "P07", {"type": "group-respond", "group": "manish", "accept": True})[0].error


def test_an_invitation_must_be_accepted_before_anyone_can_give_points(conn, test_settings):
    act(conn, test_settings, "P13", {"type": "group-invite", "companion": "kabir"})
    out, _ = act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 500})
    assert out.error and "travel group" in out.notice
    s = state(conn, test_settings, "P07")
    assert s["group"]["invites"] == [{"group": "manish", "from": "Manish Galigini"}]
    assert any("invited you" in n["text"] for n in s["notifications"])


def test_a_gift_moves_perkflex_points_between_members_and_both_ledgers_show_it(conn, test_settings):
    _group(conn, test_settings)
    giver0 = state(conn, test_settings, "P13")["wallets"]["perkflex"]["available"]
    taker0 = state(conn, test_settings, "P07")["wallets"]["perkflex"]["available"]
    out, s = act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 500, "idempotencyKey": "gift-1"})
    assert not out.error and "500 PerkFlex points sent to Kabir Sethi" in out.notice
    assert s["wallets"]["perkflex"]["available"] == giver0 - 500
    taker = state(conn, test_settings, "P07")
    assert taker["wallets"]["perkflex"]["available"] == taker0 + 500
    assert any(e["kind"] == "gift" and e["points"] == 500 for e in taker["ledger"])
    assert any(e["kind"] == "gift" and e["points"] == -500 for e in s["ledger"])
    assert any("gave you 500" in n["text"] for n in taker["notifications"])
    assert [m["name"] for m in s["group"]["members"]] == ["Manish Galigini", "Kabir Sethi"]


def test_sending_the_same_gift_request_twice_gives_once(conn, test_settings):
    _group(conn, test_settings)
    act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 500, "idempotencyKey": "gift-1"})
    out, s = act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 500, "idempotencyKey": "gift-1"})
    assert not out.error and conn.execute("SELECT count(*) AS n FROM fact_gift").fetchone()["n"] == 1


def test_gift_limits_amount_balance_daily_total_and_no_passing_on(conn, test_settings):
    _group(conn, test_settings)
    assert "100 to 2,000" in act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 99})[0].notice
    assert "100 to 2,000" in act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 2001})[0].notice
    conn.execute("UPDATE fact_points_wallet SET perkflex_available = 9000 WHERE passenger_id IN ('P13', 'P07')")
    assert not act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 2000})[0].error
    out, _ = act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 1500})
    assert out.error and "3,000 points in 24 hours" in out.notice
    out, _ = act(conn, test_settings, "P07", {"type": "gift", "to": "manish", "points": 100})
    assert out.error and "cannot be passed on" in out.notice


def test_you_cannot_give_more_than_you_have_or_to_yourself_or_to_a_stranger(conn, test_settings):
    _group(conn, test_settings)
    conn.execute("UPDATE fact_points_wallet SET perkflex_available = 300 WHERE passenger_id = 'P13'")
    out, _ = act(conn, test_settings, "P13", {"type": "gift", "to": "kabir", "points": 500})
    assert out.error and "300 PerkFlex points available" in out.notice
    assert act(conn, test_settings, "P13", {"type": "gift", "to": "manish", "points": 100})[0].error
    out, _ = act(conn, test_settings, "P13", {"type": "gift", "to": "maya", "points": 100})
    assert out.error and "travel group" in out.notice


def test_declining_leaving_and_ending_a_group(conn, test_settings):
    act(conn, test_settings, "P13", {"type": "group-invite", "companion": "kabir"})
    act(conn, test_settings, "P07", {"type": "group-respond", "group": "manish", "accept": False})
    assert state(conn, test_settings, "P07")["group"]["invites"] == []
    _group(conn, test_settings)
    assert not act(conn, test_settings, "P07", {"type": "group-leave"})[0].error
    assert [m["name"] for m in state(conn, test_settings, "P13")["group"]["members"]] == ["Manish Galigini"]
    _group(conn, test_settings)
    act(conn, test_settings, "P13", {"type": "group-leave"})  # the organiser leaves: the group ends
    assert state(conn, test_settings, "P07")["group"]["inGroup"] is False


def test_a_group_has_up_to_six_travellers_and_one_group_per_traveller(conn, test_settings):
    for who in ("kabir", "maya", "ravi", "neha", "dev"):
        assert not act(conn, test_settings, "P13", {"type": "group-invite", "companion": who})[0].error
    out, _ = act(conn, test_settings, "P13", {"type": "group-invite", "companion": "sara"})
    assert out.error and "up to 6" in out.notice
    act(conn, test_settings, "P07", {"type": "group-respond", "group": "manish", "accept": True})
    out, _ = act(conn, test_settings, "P12", {"type": "group-invite", "companion": "kabir"})
    assert out.error and "already in another travel group" in out.notice


def test_a_companion_can_be_found_by_rapid_rewards_number(conn, test_settings):
    number = conn.execute("SELECT rapid_rewards_account_id AS n FROM dim_passenger WHERE passenger_id = 'P07'").fetchone()["n"]
    assert not act(conn, test_settings, "P13", {"type": "group-invite", "companion": number})[0].error
    assert act(conn, test_settings, "P13", {"type": "group-invite", "companion": "nobody-here"})[0].error


# ---------------------------------------------------------------- sales
def test_a_sale_lowers_the_price_the_traveller_pays_and_only_on_that_flight(conn, test_settings):
    act(conn, test_settings, "P13", {"type": "open-checkin"})
    s0 = state(conn, test_settings, "P13")
    flight = conn.execute("SELECT flight_id FROM fact_booking WHERE passenger_id = 'P13'").fetchone()["flight_id"]
    set_sale(conn, "airline", flight, "bag", 20)
    s = state(conn, test_settings, "P13")
    assert (s["prices"]["bag1"], s["prices"]["list"]["bag1"], s["prices"]["sales"]) == (2400, 3000, {"bag": 20})
    out, after = act(conn, test_settings, "P13", {"type": "redeem", "benefit": "bag"})
    assert not out.error and after["balance"] == s0["balance"] - 2400
    other = [f["flight_id"] for f in conn.execute("SELECT flight_id FROM dim_flight_schedule").fetchall() if f["flight_id"] != flight][0]
    assert conn.execute("SELECT pf_redeem_price(%s, 'BAG1') AS p", (other,)).fetchone()["p"] == 3000


def test_a_sale_can_be_ended_and_each_change_is_logged(conn):
    set_sale(conn, "airline", "F01", "preferred", 25)
    assert conn.execute("SELECT pf_redeem_price('F01', 'SEAT_PREF') AS p").fetchone()["p"] == 1650
    set_sale(conn, "airline", "F01", "preferred", 0)
    assert conn.execute("SELECT pf_redeem_price('F01', 'SEAT_PREF') AS p").fetchone()["p"] == 2200
    rows = conn.execute("SELECT old_value, new_value FROM fact_policy_audit ORDER BY audit_id").fetchall()
    assert [(r["old_value"], r["new_value"]) for r in rows] == [(None, "25%"), ("25%", "ended")]


def test_small_perk_prices_follow_a_sale_too(conn, test_settings):
    act(conn, test_settings, "P13", {"type": "open-checkin"})
    flight = conn.execute("SELECT flight_id FROM fact_booking WHERE passenger_id = 'P13'").fetchone()["flight_id"]
    set_sale(conn, "airline", flight, "drink", 50)
    perk = next(p for p in state(conn, test_settings, "P13")["booking"]["perks"] if p["id"] == "drink")
    assert (perk["redeemPoints"], perk["listPoints"]) == (300, 600)
    out, _ = act(conn, test_settings, "P13", {"type": "redeem", "benefit": "drink"})
    assert not out.error and "300" in out.notice


def test_a_sale_sends_a_message_to_travellers_on_that_flight_only_once_it_starts(conn, test_settings):
    act(conn, test_settings, "P13", {"type": "open-checkin"})
    s = state(conn, test_settings, "P13")
    assert not any(n["kind"] == "price-drop" for n in s["notifications"])
    flight = conn.execute("SELECT flight_id FROM fact_booking WHERE passenger_id = 'P13'").fetchone()["flight_id"]
    set_sale(conn, "airline", flight, "preferred", 25)
    s = state(conn, test_settings, "P13")
    drop = next(n for n in s["notifications"] if n["kind"] == "price-drop")
    assert "Preferred seat is 25% off" in drop["text"] and "1,650 points instead of 2,200" in drop["text"]
    set_sale(conn, "airline", flight, "preferred", 0)
    assert not any(n["kind"] == "price-drop" for n in state(conn, test_settings, "P13")["notifications"])
    assert "watches" not in s


def test_the_status_card_says_what_the_next_level_is_worth(conn, test_settings):
    nudge = state(conn, test_settings, "P14")["status"]["nudge"]  # Rohith, Silver
    assert nudge["tier"] == "Gold" and nudge["bagNow"] == 880 and nudge["bagNext"] == 960
    assert nudge["flyingNow"] == 3780 and nudge["flyingNext"] == 4320
    assert state(conn, test_settings, "P07")["status"]["nudge"] is None  # Platinum is the top


def test_the_demo_reset_clears_groups_gifts_sales_and_the_policy(conn):
    update_policy(conn, "airline", mode="VALUE", completion_bonus=75)
    set_sale(conn, "airline", "F01", "bag", 20)
    conn.execute("SELECT pf_group_invite('P13', 'P07')")
    conn.execute("SELECT pf_demo_restore()")
    assert conn.execute("SELECT release_mode, completion_bonus FROM dim_reward_policy").fetchone() == {"release_mode": "FLAT", "completion_bonus": 50}
    for table in ("fact_group_member", "fact_gift", "fact_price_sale"):
        assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0  # noqa: S608


# ---------------------------------------------------------------- the airline's controls over HTTP
def test_only_the_airline_can_read_or_change_the_controls(client):
    sign_in(client, "maya")
    assert client.get("/api/admin/controls").status_code == 403
    assert client.post("/api/admin/policy", json={"mode": "VALUE"}).status_code == 403
    assert client.post("/api/admin/sale", json={"flightId": "F01", "benefit": "bag", "discountPct": 20}).status_code == 403


def test_the_airline_changes_the_policy_and_runs_a_sale_and_travellers_see_both(client):
    sign_in(client, "airline")
    body = client.post("/api/admin/policy", json={"mode": "VALUE", "completionBonus": 100}).json()
    assert body["policy"]["mode"] == "VALUE" and body["policy"]["completionBonus"] == 100
    assert {a["setting"] for a in body["audit"]} >= {"release_mode", "completion_bonus"}
    body = client.post("/api/admin/sale", json={"flightId": "F01", "benefit": "preferred", "discountPct": 25}).json()
    assert body["sales"][0]["discountPct"] == 25
    sign_in(client, "harshini")
    s = client.get("/api/state").json()
    assert s["rewards"]["mode"] == "VALUE" and s["rewards"]["completionBonus"] == 100
    assert s["prices"]["sales"] == {"preferred": 25}
    sign_in(client, "airline")  # leave the shared schema as found
    client.post("/api/admin/policy", json={"mode": "FLAT", "completionBonus": 50})
    client.post("/api/admin/sale", json={"flightId": "F01", "benefit": "preferred", "discountPct": 0})


def test_bad_sale_and_policy_values_are_refused(client):
    sign_in(client, "airline")
    assert client.post("/api/admin/sale", json={"flightId": "F01", "benefit": "bag", "discountPct": 3}).status_code == 422
    assert client.post("/api/admin/sale", json={"flightId": "F01", "benefit": "bag", "discountPct": 80}).status_code == 422
    assert client.post("/api/admin/sale", json={"flightId": "F01", "benefit": "unicorn", "discountPct": 20}).status_code == 422
    assert client.post("/api/admin/policy", json={"valuePercent": 99}).status_code == 422
    assert client.post("/api/admin/policy", json={"mode": "FREE"}).status_code == 422


def test_the_demo_sale_button_puts_the_viewers_flight_on_a_25_percent_sale(client):
    start_check_in(client, "dev")
    s = client.post("/api/demo/sale", json={"benefit": "preferred"}).json()
    assert s["prices"]["sales"] == {"preferred": 25} and s["prices"]["preferred"] == 1650
    assert client.post("/api/demo/sale", json={"benefit": "unicorn"}).status_code == 422
    client.post("/api/demo/reset")  # clears the sale for the tests that follow
