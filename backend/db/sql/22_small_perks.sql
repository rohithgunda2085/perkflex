-- Small perks (additive). Priority boarding, a premium drink and priority-lane access can be released for points or,
-- for boarding and drinks, bought with points.
--
-- Rule (hybrid): the one rewarded release per flight (a bag OR a seat) is untouched. Small perks sit beside it:
--   * they never use that slot (rewarded_flag stays false);
--   * each perk can be released once per booking;
--   * a booking can earn at most 300 points from small perks (the three release values add up to exactly 300);
--   * they draw on the same per-flight reward budget and stay pending until the trip is flown.
-- Whether a traveller already has a perk comes from their fare and tier (pf_perk_source), never from the browser.
BEGIN;

-- 1. dim_benefit accepts a third type, PERK.
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'dim_benefit'::regclass AND contype = 'c'
              AND (pg_get_constraintdef(oid) LIKE '%benefit_type%') LOOP
    EXECUTE format('ALTER TABLE dim_benefit DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

ALTER TABLE dim_benefit ADD CONSTRAINT dim_benefit_type_check CHECK (benefit_type IN ('BAG','SEAT','PERK'));
ALTER TABLE dim_benefit ADD CONSTRAINT dim_benefit_shape_check CHECK (
  (benefit_type = 'BAG'  AND bag_ordinal IS NOT NULL AND seat_class IS NULL) OR
  (benefit_type = 'SEAT' AND seat_class  IS NOT NULL AND bag_ordinal IS NULL) OR
  (benefit_type = 'PERK' AND seat_class  IS NULL     AND bag_ordinal IS NULL));

INSERT INTO dim_benefit (benefit_id, benefit_name, benefit_type, bag_ordinal, seat_class,
                         perkflex_release_points, perkflex_redeem_points, release_eligible_flag, cash_addon_cents) VALUES
  ('PERK_BOARDING', 'Priority boarding', 'PERK', NULL, NULL, 100, 900, true, 1000),
  ('PERK_DRINK',    'Premium drink',     'PERK', NULL, NULL, 150, 600, true, 800),
  ('PERK_LANE',     'Priority lane',     'PERK', NULL, NULL,  50,   0, true, 0)   -- not for sale: redeem = 0
ON CONFLICT (benefit_id) DO NOTHING;

-- 2. Which perks does this traveller already have, and from where? NULL means they do not have it.
CREATE OR REPLACE FUNCTION pf_perk_source(p_booking text, p_benefit text) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT CASE p_benefit
    WHEN 'PERK_LANE' THEN
      CASE WHEN f.priority_lane_flag THEN 'FARE' WHEN p.tier_status IN ('SILVER','GOLD','PLATINUM') THEN 'TIER' END
    WHEN 'PERK_DRINK' THEN
      CASE WHEN f.premium_drink_flag THEN 'FARE' WHEN p.tier_status IN ('GOLD','PLATINUM') THEN 'TIER' END
    WHEN 'PERK_BOARDING' THEN
      CASE WHEN f.boarding_group = 'Group 1' THEN 'FARE' WHEN p.tier_status IN ('SILVER','GOLD','PLATINUM') THEN 'TIER' END
  END
  FROM fact_booking b
  JOIN dim_fare f ON f.fare_id = b.fare_id
  JOIN dim_passenger p ON p.passenger_id = b.passenger_id
  WHERE b.booking_id = p_booking;
$$;

-- 3. Release a perk you already have, for pending PerkFlex points.
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
  SELECT COALESCE(sum(perkflex_points_earned), 0) INTO v_earned
    FROM fact_perkflex_transaction t JOIN dim_benefit d USING (benefit_id)
   WHERE t.booking_id = p_booking AND d.benefit_type = 'PERK' AND t.action_type = 'RELEASE'
     AND t.transaction_status IN ('ACCEPTED','SETTLED');
  IF v_earned + v_d.perkflex_release_points > 300 THEN
    RAISE EXCEPTION 'Small perks can earn at most 300 points per flight';
  END IF;
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

-- 4. Buy a perk you do not have, with points (PerkFlex points first, then Rapid Rewards).
CREATE OR REPLACE FUNCTION pf_redeem_perk(p_passenger text, p_booking text, p_benefit text, p_idem text,
                                          p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_prev jsonb; v_d dim_benefit; v_txn text; r record; v_msg text;
BEGIN
  v_prev := pf_replay(p_idem, p_booking); IF v_prev IS NOT NULL THEN RETURN v_prev; END IF;
  SELECT * INTO v_d FROM dim_benefit WHERE benefit_id = p_benefit AND benefit_type = 'PERK';
  IF NOT FOUND OR v_d.perkflex_redeem_points <= 0 THEN RAISE EXCEPTION 'This benefit cannot be bought with points'; END IF;
  b := pf_require_window(p_passenger, p_booking, p_now);
  IF pf_perk_source(p_booking, p_benefit) IS NOT NULL THEN
    RAISE EXCEPTION 'Your trip already includes %', lower(v_d.benefit_name);
  END IF;
  IF EXISTS (SELECT 1 FROM fact_passenger_benefit WHERE booking_id = p_booking AND benefit_id = p_benefit
              AND benefit_source = 'PERKFLEX') THEN
    RAISE EXCEPTION 'You have already added %', lower(v_d.benefit_name);
  END IF;
  v_txn := pf_record_txn(p_booking, p_benefit, 'REDEEM', 'ACCEPTED', 0, 0, 0, 0, NULL, p_idem, false, NULL, p_now);
  SELECT * INTO r FROM pf_pay(p_passenger, p_booking, v_txn, v_d.perkflex_redeem_points, p_now);
  IF NOT r.o_ok THEN
    v_msg := 'Not enough points. Your balance and benefits are unchanged.';
    UPDATE fact_perkflex_transaction SET transaction_status = 'FAILED', status_reason = v_msg,
      total_benefit_price_points = v_d.perkflex_redeem_points WHERE transaction_id = v_txn;
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', v_msg);
  END IF;
  UPDATE fact_perkflex_transaction SET perkflex_points_used = r.o_pf, rapid_rewards_points_used = r.o_rr,
    total_benefit_price_points = v_d.perkflex_redeem_points WHERE transaction_id = v_txn;
  INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code,
    eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity)
  VALUES ('PB' || lpad(nextval('pf_txn_seq')::text, 4, '0'), p_booking, p_benefit, 'PERKFLEX', v_txn, 0, 'CHECKIN', 0, 0, 1);
  RETURN jsonb_build_object('ok', true, 'transaction_id', v_txn, 'perkflex_points_used', r.o_pf,
    'rapid_rewards_points_used', r.o_rr, 'message', v_d.benefit_name || ' added');
END $$;

COMMIT;
