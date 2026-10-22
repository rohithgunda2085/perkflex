-- PerkFlex queries for every table (PostgreSQL / psql).
-- Run after 01_schema.sql, 02_seed.sql and 03_functions.sql:  psql -d perkflex -f 04_queries.sql
-- Parameters are psql variables. In the application use $1, $2 ... parameters instead of :'name'.
\set ON_ERROR_STOP on
\pset null '(null)'
\set passenger 'P01'
\set booking   'B01'
\set flight    'F01'
\set login     'maya'
\set origin    'DAL'
\set dest      'DEN'
\set depdate   '2027-12-16'
\set now       '2027-12-15 16:00:00+00'
\set need_refundable 'true'
\set need_flexible   'false'

\echo '=== DIM_USER_ACCOUNT ==='
\echo '-- Login lookup (the API verifies password_hash, then issues a signed session token)'
SELECT user_id, passenger_id, user_role, password_hash
FROM dim_user_account WHERE login_id = :'login' AND is_active_flag;
\echo '-- Airline admin logins'
SELECT user_id, login_id, last_login_time_utc FROM dim_user_account WHERE user_role = 'AIRLINE_ADMIN';
\echo '-- Record a successful sign-in (statement, not run here):'
\echo '--   UPDATE dim_user_account SET last_login_time_utc = now() WHERE user_id = :''user_id'';'

\echo '=== DIM_PASSENGER ==='
\echo '-- Traveller profile with wallet and current booking (the "me" screen)'
SELECT p.passenger_id, p.passenger_name, CASE p.tier_status WHEN 'NONE' THEN 'Member' ELSE initcap(p.tier_status) END AS tier,
       p.credit_card_type, w.rapid_rewards_available, w.rapid_rewards_pending, w.perkflex_available, w.perkflex_pending,
       b.booking_id, b.booking_status, s.seat_number
FROM dim_passenger p
JOIN fact_points_wallet w USING (passenger_id)
LEFT JOIN fact_booking b ON b.passenger_id = p.passenger_id AND b.booking_status IN ('BOOKED','CHECKED_IN')
LEFT JOIN dim_seat s ON s.seat_id = b.seat_id
WHERE p.passenger_id = :'passenger';
\echo '-- All travellers with tier or card benefits'
SELECT passenger_id, passenger_name, tier_status, credit_card_type FROM dim_passenger
WHERE tier_status <> 'NONE' OR credit_card_type <> 'NONE' ORDER BY passenger_id;

\echo '=== DIM_FLIGHT_SCHEDULE ==='
\echo '-- Flight search by route and date, with the lowest fare'
SELECT f.flight_id, f.carrier_code || f.flight_number AS flight, f.origin_airport, f.destination_airport,
       f.departure_time_utc, f.arrival_time_utc,
       round(MIN(fa.base_fare_cents + f.fare_offset_cents + fa.tax_cents) / 100.0, 2) AS lowest_total_usd,
       (SELECT count(*) FROM dim_seat s WHERE s.flight_id = f.flight_id AND s.seat_status <> 'ASSIGNED') AS seats_left
FROM dim_flight_schedule f CROSS JOIN dim_fare fa
WHERE f.origin_airport = :'origin' AND f.destination_airport = :'dest' AND f.flight_date = :'depdate'::date AND f.flight_status = 'SCHEDULED'
GROUP BY f.flight_id ORDER BY f.departure_time_utc;
\echo '-- Flights where web check-in is open at the chosen time'
SELECT flight_id, carrier_code || flight_number AS flight, checkin_open_time_utc, departure_time_utc
FROM dim_flight_schedule WHERE :'now'::timestamptz BETWEEN checkin_open_time_utc AND departure_time_utc AND flight_status = 'SCHEDULED';

\echo '=== DIM_FARE ==='
\echo '-- The four fares for a flight: price, benefits and flight points earned'
SELECT fa.fare_id, fa.fare_name, round((fa.base_fare_cents + f.fare_offset_cents + fa.tax_cents) / 100.0, 2) AS total_usd,
       fa.included_bags, fa.refundable_flag, fa.change_allowed_flag, fa.seat_access,
       ((fa.base_fare_cents + f.fare_offset_cents) / 100) * fa.earning_multiplier AS rapid_rewards_points_earned
FROM dim_fare fa CROSS JOIN dim_flight_schedule f WHERE f.flight_id = :'flight' ORDER BY fa.base_fare_cents;
\echo '-- Cheapest fare that meets the traveller''s needs (fare recommendation)'
SELECT fa.fare_id, fa.fare_name, round((fa.base_fare_cents + f.fare_offset_cents + fa.tax_cents) / 100.0, 2) AS total_usd
FROM dim_fare fa CROSS JOIN dim_flight_schedule f
WHERE f.flight_id = :'flight' AND (NOT :need_refundable OR fa.refundable_flag) AND (NOT :need_flexible OR fa.change_allowed_flag)
ORDER BY fa.base_fare_cents LIMIT 1;

\echo '=== DIM_BENEFIT ==='
\echo '-- Price list: points earned for releasing, points to buy, cash price at booking'
SELECT benefit_id, benefit_name, perkflex_release_points AS release_reward, perkflex_redeem_points AS redeem_price,
       round(cash_addon_cents / 100.0, 2) AS cash_addon_usd, release_eligible_flag
FROM dim_benefit ORDER BY benefit_type, bag_ordinal, seat_class;

\echo '=== DIM_SEAT ==='
\echo '-- Free seats by cabin, front to back (the order offers use)'
SELECT seat_type, seat_number, seat_position, seat_status FROM dim_seat
WHERE flight_id = :'flight' AND seat_status IN ('AVAILABLE','RELEASED')
ORDER BY CASE seat_type WHEN 'EXTRA_LEGROOM' THEN 1 WHEN 'PREFERRED' THEN 2 ELSE 3 END, row_number, seat_number LIMIT 10;
\echo '-- Inventory by cabin and status'
SELECT seat_type, count(*) FILTER (WHERE seat_status = 'AVAILABLE') AS available,
       count(*) FILTER (WHERE seat_status = 'ASSIGNED') AS assigned, count(*) FILTER (WHERE seat_status = 'RELEASED') AS released
FROM dim_seat WHERE flight_id = :'flight' GROUP BY seat_type ORDER BY seat_type;
\echo '-- Seat map with the traveller in each assigned seat (first rows)'
SELECT s.seat_number, s.seat_type, p.passenger_name
FROM dim_seat s LEFT JOIN fact_booking b ON b.seat_id = s.seat_id AND b.booking_status IN ('BOOKED','CHECKED_IN')
LEFT JOIN dim_passenger p ON p.passenger_id = b.passenger_id
WHERE s.flight_id = :'flight' AND s.row_number <= 4 ORDER BY s.row_number, s.seat_number;

\echo '=== FACT_BOOKING ==='
\echo '-- Booking detail (trip card and boarding pass)'
SELECT b.booking_id, p.passenger_name, f.carrier_code || f.flight_number AS flight, f.origin_airport || ' > ' || f.destination_airport AS route,
       f.departure_time_utc, fa.fare_name, s.seat_number, s.seat_type, b.booking_status, round(b.cash_total_cents / 100.0, 2) AS cash_total_usd,
       b.expected_bag_count, b.actual_bag_count
FROM fact_booking b JOIN dim_passenger p USING (passenger_id) JOIN dim_flight_schedule f USING (flight_id)
JOIN dim_fare fa USING (fare_id) LEFT JOIN dim_seat s ON s.seat_id = b.seat_id WHERE b.booking_id = :'booking';
\echo '-- My bookings'
SELECT booking_id, flight_id, fare_id, booking_status FROM fact_booking WHERE passenger_id = :'passenger' ORDER BY booking_date_utc DESC;
\echo '-- Flight manifest counts by status'
SELECT booking_status, count(*) FROM fact_booking WHERE flight_id = :'flight' GROUP BY booking_status ORDER BY booking_status;

\echo '=== FACT_PASSENGER_BENEFIT ==='
\echo '-- Where each effective benefit comes from ("Already yours: ...")'
SELECT pb.booking_id, d.benefit_name, pb.benefit_source, pb.source_code, pb.available_from,
       pb.eligible_quantity + pb.granted_quantity - pb.released_quantity AS effective, pb.used_quantity, pb.released_quantity
FROM fact_passenger_benefit pb JOIN dim_benefit d USING (benefit_id) WHERE pb.booking_id = :'booking' ORDER BY d.benefit_type, d.bag_ordinal;
\echo '-- Bag allowance versus bags being checked (unused > 0 means a release offer)'
SELECT b.booking_id, pf_bag_allowance(b.booking_id) AS bag_allowance, COALESCE(b.actual_bag_count, b.expected_bag_count) AS bags_checking,
       pf_bag_allowance(b.booking_id) - COALESCE(b.actual_bag_count, b.expected_bag_count) AS unused
FROM fact_booking b WHERE b.flight_id = :'flight' ORDER BY b.booking_id;

\echo '=== FACT_FLIGHT_CAMPAIGN ==='
\echo '-- Reward budget meter (Airline view)'
SELECT c.flight_id, c.reward_budget_points, c.budget_settled_points AS settled, c.budget_reserved_points AS reserved,
       c.budget_remaining_points AS remaining,
       round(100.0 * (c.budget_settled_points + c.budget_reserved_points) / NULLIF(c.reward_budget_points, 0), 1) AS pct_used,
       round((c.reward_budget_points * c.assumed_cost_per_point_cents) / 100.0, 2) AS budget_usd, c.bag_grants_remaining, c.bag_grants_total, c.campaign_status
FROM fact_flight_campaign c ORDER BY c.flight_id;

\echo '=== FACT_POINTS_WALLET ==='
\echo '-- Balances shown on the site'
SELECT passenger_id, rapid_rewards_available, rapid_rewards_pending, perkflex_available, perkflex_pending, total_available_for_perkflex
FROM fact_points_wallet WHERE passenger_id = :'passenger';
\echo '-- Reconciliation: wallet must equal the ledger (no rows = healthy)'
WITH l AS (
  SELECT passenger_id,
    COALESCE(sum(points_delta) FILTER (WHERE point_type = 'RAPID_REWARDS' AND point_status IN ('AVAILABLE','POSTED')), 0) AS rr_av,
    COALESCE(sum(points_delta) FILTER (WHERE point_type = 'PERKFLEX'      AND point_status IN ('AVAILABLE','POSTED')), 0) AS pf_av,
    COALESCE(sum(points_delta) FILTER (WHERE point_type = 'RAPID_REWARDS' AND point_status = 'PENDING'
        AND NOT EXISTS (SELECT 1 FROM fact_point_transaction x WHERE x.source_point_transaction_id = t.point_transaction_id)), 0) AS rr_pe,
    COALESCE(sum(points_delta) FILTER (WHERE point_type = 'PERKFLEX'      AND point_status = 'PENDING'
        AND NOT EXISTS (SELECT 1 FROM fact_point_transaction x WHERE x.source_point_transaction_id = t.point_transaction_id)), 0) AS pf_pe
  FROM fact_point_transaction t GROUP BY passenger_id)
SELECT w.passenger_id, w.rapid_rewards_available, l.rr_av, w.rapid_rewards_pending, l.rr_pe,
       w.perkflex_available, l.pf_av, w.perkflex_pending, l.pf_pe
FROM fact_points_wallet w JOIN l USING (passenger_id)
WHERE (w.rapid_rewards_available, w.rapid_rewards_pending, w.perkflex_available, w.perkflex_pending) IS DISTINCT FROM (l.rr_av, l.rr_pe, l.pf_av, l.pf_pe);

\echo '=== FACT_PERKFLEX_TRANSACTION ==='
\echo '-- PerkFlex offers for a booking, computed live (nothing is stored until a traveller opens or accepts one)'
WITH b AS (SELECT * FROM fact_booking WHERE booking_id = :'booking'),
     cur AS (SELECT s.* FROM dim_seat s JOIN b ON s.seat_id = b.seat_id),
     w AS (SELECT * FROM fact_points_wallet WHERE passenger_id = :'passenger'),
     c AS (SELECT c.* FROM fact_flight_campaign c JOIN b USING (flight_id)),
     allow AS (SELECT pf_bag_allowance((SELECT booking_id FROM b)) AS n)
SELECT 'RELEASE' AS action, d.benefit_id, d.benefit_name, d.perkflex_release_points AS points, 'earn (pending until you fly)' AS note
  FROM dim_benefit d, b, allow, c
 WHERE d.benefit_type = 'BAG' AND d.bag_ordinal = allow.n AND allow.n > COALESCE(b.actual_bag_count, b.expected_bag_count)
   AND NOT b.reward_release_used_flag AND c.budget_remaining_points >= d.perkflex_release_points
UNION ALL
SELECT 'RELEASE', d.benefit_id, d.benefit_name || ' to Standard seat', d.perkflex_release_points, 'earn (pending until you fly)'
  FROM dim_benefit d, b, cur, c
 WHERE d.benefit_type = 'SEAT' AND d.seat_class = cur.seat_type AND cur.seat_type <> 'STANDARD'
   AND NOT b.reward_release_used_flag AND NOT b.seat_waiver_flag AND c.budget_remaining_points >= d.perkflex_release_points
UNION ALL
SELECT 'REDEEM', d.benefit_id, d.benefit_name, d.perkflex_redeem_points,
       CASE WHEN w.total_available_for_perkflex >= d.perkflex_redeem_points THEN 'you can afford this' ELSE 'need ' || (d.perkflex_redeem_points - w.total_available_for_perkflex) || ' more points' END
  FROM dim_benefit d, allow, w, c
 WHERE d.benefit_type = 'BAG' AND d.bag_ordinal = allow.n + 1 AND allow.n < 3 AND c.bag_grants_remaining > 0
UNION ALL
SELECT 'REDEEM', d.benefit_id, d.benefit_name, d.perkflex_redeem_points,
       CASE WHEN w.total_available_for_perkflex >= d.perkflex_redeem_points THEN 'you can afford this' ELSE 'need ' || (d.perkflex_redeem_points - w.total_available_for_perkflex) || ' more points' END
  FROM dim_benefit d, b, cur, w
 WHERE d.benefit_type = 'SEAT' AND d.seat_class <> 'STANDARD' AND NOT b.seat_waiver_flag
   AND (CASE d.seat_class WHEN 'PREFERRED' THEN 2 ELSE 3 END) > (CASE cur.seat_type WHEN 'STANDARD' THEN 1 WHEN 'PREFERRED' THEN 2 ELSE 3 END)
ORDER BY 1, 4;
\echo '-- PerkFlex actions on a booking'
SELECT transaction_id, benefit_id, action_type, transaction_status, perkflex_points_earned AS earned,
       perkflex_points_used AS pf_used, rapid_rewards_points_used AS rr_used, replacement_seat_id, status_reason
FROM fact_perkflex_transaction WHERE booking_id = :'booking' ORDER BY transaction_id;
\echo '-- Failed or declined actions (support view)'
SELECT transaction_id, booking_id, action_type, transaction_status, status_reason, transaction_time_utc
FROM fact_perkflex_transaction WHERE transaction_status IN ('FAILED','DECLINED','EXPIRED') ORDER BY transaction_time_utc;

\echo '=== FACT_POINT_TRANSACTION ==='
\echo '-- Points statement for a traveller with a running balance per currency'
SELECT point_transaction_id, transaction_time_utc, point_type, transaction_type, points_delta, point_status,
       sum(points_delta) FILTER (WHERE point_status IN ('AVAILABLE','POSTED'))
         OVER (PARTITION BY point_type ORDER BY transaction_time_utc, point_transaction_id) AS running_available
FROM fact_point_transaction WHERE passenger_id = :'passenger' ORDER BY transaction_time_utc, point_transaction_id;
\echo '-- Pending entries still waiting to post'
SELECT t.point_transaction_id, t.passenger_id, t.point_type, t.transaction_type, t.points_delta, t.booking_id
FROM fact_point_transaction t
WHERE t.point_status = 'PENDING' AND NOT EXISTS (SELECT 1 FROM fact_point_transaction x WHERE x.source_point_transaction_id = t.point_transaction_id)
ORDER BY t.point_transaction_id;
\echo '-- Totals by entry type'
SELECT point_type, transaction_type, count(*) AS entries, sum(points_delta) AS points FROM fact_point_transaction GROUP BY 1, 2 ORDER BY 1, 2;

\echo '=== AIRLINE VIEW (reporting across tables) ==='
SELECT f.carrier_code || f.flight_number AS flight,
       count(*) FILTER (WHERE t.action_type = 'RELEASE' AND t.transaction_status IN ('ACCEPTED','SETTLED')) AS releases,
       count(*) FILTER (WHERE t.action_type = 'REDEEM'  AND t.transaction_status IN ('ACCEPTED','SETTLED')) AS redemptions,
       COALESCE(sum(t.perkflex_points_earned) FILTER (WHERE t.transaction_status IN ('ACCEPTED','SETTLED')), 0) AS pf_points_earned,
       COALESCE(sum(t.perkflex_points_used) FILTER (WHERE t.transaction_status IN ('ACCEPTED','SETTLED')), 0) AS pf_points_spent,
       COALESCE(sum(t.rapid_rewards_points_used) FILTER (WHERE t.transaction_status IN ('ACCEPTED','SETTLED')), 0) AS rr_points_spent
FROM dim_flight_schedule f LEFT JOIN fact_booking b USING (flight_id) LEFT JOIN fact_perkflex_transaction t USING (booking_id)
GROUP BY f.flight_id ORDER BY f.flight_id;
