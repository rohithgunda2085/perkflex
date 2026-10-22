-- Negative tests: each statement below must be REFUSED by the database. Run after 05_demo_run.sql.
-- A test passes when it prints "refused: ...". It prints "NOT REFUSED" if the rule is missing.
\set ON_ERROR_STOP off
CREATE OR REPLACE FUNCTION pf_expect_refusal(p_name text, p_sql text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  BEGIN EXECUTE p_sql; RAISE NOTICE 'NOT REFUSED: %', p_name;
  EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'refused: % (%)', p_name, left(SQLERRM, 80); END;
END $$;
SELECT pf_expect_refusal('edit a ledger row', $$UPDATE fact_point_transaction SET points_delta = 1 WHERE point_transaction_id = 'PT001'$$);
SELECT pf_expect_refusal('delete a ledger row', $$DELETE FROM fact_point_transaction WHERE point_transaction_id = 'PT001'$$);
SELECT pf_expect_refusal('post a pending entry twice', $$INSERT INTO fact_point_transaction (point_transaction_id,passenger_id,booking_id,point_type,transaction_type,points_delta,point_status,tqp_eligible_flag,transaction_time_utc,source_point_transaction_id) SELECT 'PTDUP1',passenger_id,booking_id,point_type,'FLIGHT_EARN_POST',points_delta,'POSTED',true,now(),point_transaction_id FROM fact_point_transaction WHERE point_transaction_id='PT010'$$);
SELECT pf_expect_refusal('negative wallet', $$UPDATE fact_points_wallet SET rapid_rewards_available = -1 WHERE passenger_id = 'P09'$$);
INSERT INTO fact_booking (booking_id,passenger_id,flight_id,fare_id,seat_id,booking_date_utc,booking_status,cash_total_cents,expected_bag_count)
  VALUES ('BX1','P09','F02','BASIC','F02-26F','2027-11-10 00:00:00+00','BOOKED',16260,0);
SELECT pf_expect_refusal('two live bookings on one seat', $$INSERT INTO fact_booking (booking_id,passenger_id,flight_id,fare_id,seat_id,booking_date_utc,booking_status,cash_total_cents,expected_bag_count) VALUES ('BX2','P08','F02','BASIC','F02-26F','2027-11-10 00:00:00+00','BOOKED',16260,0)$$);
SELECT pf_expect_refusal('budget above the flight limit', $$UPDATE fact_flight_campaign SET budget_reserved_points = 10001 WHERE flight_id = 'F02'$$);
SELECT pf_expect_refusal('bag grants below zero', $$UPDATE fact_flight_campaign SET bag_grants_remaining = -1 WHERE flight_id = 'F02'$$);
SELECT pf_expect_refusal('reused idempotency key', $$INSERT INTO fact_perkflex_transaction (transaction_id,booking_id,benefit_id,action_type,transaction_status,idempotency_key) VALUES ('TDUP','B05','BAG1','RELEASE','OFFERED','IDEMP-B01-1')$$);
SELECT pf_expect_refusal('second rewarded release on one booking', $$INSERT INTO fact_perkflex_transaction (transaction_id,booking_id,benefit_id,action_type,transaction_status,perkflex_points_earned,rewarded_flag) VALUES ('TDUP2','B01','BAG1','RELEASE','ACCEPTED',800,true)$$);
SELECT pf_expect_refusal('PerkFlex points in a flight-earn entry', $$INSERT INTO fact_point_transaction (point_transaction_id,passenger_id,point_type,transaction_type,points_delta,point_status,transaction_time_utc) VALUES ('PTBAD','P01','PERKFLEX','FLIGHT_EARN_PENDING',10,'PENDING',now())$$);
SELECT pf_expect_refusal('seat that does not exist', $$UPDATE fact_booking SET seat_id = 'F01-99Z' WHERE booking_id = 'B09'$$);
SELECT pf_expect_refusal('release after check-in', $$SELECT pf_release_bag('P01','B01','IDEMP-LATE','2027-12-16 00:00:00+00')$$);
SELECT pf_expect_refusal('another traveller''s booking', $$SELECT pf_redeem_bag('P02','B01','IDEMP-X','2027-12-15 16:00:00+00')$$);
SELECT pf_expect_refusal('idempotency key reused for another booking', $$SELECT pf_redeem_bag('P05','B05','IDEMP-B01-1','2027-12-15 16:00:00+00')$$);
