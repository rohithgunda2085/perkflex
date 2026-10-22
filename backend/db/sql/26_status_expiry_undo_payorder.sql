-- Four additions (additive):
--   1. Status display data: tier qualifying points (synthetic) on dim_passenger.
--   2. Expiry: PerkFlex points expire 12 months after they post, oldest first (pf_expiry_lots, pf_expire_points).
--   3. Undo: a release can be taken back within 5 real minutes, while check-in is open and nobody has taken the freed
--      seat (pf_undo_release).
--   4. Payment order: a traveller may choose to spend Rapid Rewards before PerkFlex (pf_set_pay_order, pf_pay).
-- Ends by retaking the demo snapshot, because the tables above gained columns.
BEGIN;

-- ---- 1. tier qualifying points (read-only display; invented for the demo) ----
ALTER TABLE dim_passenger ADD COLUMN IF NOT EXISTS tqp_ytd integer NOT NULL DEFAULT 0 CHECK (tqp_ytd >= 0);
UPDATE dim_passenger SET tqp_ytd = CASE tier_status
    WHEN 'NONE' THEN 6000 WHEN 'SILVER' THEN 38000 WHEN 'GOLD' THEN 71000 WHEN 'PLATINUM' THEN 142000 END
 WHERE tqp_ytd = 0;

-- ---- real-time record of when an action happened (the demo clock is pinned, so it cannot time the undo window) ----
ALTER TABLE fact_perkflex_transaction ADD COLUMN IF NOT EXISTS recorded_at timestamptz NOT NULL DEFAULT now();

CREATE OR REPLACE FUNCTION pf_record_txn(
  p_booking text, p_benefit text, p_action text, p_status text, p_earned int, p_pf_used int, p_rr_used int,
  p_price int, p_seat text, p_idem text, p_rewarded boolean, p_reason text, p_now timestamptz) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE v_id text;
BEGIN
  SELECT transaction_id INTO v_id FROM fact_perkflex_transaction
   WHERE booking_id = p_booking AND benefit_id = p_benefit AND action_type = p_action
     AND transaction_status = 'OFFERED' ORDER BY transaction_id LIMIT 1 FOR UPDATE;
  IF v_id IS NULL THEN
    v_id := 'T' || lpad(nextval('pf_txn_seq')::text, 4, '0');
    INSERT INTO fact_perkflex_transaction (transaction_id, booking_id, benefit_id, action_type, transaction_status,
      perkflex_points_earned, perkflex_points_used, rapid_rewards_points_used, total_benefit_price_points,
      replacement_seat_id, transaction_time_utc, idempotency_key, rewarded_flag, status_reason)
    VALUES (v_id, p_booking, p_benefit, p_action, p_status, p_earned, p_pf_used, p_rr_used, p_price,
      p_seat, p_now, p_idem, p_rewarded, p_reason);
  ELSE
    UPDATE fact_perkflex_transaction SET transaction_status = p_status, perkflex_points_earned = p_earned,
      perkflex_points_used = p_pf_used, rapid_rewards_points_used = p_rr_used, total_benefit_price_points = p_price,
      replacement_seat_id = COALESCE(p_seat, replacement_seat_id), transaction_time_utc = p_now,
      idempotency_key = p_idem, rewarded_flag = p_rewarded, status_reason = p_reason, recorded_at = now()
    WHERE transaction_id = v_id;
  END IF;
  RETURN v_id;
END $$;

-- ---- 4. payment order ----
ALTER TABLE fact_points_wallet ADD COLUMN IF NOT EXISTS pay_rapid_first boolean NOT NULL DEFAULT false;

CREATE OR REPLACE FUNCTION pf_set_pay_order(p_passenger text, p_rapid_first boolean) RETURNS jsonb
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE fact_points_wallet SET pay_rapid_first = p_rapid_first, wallet_version = wallet_version + 1
   WHERE passenger_id = p_passenger;
  IF NOT FOUND THEN RAISE EXCEPTION 'No wallet found for this traveller'; END IF;
  RETURN jsonb_build_object('ok', true, 'rapid_first', p_rapid_first);
END $$;

CREATE OR REPLACE FUNCTION pf_pay(p_passenger text, p_booking text, p_txn text, p_price int, p_now timestamptz,
  OUT o_pf int, OUT o_rr int, OUT o_ok boolean) LANGUAGE plpgsql AS $$
DECLARE w fact_points_wallet;
BEGIN
  SELECT * INTO w FROM fact_points_wallet WHERE passenger_id = p_passenger FOR UPDATE;
  IF w.pay_rapid_first THEN
    o_rr := LEAST(w.rapid_rewards_available, p_price);
    o_pf := p_price - o_rr;
    o_ok := w.perkflex_available >= o_pf;
  ELSE
    o_pf := LEAST(w.perkflex_available, p_price);
    o_rr := p_price - o_pf;
    o_ok := w.rapid_rewards_available >= o_rr;
  END IF;
  IF NOT o_ok THEN RETURN; END IF;
  IF o_pf > 0 THEN PERFORM pf_ledger(p_passenger, p_booking, p_txn, 'PERKFLEX', 'BENEFIT_DEBIT', -o_pf, 'POSTED', false, p_now, NULL); END IF;
  IF o_rr > 0 THEN PERFORM pf_ledger(p_passenger, p_booking, p_txn, 'RAPID_REWARDS', 'BENEFIT_DEBIT', -o_rr, 'POSTED', false, p_now, NULL); END IF;
  UPDATE fact_points_wallet SET perkflex_available = perkflex_available - o_pf,
    rapid_rewards_available = rapid_rewards_available - o_rr, wallet_version = wallet_version + 1, updated_time_utc = p_now
  WHERE passenger_id = p_passenger;
END $$;

-- ---- 2. expiry: 12 months after posting, oldest points first ----
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'fact_point_transaction'::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%''SEED''%' LOOP
    EXECUTE format('ALTER TABLE fact_point_transaction DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
ALTER TABLE fact_point_transaction ADD CONSTRAINT fact_point_transaction_type_check CHECK (transaction_type IN
  ('SEED','FLIGHT_EARN_PENDING','FLIGHT_EARN_POST','RELEASE_PENDING','RELEASE_POST','BENEFIT_DEBIT','REFUND','VOID','EXPIRY'));
ALTER TABLE fact_point_transaction ADD CONSTRAINT fact_point_transaction_expiry_check CHECK (
  transaction_type <> 'EXPIRY' OR (point_type = 'PERKFLEX' AND points_delta < 0 AND point_status = 'POSTED'));

-- The PerkFlex points still unspent, lot by lot. Spending (and earlier expiry) uses up the oldest lots first.
CREATE OR REPLACE FUNCTION pf_expiry_lots(p_passenger text)
RETURNS TABLE (points int, posted_at timestamptz, expires_at timestamptz) LANGUAGE plpgsql STABLE AS $$
DECLARE v_used int; r record; v_take int; v_left int;
BEGIN
  SELECT COALESCE(-sum(points_delta), 0) INTO v_used FROM fact_point_transaction
   WHERE passenger_id = p_passenger AND point_type = 'PERKFLEX' AND transaction_type IN ('BENEFIT_DEBIT','EXPIRY');
  FOR r IN SELECT points_delta AS d, transaction_time_utc AS t FROM fact_point_transaction
            WHERE passenger_id = p_passenger AND point_type = 'PERKFLEX' AND transaction_type = 'RELEASE_POST'
            ORDER BY transaction_time_utc, point_transaction_id LOOP
    v_take := LEAST(v_used, r.d); v_used := v_used - v_take; v_left := r.d - v_take;
    IF v_left > 0 THEN
      points := v_left; posted_at := r.t; expires_at := r.t + interval '12 months'; RETURN NEXT;
    END IF;
  END LOOP;
END $$;

-- Takes expired lots out of the wallet. Safe to call again and again: it only removes what has expired.
CREATE OR REPLACE FUNCTION pf_expire_points(p_passenger text, p_now timestamptz DEFAULT now()) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE v_exp int; w fact_points_wallet;
BEGIN
  SELECT * INTO w FROM fact_points_wallet WHERE passenger_id = p_passenger FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('ok', true, 'expired', 0); END IF;
  SELECT LEAST(w.perkflex_available, COALESCE(sum(points), 0))::int INTO v_exp FROM pf_expiry_lots(p_passenger) WHERE expires_at <= p_now;
  IF v_exp > 0 THEN
    PERFORM pf_ledger(p_passenger, NULL, NULL, 'PERKFLEX', 'EXPIRY', -v_exp, 'POSTED', false, p_now, NULL);
    UPDATE fact_points_wallet SET perkflex_available = perkflex_available - v_exp, wallet_version = wallet_version + 1,
           updated_time_utc = p_now WHERE passenger_id = p_passenger;
  END IF;
  RETURN jsonb_build_object('ok', true, 'expired', v_exp);
END $$;

-- ---- 3. undo a release (5 real minutes, check-in still open) ----
CREATE OR REPLACE FUNCTION pf_undo_release(p_passenger text, p_booking text, p_txn text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; t fact_perkflex_transaction; d dim_benefit; v_pend fact_point_transaction;
        v_old dim_seat; v_cur dim_seat;
BEGIN
  b := pf_require_window(p_passenger, p_booking, p_now);
  SELECT * INTO t FROM fact_perkflex_transaction WHERE transaction_id = p_txn AND booking_id = p_booking FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'That release was not found for this trip'; END IF;
  IF t.action_type <> 'RELEASE' THEN RAISE EXCEPTION 'Only a release can be undone'; END IF;
  IF t.transaction_status = 'VOID' THEN
    RETURN jsonb_build_object('ok', true, 'replayed', true, 'message', 'That release was already undone');
  END IF;
  IF t.transaction_status <> 'ACCEPTED' THEN RAISE EXCEPTION 'This release can no longer be undone'; END IF;
  IF now() - t.recorded_at > interval '5 minutes' THEN
    RAISE EXCEPTION 'The 5-minute window to undo this release has passed';
  END IF;
  SELECT * INTO d FROM dim_benefit WHERE benefit_id = t.benefit_id;
  SELECT * INTO v_pend FROM fact_point_transaction
   WHERE perkflex_transaction_id = p_txn AND transaction_type = 'RELEASE_PENDING' FOR UPDATE;
  IF NOT FOUND OR EXISTS (SELECT 1 FROM fact_point_transaction x WHERE x.source_point_transaction_id = v_pend.point_transaction_id) THEN
    RAISE EXCEPTION 'This release can no longer be undone';
  END IF;

  IF d.benefit_type = 'BAG' THEN
    UPDATE fact_passenger_benefit SET released_quantity = 0
     WHERE booking_id = p_booking AND benefit_id = t.benefit_id AND released_quantity > 0;
    UPDATE fact_booking SET reward_release_used_flag = false WHERE booking_id = p_booking;
  ELSIF d.benefit_type = 'PERK' THEN
    DELETE FROM fact_passenger_benefit WHERE booking_id = p_booking AND benefit_id = t.benefit_id AND released_quantity > 0;
  ELSE  -- SEAT: give the traveller their seat back, if nobody has taken it
    SELECT * INTO v_old FROM dim_seat WHERE flight_id = b.flight_id AND freed_by_booking = p_booking
       AND reused_by_booking IS NULL AND seat_status = 'RELEASED' FOR UPDATE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Another traveller has taken that seat, so this release cannot be undone';
    END IF;
    SELECT * INTO v_cur FROM dim_seat WHERE seat_id = b.seat_id FOR UPDATE;
    UPDATE dim_seat SET seat_status = 'ASSIGNED', freed_by_booking = NULL, freed_time_utc = NULL WHERE seat_id = v_old.seat_id;
    UPDATE dim_seat SET seat_status = 'AVAILABLE' WHERE seat_id = v_cur.seat_id;
    UPDATE fact_booking SET seat_id = v_old.seat_id, seat_waiver_flag = false, reward_release_used_flag = false
     WHERE booking_id = p_booking;
    UPDATE fact_passenger_benefit SET released_quantity = 0
     WHERE booking_id = p_booking AND benefit_id = t.benefit_id AND released_quantity > 0;
  END IF;

  PERFORM pf_ledger(p_passenger, p_booking, p_txn, 'PERKFLEX', 'VOID', -v_pend.points_delta, 'VOID', false, p_now, v_pend.point_transaction_id);
  UPDATE fact_points_wallet SET perkflex_pending = perkflex_pending - v_pend.points_delta,
         wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_passenger;
  UPDATE fact_flight_campaign SET budget_reserved_points = budget_reserved_points - v_pend.points_delta,
         updated_time_utc = p_now WHERE flight_id = b.flight_id;
  UPDATE fact_perkflex_transaction SET transaction_status = 'VOID', rewarded_flag = false,
         status_reason = 'Undone by the traveller' WHERE transaction_id = p_txn;
  RETURN jsonb_build_object('ok', true, 'points_returned', v_pend.points_delta, 'message', 'Release undone');
END $$;

-- ---- demo data: a lot of PerkFlex points that is about to expire (12 months before 2027-12-27 is 2026-12-27) ----
INSERT INTO fact_point_transaction (point_transaction_id, passenger_id, booking_id, perkflex_transaction_id, point_type,
  transaction_type, points_delta, point_status, tqp_eligible_flag, transaction_time_utc, source_point_transaction_id)
SELECT 'PT901', 'P13', NULL, NULL, 'PERKFLEX', 'RELEASE_PENDING', 1500, 'PENDING', false, '2026-12-26T12:00:00Z', NULL
 WHERE NOT EXISTS (SELECT 1 FROM fact_point_transaction WHERE point_transaction_id = 'PT901');
INSERT INTO fact_point_transaction (point_transaction_id, passenger_id, booking_id, perkflex_transaction_id, point_type,
  transaction_type, points_delta, point_status, tqp_eligible_flag, transaction_time_utc, source_point_transaction_id)
SELECT 'PT902', 'P13', NULL, NULL, 'PERKFLEX', 'RELEASE_POST', 1500, 'POSTED', false, '2026-12-27T12:00:00Z', 'PT901'
 WHERE NOT EXISTS (SELECT 1 FROM fact_point_transaction WHERE point_transaction_id = 'PT902');
UPDATE fact_points_wallet SET perkflex_available = perkflex_available + 1500
 WHERE passenger_id = 'P13' AND NOT EXISTS (SELECT 1 FROM fact_point_transaction WHERE point_transaction_id = 'PT902' AND false);

SELECT pf_demo_snapshot(true);

COMMIT;
