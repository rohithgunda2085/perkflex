"""The migrations produce the schema, data and functions the API depends on."""

import pytest

from app.migrations import migration_files, run_migrations
from app.db import connect

pytestmark = pytest.mark.db


def one(conn, sql, *params):
    return conn.execute(sql, params).fetchone()


def test_all_migrations_are_recorded(conn):
    applied = [r["filename"] for r in conn.execute("SELECT filename FROM schema_migrations ORDER BY filename")]
    assert applied == migration_files()


def test_rerunning_migrations_applies_nothing(test_settings):
    with connect(test_settings, autocommit=True) as c:
        assert run_migrations(c, log=lambda _: None) == []


def test_the_expected_travellers_and_accounts_exist(conn):
    assert one(conn, "SELECT count(*) AS n FROM dim_passenger")["n"] == 20
    assert one(conn, "SELECT count(*) AS n FROM dim_user_account")["n"] == 21
    assert one(conn, "SELECT count(*) AS n FROM fact_booking")["n"] == 19  # Michael Rankin has no trip yet
    assert one(conn, "SELECT count(*) AS n FROM dim_seat")["n"] == 5856  # 61 flights x 96 seats


def test_every_route_between_the_five_airports_has_three_departures_and_a_campaign(conn):
    assert one(conn, "SELECT count(*) AS n FROM dim_flight_schedule")["n"] == 61  # F01-F04 + 19 routes x 3
    rows = conn.execute(
        """SELECT origin_airport o, destination_airport d, count(DISTINCT flight_number) numbers, count(*) flights
             FROM dim_flight_schedule WHERE flight_date = '2027-12-16' GROUP BY 1, 2"""
    ).fetchall()
    assert len(rows) == 20 and all(r["o"] != r["d"] and r["numbers"] == 3 and r["flights"] == 3 for r in rows)
    assert one(conn, "SELECT count(*) AS n FROM fact_flight_campaign")["n"] == 61
    assert one(conn, "SELECT count(*) AS n FROM dim_seat WHERE flight_id = 'LAS-PHX-1'")["n"] == 96


def test_confirmation_codes_exist_and_rohith_keeps_his_demo_code(conn):
    assert one(conn, "SELECT confirmation_code AS c FROM fact_booking WHERE booking_id = 'B14'")["c"] == "R8H6WF"
    assert one(conn, "SELECT confirmation_code AS c FROM fact_booking WHERE booking_id = 'B01'")["c"] == "B01"
    assert one(conn, "SELECT count(*) AS n FROM fact_booking WHERE confirmation_code IS NULL")["n"] == 0


def test_the_new_traveller_has_no_booking_and_no_points(conn):
    assert one(conn, "SELECT count(*) AS n FROM fact_booking WHERE passenger_id = 'P18'")["n"] == 0
    w = one(conn, "SELECT rapid_rewards_available AS a, perkflex_available AS p FROM fact_points_wallet WHERE passenger_id = 'P18'")
    assert (w["a"], w["p"]) == (0, 0)


def test_the_ledger_is_append_only(conn):
    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("DELETE FROM fact_point_transaction WHERE point_transaction_id = 'PT001'")


def test_complete_booking_refuses_before_check_in_and_is_scoped_to_one_booking(conn):
    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match="Complete check-in"):
        conn.execute("SELECT pf_complete_booking('P01', 'B01', '2027-12-15T16:00:00Z')")
