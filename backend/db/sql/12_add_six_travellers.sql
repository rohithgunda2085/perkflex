-- Adds six travellers (synthetic data): Sean Lynch (Platinum), Lu Truong (Gold), Justin Bundick (Gold),
-- Michael Rankin (new traveller, no booking), Michael Hanna (Silver) and Dee Ann Carlin (Silver).
-- Additive only. Benefit rows hold one effective row per bag ordinal / seat (pf_bag_allowance sums them).
-- Passwords use the seed placeholder; run `npm run db:seed-users` to set real ones.
BEGIN;

INSERT INTO dim_passenger (passenger_id, rapid_rewards_account_id, passenger_name, tier_status, credit_card_type, primary_cardholder_flag, demo_story) VALUES
  ('P15', 'RR10015', 'Sean Lynch',     'PLATINUM', 'NONE', false, 'Platinum member: three bags and Extra Legroom are covered, only one bag planned'),
  ('P16', 'RR10016', 'Lu Truong',      'GOLD',     'NONE', false, 'Gold member on a refundable Choice Preferred fare: two bags and Extra Legroom are covered'),
  ('P17', 'RR10017', 'Justin Bundick', 'GOLD',     'NONE', false, 'Gold member on a Basic fare: Gold supplies two bags and Extra Legroom, one bag planned'),
  ('P18', 'RR10018', 'Michael Rankin', 'NONE',     'NONE', false, 'New traveller with no trip yet: starts at Book a flight after login'),
  ('P19', 'RR10019', 'Michael Hanna',  'SILVER',   'NONE', false, 'Silver member: one bag and a front seat are covered, a second bag to add'),
  ('P20', 'RR10020', 'Dee Ann Carlin', 'SILVER',   'NONE', false, 'Silver member on a Basic fare: the tier covers a bag and a front seat');

INSERT INTO dim_user_account (user_id, passenger_id, login_id, password_hash, user_role, is_active_flag, last_login_time_utc) VALUES
  ('U16', 'P15', 'sean.lynch',     'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U17', 'P16', 'lu.truong',      'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U18', 'P17', 'justin.bundick', 'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U19', 'P18', 'michael.rankin', 'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U20', 'P19', 'michael.hanna',  'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL),
  ('U21', 'P20', 'deeann.carlin',  'DEMO-HASH-REPLACE-AT-DEPLOY', 'PASSENGER', true, NULL);

-- Bookings (none for Michael Rankin, P18)
INSERT INTO fact_booking (booking_id, passenger_id, flight_id, fare_id, seat_id, booking_date_utc, booking_status, cash_total_cents, expected_bag_count, actual_bag_count, checkin_opened_time_utc, checkin_completed_time_utc, reward_release_used_flag, seat_waiver_flag, pref_seat, pref_refundable_flag, pref_flexible_flag, pref_seat_now_flag, pref_early_boarding_flag, pref_budget_cents) VALUES
  ('B15', 'P15', 'F01', 'CHOICE',           'F01-1D', '2027-11-14T15:00:00Z', 'BOOKED', 20260, 1, 1, '2027-12-15T15:30:00Z', NULL, false, false, 'EXTRA', false, false, false, false, 45000),
  ('B16', 'P16', 'F01', 'CHOICE_PREFERRED', 'F01-1E', '2027-11-15T15:00:00Z', 'BOOKED', 24260, 2, 2, '2027-12-15T15:30:00Z', NULL, false, false, 'EXTRA', true,  false, false, false, 45000),
  ('B17', 'P17', 'F01', 'BASIC',            'F01-2C', '2027-11-16T15:00:00Z', 'BOOKED', 16260, 1, 1, '2027-12-15T15:30:00Z', NULL, false, false, 'EXTRA', false, false, false, false, 45000),
  ('B18', 'P19', 'F01', 'CHOICE',           'F01-6B', '2027-11-17T15:00:00Z', 'BOOKED', 20260, 2, 2, '2027-12-15T15:30:00Z', NULL, false, false, 'FRONT', false, false, false, false, 45000),
  ('B19', 'P20', 'F01', 'BASIC',            'F01-7B', '2027-11-18T15:00:00Z', 'BOOKED', 16260, 1, 1, '2027-12-15T15:30:00Z', NULL, false, false, 'FRONT', false, false, false, false, 45000);

UPDATE dim_seat SET seat_status = 'ASSIGNED'
 WHERE seat_id IN ('F01-1D', 'F01-1E', 'F01-2C', 'F01-6B', 'F01-7B');

INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code, eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity) VALUES
  -- Sean (Platinum): three bags, one used; Extra Legroom seat
  ('PB34', 'B15', 'BAG1',      'TIER', 'PLATINUM', 1, 'BOOKING', 1, 0, 0),
  ('PB35', 'B15', 'BAG2',      'TIER', 'PLATINUM', 1, 'BOOKING', 0, 0, 0),
  ('PB36', 'B15', 'BAG3',      'TIER', 'PLATINUM', 1, 'BOOKING', 0, 0, 0),
  ('PB37', 'B15', 'SEAT_XL',   'TIER', 'PLATINUM', 1, 'BOOKING', 1, 0, 0),
  -- Lu (Gold): two bags used; Extra Legroom seat
  ('PB38', 'B16', 'BAG1',      'TIER', 'GOLD',     1, 'BOOKING', 1, 0, 0),
  ('PB39', 'B16', 'BAG2',      'TIER', 'GOLD',     1, 'BOOKING', 1, 0, 0),
  ('PB40', 'B16', 'SEAT_XL',   'TIER', 'GOLD',     1, 'BOOKING', 1, 0, 0),
  -- Justin (Gold): two bags, one used; Extra Legroom seat
  ('PB41', 'B17', 'BAG1',      'TIER', 'GOLD',     1, 'BOOKING', 1, 0, 0),
  ('PB42', 'B17', 'BAG2',      'TIER', 'GOLD',     1, 'BOOKING', 0, 0, 0),
  ('PB43', 'B17', 'SEAT_XL',   'TIER', 'GOLD',     1, 'BOOKING', 1, 0, 0),
  -- Michael Hanna (Silver): first bag and Preferred seat now, Extra Legroom at check-in
  ('PB44', 'B18', 'BAG1',      'TIER', 'SILVER',   1, 'BOOKING', 1, 0, 0),
  ('PB45', 'B18', 'SEAT_PREF', 'TIER', 'SILVER',   1, 'BOOKING', 1, 0, 0),
  ('PB46', 'B18', 'SEAT_XL',   'TIER', 'SILVER',   1, 'CHECKIN', 0, 0, 0),
  -- Dee Ann (Silver): same tier benefits on a Basic fare
  ('PB47', 'B19', 'BAG1',      'TIER', 'SILVER',   1, 'BOOKING', 1, 0, 0),
  ('PB48', 'B19', 'SEAT_PREF', 'TIER', 'SILVER',   1, 'BOOKING', 1, 0, 0),
  ('PB49', 'B19', 'SEAT_XL',   'TIER', 'SILVER',   1, 'CHECKIN', 0, 0, 0);

-- Wallets (Michael Rankin starts with nothing) and ledger (pending earn = fare base dollars x multiplier)
INSERT INTO fact_points_wallet (passenger_id, rapid_rewards_available, rapid_rewards_pending, perkflex_available, perkflex_pending, wallet_version, updated_time_utc) VALUES
  ('P15', 30000, 1140, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P16', 18000, 1840, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P17',  7000,  300, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P18',     0,    0, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P19',  8000, 1140, 0, 0, 1, '2027-11-01T00:00:00Z'),
  ('P20',  2500,  300, 0, 0, 1, '2027-11-01T00:00:00Z');

INSERT INTO fact_point_transaction (point_transaction_id, passenger_id, booking_id, perkflex_transaction_id, point_type, transaction_type, points_delta, point_status, tqp_eligible_flag, transaction_time_utc, reversal_transaction_id, source_point_transaction_id) VALUES
  ('PT029', 'P15', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                30000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT030', 'P16', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                18000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT031', 'P17', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 7000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT032', 'P18', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                    0, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT033', 'P19', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 8000, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT034', 'P20', NULL,  NULL, 'RAPID_REWARDS', 'SEED',                 2500, 'AVAILABLE', false, '2027-11-01T00:00:00Z', NULL, NULL),
  ('PT035', 'P15', 'B15', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1140, 'PENDING',   true,  '2027-11-14T15:00:00Z', NULL, NULL),
  ('PT036', 'P16', 'B16', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1840, 'PENDING',   true,  '2027-11-15T15:00:00Z', NULL, NULL),
  ('PT037', 'P17', 'B17', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',   300, 'PENDING',   true,  '2027-11-16T15:00:00Z', NULL, NULL),
  ('PT038', 'P19', 'B18', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',  1140, 'PENDING',   true,  '2027-11-17T15:00:00Z', NULL, NULL),
  ('PT039', 'P20', 'B19', NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_PENDING',   300, 'PENDING',   true,  '2027-11-18T15:00:00Z', NULL, NULL);

COMMIT;
