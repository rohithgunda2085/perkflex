-- Adds flights for every route between the five demo airports (DAL, DEN, LAS, PHX, BNA), so the booking screen can
-- book whichever pair a traveller picks. DAL -> DEN already exists as F01-F04 and is left alone.
--
-- Each route gets the same three departures as F01-F03 (flight numbers 2418, 968 and 1820, same times and fare
-- offsets) on 16 Dec 2027, each with the same 96-seat layout and reward campaign. Flight ids look like
-- 'DAL-LAS-1' and seat ids like 'DAL-LAS-1-3A'. Distances are approximate. Synthetic data.
-- Safe to run twice: every insert skips rows that already exist.
--
-- One flight number can now serve several routes on the same day (as a multi-stop flight does), so the uniqueness
-- rule on (carrier, number, date) becomes (carrier, number, date, origin, destination).
BEGIN;

ALTER TABLE dim_flight_schedule
  DROP CONSTRAINT IF EXISTS dim_flight_schedule_carrier_code_flight_number_flight_date_key;
ALTER TABLE dim_flight_schedule
  DROP CONSTRAINT IF EXISTS dim_flight_schedule_number_date_route_key;
ALTER TABLE dim_flight_schedule
  ADD CONSTRAINT dim_flight_schedule_number_date_route_key
  UNIQUE (carrier_code, flight_number, flight_date, origin_airport, destination_airport);

CREATE TEMP TABLE pf_route (origin text, destination text, miles integer) ON COMMIT DROP;
INSERT INTO pf_route (origin, destination, miles)
SELECT a.code, b.code, d.miles
  FROM (VALUES ('DAL'), ('DEN'), ('LAS'), ('PHX'), ('BNA')) AS a(code)
  JOIN (VALUES ('DAL'), ('DEN'), ('LAS'), ('PHX'), ('BNA')) AS b(code) ON a.code <> b.code
  JOIN (VALUES ('BNA','DAL',626), ('BNA','DEN',1019), ('BNA','LAS',1740), ('BNA','PHX',1480),
               ('DAL','DEN',651), ('DAL','LAS',1067), ('DAL','PHX',887),
               ('DEN','LAS',628), ('DEN','PHX',586), ('LAS','PHX',256)) AS d(lo, hi, miles)
    ON d.lo = LEAST(a.code, b.code) AND d.hi = GREATEST(a.code, b.code)
 WHERE NOT (a.code = 'DAL' AND b.code = 'DEN');

INSERT INTO dim_flight_schedule (flight_id, carrier_code, flight_number, flight_date, origin_airport, destination_airport,
                                 departure_time_utc, arrival_time_utc, checkin_open_time_utc, fare_offset_cents,
                                 aircraft_type, aircraft_capacity, distance_miles, flight_status)
SELECT r.origin || '-' || r.destination || '-' || CASE t.flight_id WHEN 'F01' THEN '1' WHEN 'F02' THEN '2' ELSE '3' END,
       t.carrier_code, t.flight_number, t.flight_date, r.origin, r.destination,
       t.departure_time_utc, t.arrival_time_utc, t.checkin_open_time_utc, t.fare_offset_cents,
       t.aircraft_type, t.aircraft_capacity, r.miles, 'SCHEDULED'
  FROM pf_route r
 CROSS JOIN dim_flight_schedule t
 WHERE t.flight_id IN ('F01', 'F02', 'F03')
ON CONFLICT (flight_id) DO NOTHING;

INSERT INTO dim_seat (seat_id, flight_id, seat_number, row_number, seat_type, seat_position, seat_status)
SELECT f.flight_id || '-' || rw || l.letter, f.flight_id, rw || l.letter, rw,
       CASE WHEN rw <= 3 THEN 'EXTRA_LEGROOM' WHEN rw <= 7 THEN 'PREFERRED' ELSE 'STANDARD' END,
       CASE WHEN l.letter IN ('A','F') THEN 'WINDOW' WHEN l.letter IN ('B','E') THEN 'MIDDLE' ELSE 'AISLE' END,
       'AVAILABLE'
  FROM dim_flight_schedule f
  JOIN pf_route r ON r.origin = f.origin_airport AND r.destination = f.destination_airport
 CROSS JOIN unnest(ARRAY[1,2,3,4,5,6,7,18,19,20,21,22,23,24,25,26]) AS rw
 CROSS JOIN (VALUES ('A'),('B'),('C'),('D'),('E'),('F')) AS l(letter)
 WHERE f.flight_id LIKE '%-%-_'
ON CONFLICT (seat_id) DO NOTHING;

INSERT INTO fact_flight_campaign (flight_id, reward_budget_points, budget_reserved_points, budget_settled_points,
                                  bag_grants_total, bag_grants_remaining, assumed_cost_per_point_cents,
                                  campaign_status, updated_time_utc)
SELECT f.flight_id, 10000, 0, 0, 16, 16, 1, 'OPEN', '2027-11-01T00:00:00Z'
  FROM dim_flight_schedule f
  JOIN pf_route r ON r.origin = f.origin_airport AND r.destination = f.destination_airport
 WHERE f.flight_id LIKE '%-%-_'
ON CONFLICT (flight_id) DO NOTHING;

COMMIT;
