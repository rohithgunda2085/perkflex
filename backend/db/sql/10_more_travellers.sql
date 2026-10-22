-- Adds five travellers: Srija, Mahesh, Harshini, Manish and Rohith (synthetic data).
-- Additive only: nothing existing is changed except marking the new travellers' seats ASSIGNED.
-- Run after 01_schema.sql, 02_seed.sql and 03_functions.sql (npm run db:migrate does this).
-- Passwords use the same placeholder as the original seed; run `npm run db:seed-users` to set real ones.
BEGIN;

-- ---- Rohith's presentation flight (22 Oct 2026), same layout as F01-F03 (96 seats) ----
INSERT INTO dim_flight_schedule (flight_id, carrier_code, flight_number, flight_date, origin_airport, destination_airport, departure_time_utc, arrival_time_utc, checkin_open_time_utc, fare_offset_cents, aircraft_type, aircraft_capacity, distance_miles, flight_status) VALUES
  ('F04', 'PF', '2418', '2026-10-22', 'DAL', 'DEN', '2026-10-22T14:30:00Z', '2026-10-22T17:00:00Z', '2026-10-21T14:30:00Z', 0, '73H', 175, 651, 'SCHEDULED');

INSERT INTO dim_seat (seat_id, flight_id, seat_number, row_number, seat_type, seat_position, seat_status)
SELECT 'F04-' || r || l.letter, 'F04', r || l.letter, r,
       CASE WHEN r <= 3 THEN 'EXTRA_LEGROOM' WHEN r <= 7 THEN 'PREFERRED' ELSE 'STANDARD' END,
       CASE WHEN l.letter IN ('A','F') THEN 'WINDOW' WHEN l.letter IN ('B','E') THEN 'MIDDLE' ELSE 'AISLE' END,
       'AVAILABLE'
  FROM unnest(ARRAY[1,2,3,4,5,6,7,18,19,20,21,22,23,24,25,26]) AS r
 CROSS JOIN (VALUES ('A'),('B'),('C'),('D'),('E'),('F')) AS l(letter);

INSERT INTO fact_flight_campaign (flight_id, reward_budget_points, budget_reserved_points, budget_settled_points, bag_grants_total, bag_grants_remaining, assumed_cost_per_point_cents, campaign_status, updated_time_utc) VALUES
  ('F04', 10000, 0, 0, 16, 16, 1, 'OPEN', '2026-09-30T00:00:00Z');

-- ---- Travellers ----
INSERT INTO dim_passenger (passenger_id, rapid_rewards_account_id, passenger_name, tier_status, credit_card_type, primary_cardholder_flag, demo_story) VALUES
  ('P10', 'RR10010', 'Srija Panchagnula',    'NONE', 'PREMIER',  true,  'Premier cardmember: Preferred seat is covered once check-in opens'),
  ('P11', 'RR10011', 'Mahesh Ammanaganti',   'NONE', 'NONE',     false, 'Refundable Choice Preferred fare; needs a bag and has points to cover it'),
  ('P12', 'RR10012', 'Harshini Bhavisetty', 'NONE', 'PRIORITY', true,  'Priority cardmember: first bag and a Preferred seat now, Extra Legroom at check-in'),
  ('P13', 'RR10013', 'Manish Galigini',   'NONE', 'NONE',     false, 'Large points balance; wants Extra Legroom and can redeem for it'),
  ('P14', 'RR10014', 'Rohith Gunda',   'NONE', 'NONE',     false, 'Flight booked. Ready to make the most of every perk');

INSERT INTO dim_user_account (user_id, passenger_id, login_id, password_hash, user_role, is_active_flag, last_login_time_utc) VALUES
  ('U11', 'P10', 'srija',    'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U12', 'P11', 'mahesh',   'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U13', 'P12', 'harshini', 'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U14', 'P13', 'manish',   'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U15', 'P14', 'rohith',   'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL);

-- ---- Bookings and their seats ----
INSERT INTO fact_booking (booking_id, passenger_id, flight_id, fare_id, seat_id, booking_date_utc, booking_status, cash_total_cents, expected_bag_count, actual_bag_count, checkin_opened_time_utc, checkin_completed_time_utc, reward_release_used_flag, seat_waiver_flag, pref_seat, pref_refundable_flag, pref_flexible_flag, pref_seat_now_flag, pref_early_boarding_flag, pref_budget_cents) VALUES
  ('B10', 'P10', 'F01', 'CHOICE',           'F01-19B', '2027-11-10T15:00:00Z', 'BOOKED', 20260, 0, 0, '2027-12-15T15:30:00Z', NULL, false, false, 'ANY',   false, true,  false, false, 45000),
  ('B11', 'P11', 'F01', 'CHOICE_PREFERRED', 'F01-5A',  '2027-11-11T15:00:00Z', 'BOOKED', 24260, 1, 1, '2027-12-15T15:30:00Z', NULL, false, false, 'ANY',   true,  false, false, false, 45000),
  ('B12', 'P12', 'F01', 'CHOICE',           'F01-6A',  '2027-11-12T15:00:00Z', 'BOOKED', 20260, 1, 1, '2027-12-15T15:30:00Z', NULL, false, false, 'FRONT', false, false, false, false, 45000),
  ('B13', 'P13', 'F01', 'CHOICE',           'F01-20A', '2027-11-13T15:00:00Z', 'BOOKED', 20260, 0, 0, '2027-12-15T15:30:00Z', NULL, false, false, 'EXTRA', false, false, false, false, 45000),
  ('B14', 'P14', 'F04', 'CHOICE_EXTRA',     'F04-3A',  '2026-10-01T15:00:00Z', 'BOOKED', 28260, 0, 0, '2026-10-21T14:30:00Z', NULL, false, false, 'EXTRA', true,  false, false, false, 45000);

UPDATE dim_seat SET seat_status = 'ASSIGNED'
 WHERE seat_id IN ('F01-19B', 'F01-5A', 'F01-6A', 'F01-20A', 'F04-3A');

-- ---- Benefits each traveller already holds ----
INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code, eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity) VALUES
  ('PB16', 'B10', 'BAG1',      'CARD',  'PREMIER',          1, 'BOOKING', 0, 0, 0),
  ('PB17', 'B10', 'SEAT_PREF', 'CARD',  'PREMIER',          1, 'CHECKIN', 0, 0, 0),
  ('PB18', 'B11', 'SEAT_PREF', 'FARE',  'CHOICE_PREFERRED', 1, 'BOOKING', 1, 0, 0),
  ('PB19', 'B12', 'BAG1',      'CARD',  'PRIORITY',         1, 'BOOKING', 1, 0, 0),
  ('PB20', 'B12', 'SEAT_PREF', 'CARD',  'PRIORITY',         1, 'BOOKING', 1, 0, 0),
  ('PB21', 'B12', 'SEAT_XL',   'CARD',  'PRIORITY',         1, 'CHECKIN', 0, 0, 0),
  ('PB22', 'B14', 'BAG1',      'FARE',  'CHOICE_EXTRA',     1, 'BOOKING', 0, 0, 0),
  ('PB23', 'B14', 'BAG2',      'FARE',  'CHOICE_EXTRA',     1, 'BOOKING', 0, 0, 0),
  ('PB24', 'B14', 'SEAT_XL',   'FARE',  'CHOICE_EXTRA',     1, 'BOOKING', 1, 0, 0);

-- ---- Wallets and ledger (pending earn = fare base dollars x earning multiplier, as in the original seed) ----
INSERT INTO fact_points_wallet (passenger_id, rapid_rewards_available, rapid_rewards_pending, perkflex_available, perkflex_pending, wallet_version, updated_time_utc) VALUES
  ('P10',  4000, 1140, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P11', 15000, 1840, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P12',  9000, 1140, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P13', 25000, 1140, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P14', 12450, 2700, 0, 0, 1, '2026-09-30T00:00:00Z');

INSERT INTO fact_point_transaction (point_transaction_id, passenger_id, booking_id, perkflex_transaction_id, point_type, transaction_type, points_delta, point_status, tqp_eligible_flag, transaction_time_utc, reversal_transaction_id, source_point_transaction_id) VALUES
  ('PT019', 'P10', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 4000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT020', 'P11', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                15000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT021', 'P12', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 9000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT022', 'P13', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                25000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT023', 'P14', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                12450, 'AVAILABLE', false, '2026-09-30T00:00:00Z', NULL, NULL),
  ('PT024', 'P10', 'B10', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1140, 'PENDING',   true,  '2027-11-10T15:00:00Z', NULL, NULL),
  ('PT025', 'P11', 'B11', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1840, 'PENDING',   true,  '2027-11-11T15:00:00Z', NULL, NULL),
  ('PT026', 'P12', 'B12', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1140, 'PENDING',   true,  '2027-11-12T15:00:00Z', NULL, NULL),
  ('PT027', 'P13', 'B13', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1140, 'PENDING',   true,  '2027-11-13T15:00:00Z', NULL, NULL),
  ('PT028', 'P14', 'B14', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  2700, 'PENDING',   true,  '2026-10-01T15:00:00Z', NULL, NULL);

COMMIT;
