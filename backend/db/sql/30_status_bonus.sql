-- Status bonuses (additive).
--   * Flying points (Rapid Rewards): base fare x fare rate x (1 + flying bonus). The fare rate already existed
--     (dim_fare.earning_multiplier); the status bonus is new.
--   * PerkFlex release rewards: base reward x (1 + release bonus). The 300-point small-perk cap counts BASE points,
--     so a bonus never shrinks what a traveller may release. Budget checks and ledger rows use the bonus amount.
-- The rates below are the airline's settings (concept values: Silver/Gold/Platinum flying bonus follows the 2027
-- status levels; the release bonus is a PerkFlex proposal). They are mirrored in backend/app/rules/data.py and a test
-- keeps the two in step.
BEGIN;

CREATE TABLE IF NOT EXISTS dim_tier_bonus (
  tier_status        text PRIMARY KEY CHECK (tier_status IN ('NONE','SILVER','GOLD','PLATINUM')),
  flying_bonus_pct   integer NOT NULL CHECK (flying_bonus_pct BETWEEN 0 AND 300),
  release_bonus_pct  integer NOT NULL CHECK (release_bonus_pct BETWEEN 0 AND 100)
);
INSERT INTO dim_tier_bonus VALUES ('NONE', 0, 0), ('SILVER', 40, 10), ('GOLD', 60, 20), ('PLATINUM', 120, 30)
ON CONFLICT (tier_status) DO NOTHING;

-- Points for a release, with the traveller's status bonus (half up).
CREATE OR REPLACE FUNCTION pf_release_points(p_passenger text, p_benefit text) RETURNS integer
LANGUAGE sql STABLE AS $$
  SELECT floor(d.perkflex_release_points * (100 + COALESCE(t.release_bonus_pct, 0)) / 100.0 + 0.5)::int
    FROM dim_benefit d
    JOIN dim_passenger p ON p.passenger_id = p_passenger
    LEFT JOIN dim_tier_bonus t ON t.tier_status = p.tier_status
   WHERE d.benefit_id = p_benefit;
$$;

CREATE OR REPLACE FUNCTION pf_release_bag(p_passenger text, p_booking text, p_idem text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_prev jsonb; v_row fact_passenger_benefit; v_d dim_benefit; c fact_flight_campaign; v_txn text;
BEGIN
  v_prev := pf_replay(p_idem, p_booking); IF v_prev IS NOT NULL THEN RETURN v_prev; END IF;
  b := pf_require_window(p_passenger, p_booking, p_now);
  IF b.reward_release_used_flag THEN RAISE EXCEPTION 'You have already accepted your one reward offer for this flight'; END IF;
  IF pf_bag_allowance(p_booking) <= COALESCE(b.actual_bag_count, b.expected_bag_count) THEN
    RAISE EXCEPTION 'Only an unused included bag allowance can be released';
  END IF;
  -- release the highest bag in the allowance
  SELECT pb.* INTO v_row FROM fact_passenger_benefit pb JOIN dim_benefit d USING (benefit_id)
   WHERE pb.booking_id = p_booking AND d.benefit_type = 'BAG'
     AND (pb.eligible_quantity + pb.granted_quantity - pb.released_quantity) > 0
   ORDER BY d.bag_ordinal DESC LIMIT 1 FOR UPDATE OF pb;
  SELECT * INTO v_d FROM dim_benefit WHERE benefit_id = v_row.benefit_id;
  v_d.perkflex_release_points := pf_release_points(p_passenger, v_d.benefit_id);  -- status bonus
  IF NOT v_d.release_eligible_flag THEN RAISE EXCEPTION 'This benefit cannot be released'; END IF;
  SELECT * INTO c FROM fact_flight_campaign WHERE flight_id = b.flight_id FOR UPDATE;
  IF c.campaign_status <> 'OPEN' OR c.budget_remaining_points < v_d.perkflex_release_points THEN
    v_txn := pf_record_txn(p_booking, v_d.benefit_id, 'RELEASE', 'FAILED', 0, 0, 0, 0, NULL, p_idem, false,
      'This flight''s reward offers have been fully claimed. Your benefits are unchanged.', p_now);
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', 'This flight''s reward offers have been fully claimed. Your benefits are unchanged.');
  END IF;
  v_txn := pf_record_txn(p_booking, v_d.benefit_id, 'RELEASE', 'ACCEPTED', v_d.perkflex_release_points, 0, 0, 0, NULL, p_idem, true, NULL, p_now);
  PERFORM pf_ledger(p_passenger, p_booking, v_txn, 'PERKFLEX', 'RELEASE_PENDING', v_d.perkflex_release_points, 'PENDING', false, p_now, NULL);
  UPDATE fact_points_wallet SET perkflex_pending = perkflex_pending + v_d.perkflex_release_points,
    wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_passenger;
  UPDATE fact_flight_campaign SET budget_reserved_points = budget_reserved_points + v_d.perkflex_release_points, updated_time_utc = p_now WHERE flight_id = b.flight_id;
  UPDATE fact_passenger_benefit SET released_quantity = 1 WHERE passenger_benefit_id = v_row.passenger_benefit_id;
  UPDATE fact_booking SET reward_release_used_flag = true WHERE booking_id = p_booking;
  RETURN jsonb_build_object('ok', true, 'transaction_id', v_txn, 'points_pending', v_d.perkflex_release_points,
    'message', v_d.perkflex_release_points || ' PerkFlex points are pending and will post after you fly');
END $$;

CREATE OR REPLACE FUNCTION pf_release_seat(p_passenger text, p_booking text, p_idem text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_prev jsonb; v_cur dim_seat; v_new dim_seat; v_benefit text; v_d dim_benefit; c fact_flight_campaign; v_txn text;
BEGIN
  v_prev := pf_replay(p_idem, p_booking); IF v_prev IS NOT NULL THEN RETURN v_prev; END IF;
  b := pf_require_window(p_passenger, p_booking, p_now);
  IF b.reward_release_used_flag THEN RAISE EXCEPTION 'You have already accepted your one reward offer for this flight'; END IF;
  SELECT * INTO v_cur FROM dim_seat WHERE seat_id = b.seat_id FOR UPDATE;
  IF v_cur.seat_type = 'STANDARD' THEN RAISE EXCEPTION 'This seat is not eligible for a release reward'; END IF;
  v_benefit := CASE v_cur.seat_type WHEN 'PREFERRED' THEN 'SEAT_PREF' ELSE 'SEAT_XL' END;
  SELECT * INTO v_d FROM dim_benefit WHERE benefit_id = v_benefit;
  v_d.perkflex_release_points := pf_release_points(p_passenger, v_benefit);  -- status bonus
  SELECT * INTO c FROM fact_flight_campaign WHERE flight_id = b.flight_id FOR UPDATE;
  SELECT * INTO v_new FROM dim_seat WHERE flight_id = b.flight_id AND seat_type = 'STANDARD'
     AND seat_status IN ('AVAILABLE','RELEASED') ORDER BY row_number, seat_number LIMIT 1 FOR UPDATE;
  IF NOT FOUND OR c.campaign_status <> 'OPEN' OR c.budget_remaining_points < v_d.perkflex_release_points THEN
    v_txn := pf_record_txn(p_booking, v_benefit, 'RELEASE', 'FAILED', 0, 0, 0, 0, NULL, p_idem, false,
      'No replacement seat or reward budget is available. Your seat is unchanged.', p_now);
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', 'No replacement seat or reward budget is available. Your seat is unchanged.');
  END IF;
  -- the replacement seat is confirmed in the same transaction that frees the old seat
  UPDATE dim_seat SET seat_status = 'ASSIGNED' WHERE seat_id = v_new.seat_id;
  UPDATE dim_seat SET seat_status = 'RELEASED' WHERE seat_id = v_cur.seat_id;
  UPDATE fact_booking SET seat_id = v_new.seat_id, seat_waiver_flag = true, reward_release_used_flag = true WHERE booking_id = p_booking;
  UPDATE fact_passenger_benefit SET released_quantity = 1
   WHERE booking_id = p_booking AND benefit_id = v_benefit AND (eligible_quantity + granted_quantity) > 0;
  v_txn := pf_record_txn(p_booking, v_benefit, 'RELEASE', 'ACCEPTED', v_d.perkflex_release_points, 0, 0, 0, v_new.seat_id, p_idem, true, NULL, p_now);
  PERFORM pf_ledger(p_passenger, p_booking, v_txn, 'PERKFLEX', 'RELEASE_PENDING', v_d.perkflex_release_points, 'PENDING', false, p_now, NULL);
  UPDATE fact_points_wallet SET perkflex_pending = perkflex_pending + v_d.perkflex_release_points,
    wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_passenger;
  UPDATE fact_flight_campaign SET budget_reserved_points = budget_reserved_points + v_d.perkflex_release_points, updated_time_utc = p_now WHERE flight_id = b.flight_id;
  RETURN jsonb_build_object('ok', true, 'transaction_id', v_txn, 'old_seat', v_cur.seat_number, 'new_seat', v_new.seat_number,
    'points_pending', v_d.perkflex_release_points);
END $$;

CREATE OR REPLACE FUNCTION pf_release_perk(p_passenger text, p_booking text, p_benefit text, p_idem text,
                                           p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_prev jsonb; v_d dim_benefit; v_src text; c fact_flight_campaign; v_txn text; v_earned int;
        v_msg text;
BEGIN
  v_prev := pf_replay(p_idem, p_booking); IF v_prev IS NOT NULL THEN RETURN v_prev; END IF;
  SELECT * INTO v_d FROM dim_benefit WHERE benefit_id = p_benefit AND benefit_type = 'PERK';
  IF NOT FOUND OR NOT v_d.release_eligible_flag THEN RAISE EXCEPTION 'This benefit cannot be released'; END IF;
  b := pf_require_window(p_passenger, p_booking, p_now);
  v_src := pf_perk_source(p_booking, p_benefit);
  IF v_src IS NULL THEN RAISE EXCEPTION 'Your trip does not include %, so there is nothing to release', lower(v_d.benefit_name); END IF;
  IF EXISTS (SELECT 1 FROM fact_passenger_benefit WHERE booking_id = p_booking AND benefit_id = p_benefit
              AND benefit_source = v_src AND released_quantity > 0) THEN
    RAISE EXCEPTION 'You have already released %', lower(v_d.benefit_name);
  END IF;
  SELECT COALESCE(sum(d.perkflex_release_points), 0) INTO v_earned  -- the cap counts base points, before any bonus
    FROM fact_perkflex_transaction t JOIN dim_benefit d USING (benefit_id)
   WHERE t.booking_id = p_booking AND d.benefit_type = 'PERK' AND t.action_type = 'RELEASE'
     AND t.transaction_status IN ('ACCEPTED','SETTLED');
  IF v_earned + v_d.perkflex_release_points > 300 THEN
    RAISE EXCEPTION 'Small perks can earn at most 300 points per flight';
  END IF;
  v_d.perkflex_release_points := pf_release_points(p_passenger, p_benefit);  -- status bonus, applied after the cap check
  SELECT * INTO c FROM fact_flight_campaign WHERE flight_id = b.flight_id FOR UPDATE;
  IF c.campaign_status <> 'OPEN' OR c.budget_remaining_points < v_d.perkflex_release_points THEN
    v_msg := 'This flight''s reward offers have been fully claimed. Your benefits are unchanged.';
    v_txn := pf_record_txn(p_booking, p_benefit, 'RELEASE', 'FAILED', 0, 0, 0, 0, NULL, p_idem, false, v_msg, p_now);
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', v_msg);
  END IF;
  v_txn := pf_record_txn(p_booking, p_benefit, 'RELEASE', 'ACCEPTED', v_d.perkflex_release_points, 0, 0, 0, NULL, p_idem, false, NULL, p_now);
  PERFORM pf_ledger(p_passenger, p_booking, v_txn, 'PERKFLEX', 'RELEASE_PENDING', v_d.perkflex_release_points, 'PENDING', false, p_now, NULL);
  UPDATE fact_points_wallet SET perkflex_pending = perkflex_pending + v_d.perkflex_release_points,
    wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_passenger;
  UPDATE fact_flight_campaign SET budget_reserved_points = budget_reserved_points + v_d.perkflex_release_points,
    updated_time_utc = p_now WHERE flight_id = b.flight_id;
  INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code,
    eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity)
  VALUES ('PB' || lpad(nextval('pf_txn_seq')::text, 4, '0'), p_booking, p_benefit, v_src, v_src, 1, 'CHECKIN', 0, 1, 0);
  RETURN jsonb_build_object('ok', true, 'transaction_id', v_txn, 'points_pending', v_d.perkflex_release_points,
    'message', v_d.perkflex_release_points || ' PerkFlex points are pending and will post after you fly');
END $$;

-- Seed data: flying points already pending for travellers with status get their flying bonus, so demo travellers
-- match what a new booking would earn. The ledger is append-only, so its triggers are paused for this one correction
-- (the demo restore does the same).
ALTER TABLE fact_point_transaction DISABLE TRIGGER USER;
WITH fix AS (
  SELECT pt.point_transaction_id, pt.passenger_id,
         floor(pt.points_delta * (100 + t.flying_bonus_pct) / 100.0 + 0.5)::int AS new_points, pt.points_delta AS old_points
    FROM fact_point_transaction pt
    JOIN dim_passenger p ON p.passenger_id = pt.passenger_id
    JOIN dim_tier_bonus t ON t.tier_status = p.tier_status
   WHERE pt.transaction_type = 'FLIGHT_EARN_PENDING' AND pt.point_type = 'RAPID_REWARDS' AND t.flying_bonus_pct > 0
     AND NOT EXISTS (SELECT 1 FROM fact_point_transaction x WHERE x.source_point_transaction_id = pt.point_transaction_id)
), upd AS (
  UPDATE fact_point_transaction pt SET points_delta = fix.new_points FROM fix
   WHERE pt.point_transaction_id = fix.point_transaction_id RETURNING fix.passenger_id, fix.new_points - fix.old_points AS delta
)
UPDATE fact_points_wallet w SET rapid_rewards_pending = w.rapid_rewards_pending + s.delta
  FROM (SELECT passenger_id, sum(delta) AS delta FROM upd GROUP BY passenger_id) s WHERE w.passenger_id = s.passenger_id;
ALTER TABLE fact_point_transaction ENABLE TRIGGER USER;

SELECT pf_demo_snapshot(true);

COMMIT;
