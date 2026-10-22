-- Adds eight travellers (synthetic data) on flights F02 and F03, so every kind of traveller can be demonstrated:
--   P21 Nadia Brooks   new traveller, no status, no card, Basic fare
--   P22 Owen Patel     Silver
--   P23 Priya Nair     Gold
--   P24 Marcus Reed    Platinum
--   P25 Elena Cruz     Rapid Rewards Plus credit card (Basic fare: the card supplies the first bag)
--   P26 Tyrone Hayes   Rapid Rewards Premier credit card
--   P27 Sofia Marin    Rapid Rewards Priority credit card
--   P28 Daniel Kim     Silver status and a Priority credit card together
-- Additive only. Passwords use the seed placeholder; run `npm run db:seed-users` to set real ones.
-- The demo snapshot is brought up to date too, so "Reset demo" keeps these travellers' trips.
BEGIN;

INSERT INTO dim_passenger (passenger_id, rapid_rewards_account_id, passenger_name, tier_status, credit_card_type, primary_cardholder_flag, demo_story) VALUES
  ('P21', 'RR10021', 'Nadia Brooks', 'NONE',     'NONE',     false, 'New traveller on a Basic fare: no status and no card, so every benefit is something to buy'),
  ('P22', 'RR10022', 'Owen Patel',   'SILVER',   'NONE',     false, 'Silver member: one bag and a Preferred seat are covered, Extra Legroom opens at check-in'),
  ('P23', 'RR10023', 'Priya Nair',   'GOLD',     'NONE',     false, 'Gold member on a Choice Preferred fare: two bags and Extra Legroom are covered, one bag planned'),
  ('P24', 'RR10024', 'Marcus Reed',  'PLATINUM', 'NONE',     false, 'Platinum member on a Choice Extra fare: three bags and Extra Legroom are covered, two bags planned'),
  ('P25', 'RR10025', 'Elena Cruz',   'NONE',     'PLUS',     true,  'Rapid Rewards Plus cardmember on a Basic fare: the card covers the first bag'),
  ('P26', 'RR10026', 'Tyrone Hayes', 'NONE',     'PREMIER',  true,  'Rapid Rewards Premier cardmember on a Choice Preferred fare: the card covers a bag, the fare a Preferred seat'),
  ('P27', 'RR10027', 'Sofia Marin',  'NONE',     'PRIORITY', true,  'Rapid Rewards Priority cardmember: first bag and a Preferred seat now, Extra Legroom at check-in'),
  ('P28', 'RR10028', 'Daniel Kim',   'SILVER',   'PRIORITY', true,  'Silver member who also holds a Priority card: tier and card benefits together, one bag planned');

INSERT INTO dim_user_account (user_id, passenger_id, login_id, password_hash, user_role, is_active_flag, last_login_time_utc) VALUES
  ('U22', 'P21', 'nadia.brooks', 'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U23', 'P22', 'owen.patel',   'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U24', 'P23', 'priya.nair',   'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U25', 'P24', 'marcus.reed',  'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U26', 'P25', 'elena.cruz',   'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U27', 'P26', 'tyrone.hayes', 'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U28', 'P27', 'sofia.marin',  'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U29', 'P28', 'daniel.kim',   'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL);

-- Cash total = fare base + the flight's fare offset (F02 +$20, F03 +$35) + $12.60 tax
INSERT INTO fact_booking (booking_id, passenger_id, flight_id, fare_id, seat_id, booking_date_utc, booking_status, cash_total_cents, expected_bag_count, actual_bag_count, checkin_opened_time_utc, checkin_completed_time_utc, reward_release_used_flag, seat_waiver_flag, pref_seat, pref_refundable_flag, pref_flexible_flag, pref_seat_now_flag, pref_early_boarding_flag, pref_budget_cents, confirmation_code) VALUES
  ('B20', 'P21', 'F02', 'BASIC',            'F02-18A', '2027-11-19T15:00:00Z', 'BOOKED', 18260, 0, 0, '2027-12-15T18:15:00Z', NULL, false, false, 'ANY',   false, false, false, false, 45000, 'N7B3QK'),
  ('B21', 'P22', 'F02', 'CHOICE',           'F02-4A',  '2027-11-19T16:00:00Z', 'BOOKED', 22260, 1, 1, '2027-12-15T18:15:00Z', NULL, false, false, 'FRONT', false, false, false, false, 45000, 'O2W9PT'),
  ('B22', 'P23', 'F02', 'CHOICE_PREFERRED', 'F02-1A',  '2027-11-20T15:00:00Z', 'BOOKED', 26260, 2, 1, '2027-12-15T18:15:00Z', NULL, false, false, 'EXTRA', true,  false, false, false, 45000, 'P8N4RV'),
  ('B23', 'P24', 'F03', 'CHOICE_EXTRA',     'F03-1A',  '2027-11-20T16:00:00Z', 'BOOKED', 31760, 3, 2, '2027-12-15T23:40:00Z', NULL, false, false, 'EXTRA', true,  false, false, false, 45000, 'M5R7XD'),
  ('B24', 'P25', 'F03', 'BASIC',            'F03-18A', '2027-11-21T15:00:00Z', 'BOOKED', 19760, 1, 1, '2027-12-15T23:40:00Z', NULL, false, false, 'ANY',   false, false, false, false, 45000, 'E3C6ZL'),
  ('B25', 'P26', 'F03', 'CHOICE_PREFERRED', 'F03-4A',  '2027-11-21T16:00:00Z', 'BOOKED', 27760, 1, 1, '2027-12-15T23:40:00Z', NULL, false, false, 'ANY',   true,  false, false, false, 45000, 'T9H2YF'),
  ('B26', 'P27', 'F03', 'CHOICE',           'F03-4B',  '2027-11-22T15:00:00Z', 'BOOKED', 23760, 1, 1, '2027-12-15T23:40:00Z', NULL, false, false, 'FRONT', false, false, false, false, 45000, 'S4M8JA'),
  ('B27', 'P28', 'F03', 'CHOICE',           'F03-4C',  '2027-11-22T16:00:00Z', 'BOOKED', 23760, 1, 1, '2027-12-15T23:40:00Z', NULL, false, false, 'FRONT', false, false, false, false, 45000, 'D6K1WU');

UPDATE dim_seat SET seat_status = 'ASSIGNED'
 WHERE seat_id IN ('F02-18A', 'F02-4A', 'F02-1A', 'F03-1A', 'F03-18A', 'F03-4A', 'F03-4B', 'F03-4C');

-- Benefits each traveller holds (one effective row per bag number and seat, from the source that supplies it)
INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code, eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity) VALUES
  -- Nadia: nothing is included
  -- Owen (Silver): first bag and Preferred seat now, Extra Legroom at check-in
  ('PB50', 'B21', 'BAG1',      'TIER', 'SILVER',           1, 'BOOKING', 1, 0, 0),
  ('PB51', 'B21', 'SEAT_PREF', 'TIER', 'SILVER',           1, 'BOOKING', 1, 0, 0),
  ('PB52', 'B21', 'SEAT_XL',   'TIER', 'SILVER',           1, 'CHECKIN', 0, 0, 0),
  -- Priya (Gold): two bags (one used), Extra Legroom seat
  ('PB53', 'B22', 'BAG1',      'TIER', 'GOLD',             1, 'BOOKING', 1, 0, 0),
  ('PB54', 'B22', 'BAG2',      'TIER', 'GOLD',             1, 'BOOKING', 0, 0, 0),
  ('PB55', 'B22', 'SEAT_XL',   'TIER', 'GOLD',             1, 'BOOKING', 1, 0, 0),
  -- Marcus (Platinum): three bags (two used), Extra Legroom seat
  ('PB56', 'B23', 'BAG1',      'TIER', 'PLATINUM',         1, 'BOOKING', 1, 0, 0),
  ('PB57', 'B23', 'BAG2',      'TIER', 'PLATINUM',         1, 'BOOKING', 1, 0, 0),
  ('PB58', 'B23', 'BAG3',      'TIER', 'PLATINUM',         1, 'BOOKING', 0, 0, 0),
  ('PB59', 'B23', 'SEAT_XL',   'TIER', 'PLATINUM',         1, 'BOOKING', 1, 0, 0),
  -- Elena (Plus card): first bag
  ('PB60', 'B24', 'BAG1',      'CARD', 'PLUS',             1, 'BOOKING', 1, 0, 0),
  -- Tyrone (Premier card, Choice Preferred): card bag; the fare supplies the Preferred seat
  ('PB61', 'B25', 'BAG1',      'CARD', 'PREMIER',          1, 'BOOKING', 1, 0, 0),
  ('PB62', 'B25', 'SEAT_PREF', 'FARE', 'CHOICE_PREFERRED', 1, 'BOOKING', 1, 0, 0),
  -- Sofia (Priority card): first bag, Preferred seat now, Extra Legroom at check-in
  ('PB63', 'B26', 'BAG1',      'CARD', 'PRIORITY',         1, 'BOOKING', 1, 0, 0),
  ('PB64', 'B26', 'SEAT_PREF', 'CARD', 'PRIORITY',         1, 'BOOKING', 1, 0, 0),
  ('PB65', 'B26', 'SEAT_XL',   'CARD', 'PRIORITY',         1, 'CHECKIN', 0, 0, 0),
  -- Daniel (Silver and a Priority card): the Silver tier is the stronger source for each benefit
  ('PB66', 'B27', 'BAG1',      'TIER', 'SILVER',           1, 'BOOKING', 1, 0, 0),
  ('PB67', 'B27', 'SEAT_PREF', 'TIER', 'SILVER',           1, 'BOOKING', 1, 0, 0),
  ('PB68', 'B27', 'SEAT_XL',   'TIER', 'SILVER',           1, 'CHECKIN', 0, 0, 0);

-- Wallets and ledger (pending earn = fare base dollars x earning multiplier, as in the original seed)
INSERT INTO fact_points_wallet (passenger_id, rapid_rewards_available, rapid_rewards_pending, perkflex_available, perkflex_pending, wallet_version, updated_time_utc) VALUES
  ('P21',  1500,  300, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P22',  6000, 1140, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P23', 14000, 1840, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P24', 40000, 2700, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P25',  3200,  300, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P26',  9500, 1840, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P27', 22000, 1140, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P28', 11000, 1140, 0, 0, 1, '2027-11-01T00:00:00Z');

INSERT INTO fact_point_transaction (point_transaction_id, passenger_id, booking_id, perkflex_transaction_id, point_type, transaction_type, points_delta, point_status, tqp_eligible_flag, transaction_time_utc, reversal_transaction_id, source_point_transaction_id) VALUES
  ('PT040', 'P21', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 1500, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT041', 'P22', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 6000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT042', 'P23', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                14000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT043', 'P24', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                40000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT044', 'P25', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 3200, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT045', 'P26', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 9500, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT046', 'P27', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                22000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT047', 'P28', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                11000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT048', 'P21', 'B20', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',   300, 'PENDING',   true,  '2027-11-19T15:00:00Z', NULL, NULL),
  ('PT049', 'P22', 'B21', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1140, 'PENDING',   true,  '2027-11-19T16:00:00Z', NULL, NULL),
  ('PT050', 'P23', 'B22', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1840, 'PENDING',   true,  '2027-11-20T15:00:00Z', NULL, NULL),
  ('PT051', 'P24', 'B23', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  2700, 'PENDING',   true,  '2027-11-20T16:00:00Z', NULL, NULL),
  ('PT052', 'P25', 'B24', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',   300, 'PENDING',   true,  '2027-11-21T15:00:00Z', NULL, NULL),
  ('PT053', 'P26', 'B25', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1840, 'PENDING',   true,  '2027-11-21T16:00:00Z', NULL, NULL),
  ('PT054', 'P27', 'B26', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1140, 'PENDING',   true,  '2027-11-22T15:00:00Z', NULL, NULL),
  ('PT055', 'P28', 'B27', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1140, 'PENDING',   true,  '2027-11-22T16:00:00Z', NULL, NULL);

-- Bring the demo snapshot up to date (when there is one), so "Reset demo" keeps these trips.
DO $$
DECLARE cols text;
BEGIN
  IF to_regclass('demo_seed_fact_booking') IS NULL THEN RETURN; END IF;
  cols := pf_demo_columns('fact_booking');
  EXECUTE format('INSERT INTO demo_seed_fact_booking (%s) SELECT %s FROM fact_booking WHERE booking_id BETWEEN ''B20'' AND ''B27''', cols, cols);
  cols := pf_demo_columns('fact_passenger_benefit');
  EXECUTE format('INSERT INTO demo_seed_fact_passenger_benefit (%s) SELECT %s FROM fact_passenger_benefit WHERE booking_id BETWEEN ''B20'' AND ''B27''', cols, cols);
  cols := pf_demo_columns('fact_points_wallet');
  EXECUTE format('INSERT INTO demo_seed_fact_points_wallet (%s) SELECT %s FROM fact_points_wallet WHERE passenger_id BETWEEN ''P21'' AND ''P28''', cols, cols);
  cols := pf_demo_columns('fact_point_transaction');
  EXECUTE format('INSERT INTO demo_seed_fact_point_transaction (%s) SELECT %s FROM fact_point_transaction WHERE point_transaction_id BETWEEN ''PT040'' AND ''PT055''', cols, cols);
  UPDATE demo_seed_dim_seat SET seat_status = 'ASSIGNED'
   WHERE seat_id IN ('F02-18A', 'F02-4A', 'F02-1A', 'F03-1A', 'F03-18A', 'F03-4A', 'F03-4B', 'F03-4C');
END $$;

COMMIT;
