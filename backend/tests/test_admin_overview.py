"""The airline overview adds up the way the airline reads it. No database: the two queries are faked."""

import datetime as dt

from app.services import admin


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, flights, activity):
        self.flights, self.activity = flights, activity

    rapid = ()
    seats = ()
    flags = ()
    seat_values = ()
    pool = ()
    bags = ()
    benefits = ()

    def execute(self, sql, *a):
        if sql is admin.BENEFITS_SQL:
            return Rows(list(self.benefits))
        if sql is admin.POOL_SQL:
            return Rows(list(self.pool))
        if sql is admin.BAGS_SQL:
            return Rows(list(self.bags))
        if sql is admin.SEAT_VALUE_SQL:
            return Rows(list(self.seat_values))
        if sql is admin.FLAGS_SQL:
            return Rows(list(self.flags))
        if sql is admin.RAPID_SQL:
            return Rows(list(self.rapid))
        if sql is admin.SEAT_SQL:
            return Rows(list(self.seats))
        return Rows(self.flights if sql is admin.FLIGHTS_SQL else self.activity)


def flight(fid="F01", number="2418", budget=10000, reserved=950, settled=0, cpp=1):
    return {
        "flight_id": fid, "flight_number": number, "flight_date": dt.date(2027, 12, 16), "origin_airport": "DAL",
        "destination_airport": "DEN", "flight_status": "SCHEDULED", "budget": budget, "reserved": reserved,
        "settled": settled, "remaining": budget - reserved - settled, "cents_per_point": cpp, "bookings": 18, "checked_in": 3,
    }


def test_totals_add_up_and_cost_uses_the_flights_cost_per_point():
    conn = FakeConn(
        [flight(), flight("F02", "968", budget=20000, reserved=0, settled=2000, cpp=2)],
        [
            {"flight_id": "F01", "benefit_type": "BAG", "action_type": "RELEASE", "n": 1, "earned": 800, "spent_perkflex": 0, "spent_rapid": 0},
            {"flight_id": "F01", "benefit_type": "PERK", "action_type": "RELEASE", "n": 1, "earned": 150, "spent_perkflex": 0, "spent_rapid": 0},
            {"flight_id": "F01", "benefit_type": "BAG", "action_type": "REDEEM", "n": 1, "earned": 0, "spent_perkflex": 1000, "spent_rapid": 2000},
            {"flight_id": "ZZ", "benefit_type": "BAG", "action_type": "RELEASE", "n": 9, "earned": 9, "spent_perkflex": 0, "spent_rapid": 0},  # not listed: ignored
        ],
    )
    conn.rapid = [{"flight_id": "F01", "pending": 2700}, {"flight_id": "ZZ", "pending": 5}]
    out = admin.overview(conn)
    t = out["totals"]
    assert (t["pointsSpentPerkflex"], t["pointsSpentRapid"], t["rapidPending"]) == (1000, 2000, 2700)
    assert (t["flights"], t["budget"], t["owed"], t["paid"]) == (2, 30000, 950, 2000)
    assert t["estimatedCost"] == 9.5 + 40.0  # 950 points at 1 cent, 2,000 points at 2 cents
    assert (t["releases"], t["redemptions"], t["pointsSpent"]) == (2, 1, 3000)
    first = out["flights"][0]
    assert first["flightId"] == "WN2418" and first["releases"] == {"bag": 1, "seat": 0, "perk": 1}
    assert first["remaining"] == 9050 and first["pointsEarned"] == 950


def test_a_quiet_programme_is_all_zeros_not_an_error():
    out = admin.overview(FakeConn([], []))
    assert out["flights"] == [] and out["totals"]["estimatedCost"] == 0 and out["totals"]["owed"] == 0


def test_seats_freed_and_reused_are_counted_per_flight_and_in_total():
    conn = FakeConn([flight()], [])
    conn.seats = [{"flight_id": "F01", "freed": 3, "reused": 1}]
    out = admin.overview(conn)
    assert out["flights"][0]["seatsFreed"] == 3 and out["totals"]["seatsReused"] == 1


def test_trips_that_undo_a_lot_or_release_and_buy_back_are_flagged_for_a_person():
    conn = FakeConn([flight()], [])
    d = dt.date(2027, 12, 16)
    conn.flags = [
        {"kind": "UNDO", "confirmation_code": "ABC123", "flight_number": "2418", "flight_date": d, "n": 3, "detail": ""},
        {"kind": "RELEASE_AND_BUY", "confirmation_code": "XYZ789", "flight_number": "2418", "flight_date": d, "n": 1, "detail": "BAG"},
    ]
    flags = admin.overview(conn)["flags"]
    assert [f["kind"] for f in flags] == ["undo", "release-and-buy"]
    assert flags[0]["text"] == "Undid 3 releases (the limit)" and flags[1]["text"].endswith("bag on the same trip")
    assert "name" not in flags[0] and "passenger" not in flags[0]  # trips, not people


def test_the_with_and_without_model_values_reused_seats_at_list_price_against_the_reward_cost():
    conn = FakeConn([flight(reserved=1000, cpp=1)], [])  # 1,000 points owed at 1 cent = $10.00
    conn.seat_values = [{"flight_id": "F01", "seat_type": "EXTRA_LEGROOM", "n": 1}, {"flight_id": "F01", "seat_type": "STANDARD", "n": 2}]
    m = admin.overview(conn)["model"]
    assert m["with"] == {"rewardCost": 10.0, "seatResale": 110.0, "net": 100.0}  # 80 + 2 x 15
    assert m["without"] == {"rewardCost": 0, "seatResale": 0, "net": 0} and len(m["assumptions"]) >= 3


def test_each_flight_reports_its_benefits_inventory_pool():
    conn = FakeConn([flight(), flight("F02", "968")], [])
    conn.pool = [
        {"flight_id": "F01", "seat_type": "STANDARD", "total": 120, "free": 40, "given_back": 2, "reused": 1},
        {"flight_id": "F01", "seat_type": "EXTRA_LEGROOM", "total": 12, "free": 3, "given_back": 1, "reused": 0},
        {"flight_id": "ZZ", "seat_type": "STANDARD", "total": 9, "free": 9, "given_back": 0, "reused": 0},  # not listed: ignored
    ]
    conn.bags = [{"flight_id": "F01", "bag_grants_total": 8, "bag_grants_remaining": 5}]
    by_id = {f["flightId"]: f["pool"] for f in admin.overview(conn)["flights"]}
    a = next(p for k, p in by_id.items() if k.endswith("2418"))
    assert a["seats"]["standard"] == {"total": 120, "free": 40, "givenBack": 2, "reused": 1}
    assert a["seats"]["extra"]["free"] == 3
    assert a["seats"]["preferred"] == {"total": 0, "free": 0, "givenBack": 0, "reused": 0}
    assert a["bagGrants"] == {"total": 8, "remaining": 5}
    b = next(p for k, p in by_id.items() if k.endswith("968"))  # no rows: zeros, never missing
    assert b["bagGrants"] == {"total": 0, "remaining": 0} and b["seats"]["standard"]["free"] == 0


def test_each_flight_lists_which_benefits_were_released_and_which_were_bought():
    conn = FakeConn([flight(), flight("F02", "968")], [])
    row = lambda fid, bid, name, typ, act, n, earned=0, spent=0: {  # noqa: E731
        "flight_id": fid, "benefit_id": bid, "benefit_name": name, "benefit_type": typ, "action_type": act, "n": n,
        "earned": earned, "spent": spent,
    }
    conn.benefits = [
        row("F01", "SEAT_XL", "Extra Legroom seat", "SEAT", "RELEASE", 2, earned=3000),
        row("F01", "SEAT_XL", "Extra Legroom seat", "SEAT", "REDEEM", 1, spent=4000),
        row("F01", "BAG_2", "Second bag", "BAG", "RELEASE", 1, earned=800),
        row("ZZ", "BAG_1", "First bag", "BAG", "RELEASE", 9),  # not listed: ignored
    ]
    flights = {f["flightId"][-4:]: f for f in admin.overview(conn)["flights"]}
    got = {b["name"]: b for b in next(f for k, f in flights.items() if k.endswith("2418"))["benefits"]}
    assert (got["Extra Legroom seat"]["released"], got["Extra Legroom seat"]["bought"]) == (2, 1)
    assert (got["Extra Legroom seat"]["pointsEarned"], got["Extra Legroom seat"]["pointsSpent"]) == (3000, 4000)
    assert (got["Second bag"]["released"], got["Second bag"]["bought"], got["Second bag"]["kind"]) == (1, 0, "bag")
    assert next(f for k, f in flights.items() if k.endswith("968"))["benefits"] == []
