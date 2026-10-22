-- The PerkFlex demo story, run through the transaction functions (see 03_functions.sql).
-- Run on a freshly seeded database. p_now is a time after check-in opens (2027-12-15 15:30 UTC).
\set ON_ERROR_STOP on
\pset null '(null)'
\set now '2027-12-15 16:00:00+00'
\echo '--- Maya (P01) sets 0 bags and releases an unused bag: +800 PerkFlex points, pending'
SELECT pf_set_bags('P01','B01',0,:'now');
SELECT pf_release_bag('P01','B01','IDEMP-B01-1',:'now');
\echo '--- Retrying the same request returns the first result and changes nothing'
SELECT pf_release_bag('P01','B01','IDEMP-B01-1',:'now');
\echo '--- Neha (P03) releases Preferred seat 4A for a Standard seat: +700 pending'
SELECT pf_release_seat('P03','B03','IDEMP-B03-1',:'now');
\echo '--- Dev (P04) buys a Preferred seat with 2,200 Rapid Rewards points'
SELECT pf_redeem_seat('P04','B04','PREFERRED','IDEMP-B04-1',:'now');
\echo '--- Ravi (P02) buys a first checked bag for 3,000 points'
SELECT pf_redeem_bag('P02','B02','IDEMP-B02-1',:'now');
\echo '--- Alex (P09) has no points: the purchase fails and nothing changes'
SELECT pf_redeem_bag('P09','B09','IDEMP-B09-2',:'now');
\echo '--- Kabir (P07) checks 2 bags and releases the unused third bag'
SELECT pf_release_bag('P07','B07','IDEMP-B07-1',:'now');
\echo '--- Everyone completes check-in (PerkFlex locks)'
SELECT pf_complete_checkin(passenger_id, booking_id, :'now') FROM fact_booking WHERE flight_id = 'F01' ORDER BY booking_id;
\echo '--- Airline completes the flight: pending points post exactly once'
SELECT pf_complete_flight('F01', '2027-12-16 18:30:00+00');
\echo '--- Completing it again posts nothing'
SELECT pf_complete_flight('F01', '2027-12-16 18:31:00+00');
\echo '--- Wallets after the flight'
SELECT passenger_id, rapid_rewards_available AS rr, rapid_rewards_pending AS rr_pending, perkflex_available AS pf, perkflex_pending AS pf_pending
FROM fact_points_wallet ORDER BY passenger_id;
