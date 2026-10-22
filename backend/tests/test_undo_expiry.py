"""Undo, seat reuse, expiry, spend order and the two new perks, in PostgreSQL (these mirror checks run by hand)."""

from datetime import datetime, timezone

import pytest
from psycopg.errors import RaiseException

pytestmark = pytest.mark.db

NOW = datetime(2027, 12, 15, 23, 59, tzinfo=timezone.utc)


def call(conn, sql, *args):
    return conn.execute(f"SELECT {sql} AS r", args).fetchone()["r"]


def last_release(conn, booking):
    return conn.execute(
        "SELECT transaction_id FROM fact_perkflex_transaction WHERE booking_id = %s AND action_type = 'RELEASE' "
        "AND transaction_status = 'ACCEPTED' ORDER BY transaction_id DESC LIMIT 1",
        (booking,),
    ).fetchone()["transaction_id"]


def test_undoing_a_seat_release_restores_the_seat_and_takes_back_the_pending_points(conn):
    call(conn, "pf_open_checkin(%s,%s,%s)", "P01", "B01", NOW)
    call(conn, "pf_release_seat(%s,%s,%s,%s)", "P01", "B01", "u1", NOW)
    assert call(conn, "pf_undo_release(%s,%s,%s,%s)", "P01", "B01", last_release(conn, "B01"), NOW)["ok"]
    b = conn.execute("SELECT seat_id, seat_waiver_flag, reward_release_used_flag FROM fact_booking WHERE booking_id='B01'").fetchone()
    assert (b["seat_id"], b["seat_waiver_flag"], b["reward_release_used_flag"]) == ("F01-2A", False, False)
    assert conn.execute("SELECT perkflex_pending FROM fact_points_wallet WHERE passenger_id='P01'").fetchone()["perkflex_pending"] == 0
    assert conn.execute("SELECT budget_reserved_points FROM fact_flight_campaign WHERE flight_id='F01'").fetchone()["budget_reserved_points"] == 0


def test_a_second_undo_is_a_no_op_and_a_taken_seat_blocks_the_undo(conn):
    call(conn, "pf_open_checkin(%s,%s,%s)", "P01", "B01", NOW)
    call(conn, "pf_release_seat(%s,%s,%s,%s)", "P01", "B01", "u1", NOW)
    txn = last_release(conn, "B01")
    conn.execute("UPDATE fact_booking SET seat_id = 'F01-2A' WHERE booking_id = 'B02'")  # another traveller takes it
    assert conn.execute("SELECT reused_by_booking FROM dim_seat WHERE seat_id='F01-2A'").fetchone()["reused_by_booking"] == "B02"
    with pytest.raises(RaiseException, match="taken that seat"):
        call(conn, "pf_undo_release(%s,%s,%s,%s)", "P01", "B01", txn, NOW)


def test_the_undo_window_closes_after_one_real_minute(conn):
    call(conn, "pf_open_checkin(%s,%s,%s)", "P14", "B14", NOW)
    call(conn, "pf_release_perk(%s,%s,%s,%s,%s)", "P14", "B14", "PERK_LANE", "u1", NOW)
    conn.execute("UPDATE fact_perkflex_transaction SET recorded_at = now() - interval '10 minutes' WHERE booking_id = 'B14'")
    with pytest.raises(RaiseException, match="1-minute window"):
        call(conn, "pf_undo_release(%s,%s,%s,%s)", "P14", "B14", last_release(conn, "B14"), NOW)


def test_expired_points_leave_the_wallet_once_and_only_when_due(conn):
    assert call(conn, "pf_expire_points(%s,%s)", "P13", NOW)["expired"] == 0
    later = datetime(2028, 1, 5, tzinfo=timezone.utc)
    assert call(conn, "pf_expire_points(%s,%s)", "P13", later)["expired"] == 1500
    assert call(conn, "pf_expire_points(%s,%s)", "P13", later)["expired"] == 0
    assert conn.execute("SELECT perkflex_available FROM fact_points_wallet WHERE passenger_id='P13'").fetchone()["perkflex_available"] == 0


def test_rapid_first_spends_rapid_rewards_before_perkflex(conn):
    call(conn, "pf_open_checkin(%s,%s,%s)", "P13", "B13", NOW)
    call(conn, "pf_set_pay_order(%s,%s)", "P13", True)
    r = call(conn, "pf_redeem_perk(%s,%s,%s,%s,%s)", "P13", "B13", "PERK_BOARDING", "k1", NOW)
    assert (r["perkflex_points_used"], r["rapid_rewards_points_used"]) == (0, 900)


def test_standby_and_overweight_are_for_sale_and_overweight_cannot_be_released(conn):
    call(conn, "pf_open_checkin(%s,%s,%s)", "P13", "B13", NOW)
    assert call(conn, "pf_redeem_perk(%s,%s,%s,%s,%s)", "P13", "B13", "PERK_OVERWEIGHT", "k1", NOW)["ok"]
    with pytest.raises(RaiseException):
        call(conn, "pf_release_perk(%s,%s,%s,%s,%s)", "P13", "B13", "PERK_OVERWEIGHT", "k2", NOW)


def test_the_cap_binds_when_the_four_release_values_are_all_offered(conn):
    call(conn, "pf_open_checkin(%s,%s,%s)", "P14", "B14", NOW)
    call(conn, "pf_release_perk(%s,%s,%s,%s,%s)", "P14", "B14", "PERK_STANDBY", "a", NOW)
    with pytest.raises(RaiseException, match="at most 300"):
        call(conn, "pf_release_perk(%s,%s,%s,%s,%s)", "P14", "B14", "PERK_BOARDING", "b", NOW)
        call(conn, "pf_release_perk(%s,%s,%s,%s,%s)", "P14", "B14", "PERK_DRINK", "c", NOW)


def test_a_fourth_undo_on_one_trip_is_refused_by_the_database(conn):
    call(conn, "pf_open_checkin(%s,%s,%s)", "P14", "B14", NOW)
    for i in range(3):
        call(conn, "pf_release_perk(%s,%s,%s,%s,%s)", "P14", "B14", "PERK_LANE", f"r{i}", NOW)
        call(conn, "pf_undo_release(%s,%s,%s,%s)", "P14", "B14", last_release(conn, "B14"), NOW)
    call(conn, "pf_release_perk(%s,%s,%s,%s,%s)", "P14", "B14", "PERK_LANE", "r9", NOW)
    with pytest.raises(RaiseException, match="3 releases"):
        call(conn, "pf_undo_release(%s,%s,%s,%s)", "P14", "B14", last_release(conn, "B14"), NOW)


def test_simulated_others_take_the_released_seat_and_then_add_bags(conn):
    call(conn, "pf_open_checkin(%s,%s,%s)", "P06", "B06", NOW)
    call(conn, "pf_release_seat(%s,%s,%s,%s)", "P06", "B06", "s1", NOW)
    assert call(conn, "pf_demo_simulate_other(%s,%s)", "P06", NOW)["event"] == "seat"
    assert conn.execute("SELECT reused_by_booking FROM dim_seat WHERE freed_by_booking = 'B06'").fetchone()["reused_by_booking"]
    assert call(conn, "pf_demo_simulate_other(%s,%s)", "P06", NOW)["event"] == "bag"
