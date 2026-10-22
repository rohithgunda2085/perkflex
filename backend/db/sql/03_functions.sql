-- PerkFlex transaction procedures (reference implementation of the rules in SQL)
-- Each function is one atomic transaction. In the application the TypeScript rules engine is the
-- source of truth; these functions show the exact reads, writes and locks it must perform.
-- Return value is jsonb: {ok, transaction_id, message, ...}. Rule violations raise an exception
-- (nothing is stored). Business outcomes such as "not enough points" are stored as a FAILED action
-- and returned with ok = false.
-- Every function takes p_now so the demo can run on any date; default is now().

-- ---------- helpers ----------
CREATE OR REPLACE FUNCTION pf_bag_allowance(p_booking text) RETURNS int
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(SUM(pb.eligible_quantity + pb.granted_quantity - pb.released_quantity), 0)::int
  FROM fact_passenger_benefit pb JOIN dim_benefit d USING (benefit_id)
  WHERE pb.booking_id = p_booking AND d.benefit_type = 'BAG';
$$;

-- Returns the earlier result when the same idempotency key is retried.
CREATE OR REPLACE FUNCTION pf_replay(p_idem text, p_booking text) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE t fact_perkflex_transaction;
BEGIN
  IF p_idem IS NULL THEN RAISE EXCEPTION 'An idempotency key is required'; END IF;
  SELECT * INTO t FROM fact_perkflex_transaction WHERE idempotency_key = p_idem;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF t.booking_id <> p_booking THEN
    RAISE EXCEPTION 'Idempotency key % was already used for a different request', p_idem;
  END IF;
  RETURN jsonb_build_object('ok', t.transaction_status IN ('ACCEPTED','SETTLED'),
    'transaction_id', t.transaction_id, 'replayed', true, 'message', COALESCE(t.status_reason, 'Already processed'));
END $$;

-- Locks the booking and checks that PerkFlex is allowed: right traveller, check-in open, not completed.
CREATE OR REPLACE FUNCTION pf_require_window(p_passenger text, p_booking text, p_now timestamptz)
RETURNS fact_booking LANGUAGE plpgsql AS $$
DECLARE b fact_booking; f dim_flight_schedule;
BEGIN
  SELECT * INTO b FROM fact_booking WHERE booking_id = p_booking AND passenger_id = p_passenger FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Booking % was not found for this passenger', p_booking; END IF;
  IF b.booking_status <> 'BOOKED' THEN
    RAISE EXCEPTION 'Your check-in is complete. Benefit changes are now closed.';
  END IF;
  SELECT * INTO f FROM dim_flight_schedule WHERE flight_id = b.flight_id;
  IF f.flight_status <> 'SCHEDULED' THEN RAISE EXCEPTION 'This flight is no longer open for changes'; END IF;
  IF p_now < f.checkin_open_time_utc THEN RAISE EXCEPTION 'PerkFlex is available during web check-in, which is not open yet'; END IF;
  RETURN b;
END $$;

-- Records an action: reuses a matching OFFERED row if one exists, otherwise inserts a new row.
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
      idempotency_key = p_idem, rewarded_flag = p_rewarded, status_reason = p_reason
    WHERE transaction_id = v_id;
  END IF;
  RETURN v_id;
END $$;

CREATE OR REPLACE FUNCTION pf_ledger(
  p_passenger text, p_booking text, p_txn text, p_type text, p_ttype text, p_delta int, p_status text,
  p_tqp boolean, p_now timestamptz, p_source text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE v_id text := 'PT' || lpad(nextval('pf_point_seq')::text, 4, '0');
BEGIN
  INSERT INTO fact_point_transaction (point_transaction_id, passenger_id, booking_id, perkflex_transaction_id,
    point_type, transaction_type, points_delta, point_status, tqp_eligible_flag, transaction_time_utc, source_point_transaction_id)
  VALUES (v_id, p_passenger, p_booking, p_txn, p_type, p_ttype, p_delta, p_status, p_tqp, p_now, p_source);
  RETURN v_id;
END $$;

-- Pays a price in points: PerkFlex points first, then Rapid Rewards. Writes ledger rows and the wallet.
-- Returns NULL when the traveller cannot afford it (nothing is changed).
CREATE OR REPLACE FUNCTION pf_pay(p_passenger text, p_booking text, p_txn text, p_price int, p_now timestamptz,
  OUT o_pf int, OUT o_rr int, OUT o_ok boolean) LANGUAGE plpgsql AS $$
DECLARE w fact_points_wallet;
BEGIN
  SELECT * INTO w FROM fact_points_wallet WHERE passenger_id = p_passenger FOR UPDATE;
  o_pf := LEAST(w.perkflex_available, p_price);
  o_rr := p_price - o_pf;
  o_ok := w.rapid_rewards_available >= o_rr;
  IF NOT o_ok THEN RETURN; END IF;
  IF o_pf > 0 THEN PERFORM pf_ledger(p_passenger, p_booking, p_txn, 'PERKFLEX', 'BENEFIT_DEBIT', -o_pf, 'POSTED', false, p_now, NULL); END IF;
  IF o_rr > 0 THEN PERFORM pf_ledger(p_passenger, p_booking, p_txn, 'RAPID_REWARDS', 'BENEFIT_DEBIT', -o_rr, 'POSTED', false, p_now, NULL); END IF;
  UPDATE fact_points_wallet SET perkflex_available = perkflex_available - o_pf,
    rapid_rewards_available = rapid_rewards_available - o_rr, wallet_version = wallet_version + 1, updated_time_utc = p_now
  WHERE passenger_id = p_passenger;
END $$;

-- ---------- 1. open check-in ----------
CREATE OR REPLACE FUNCTION pf_open_checkin(p_passenger text, p_booking text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking;
BEGIN
  b := pf_require_window(p_passenger, p_booking, p_now);
  UPDATE fact_booking SET checkin_opened_time_utc = COALESCE(checkin_opened_time_utc, p_now) WHERE booking_id = p_booking;
  RETURN jsonb_build_object('ok', true, 'message', 'Check-in is open');
END $$;

-- ---------- 2. set the number of bags being checked ----------
CREATE OR REPLACE FUNCTION pf_set_bags(p_passenger text, p_booking text, p_count int, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking;
BEGIN
  IF p_count IS NULL OR p_count < 0 OR p_count > 3 THEN RAISE EXCEPTION 'Choose between 0 and 3 bags'; END IF;
  b := pf_require_window(p_passenger, p_booking, p_now);
  UPDATE fact_booking SET actual_bag_count = p_count WHERE booking_id = p_booking;
  RETURN jsonb_build_object('ok', true, 'bags', p_count, 'allowance', pf_bag_allowance(p_booking));
END $$;

-- ---------- 3. release an unused bag allowance for PerkFlex Rewards (pending) ----------
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

-- ---------- 4. release a premium seat for a Standard seat and PerkFlex Rewards (pending) ----------
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

-- ---------- 5. buy one more checked bag with points ----------
CREATE OR REPLACE FUNCTION pf_redeem_bag(p_passenger text, p_booking text, p_idem text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_prev jsonb; v_allow int; v_d dim_benefit; c fact_flight_campaign; v_txn text; r record; v_msg text;
BEGIN
  v_prev := pf_replay(p_idem, p_booking); IF v_prev IS NOT NULL THEN RETURN v_prev; END IF;
  b := pf_require_window(p_passenger, p_booking, p_now);
  v_allow := pf_bag_allowance(p_booking);
  IF v_allow >= 3 THEN RAISE EXCEPTION 'The demo supports up to three checked bags'; END IF;
  SELECT * INTO v_d FROM dim_benefit WHERE benefit_type = 'BAG' AND bag_ordinal = v_allow + 1;
  SELECT * INTO c FROM fact_flight_campaign WHERE flight_id = b.flight_id FOR UPDATE;
  IF c.bag_grants_remaining < 1 THEN
    v_msg := 'No bag allowances are left to grant on this flight.';
    v_txn := pf_record_txn(p_booking, v_d.benefit_id, 'REDEEM', 'FAILED', 0, 0, 0, v_d.perkflex_redeem_points, NULL, p_idem, false, v_msg, p_now);
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', v_msg);
  END IF;
  v_txn := pf_record_txn(p_booking, v_d.benefit_id, 'REDEEM', 'ACCEPTED', 0, 0, 0, 0, NULL, p_idem, false, NULL, p_now);
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
  VALUES ('PB' || lpad(nextval('pf_txn_seq')::text, 4, '0'), p_booking, v_d.benefit_id, 'PERKFLEX', v_txn, 0, 'CHECKIN', 0, 0, 1);
  UPDATE fact_flight_campaign SET bag_grants_remaining = bag_grants_remaining - 1, updated_time_utc = p_now WHERE flight_id = b.flight_id;
  RETURN jsonb_build_object('ok', true, 'transaction_id', v_txn, 'perkflex_points_used', r.o_pf,
    'rapid_rewards_points_used', r.o_rr, 'message', v_d.benefit_name || ' added');
END $$;

-- ---------- 6. upgrade the seat (p_target: PREFERRED or EXTRA_LEGROOM) ----------
CREATE OR REPLACE FUNCTION pf_redeem_seat(p_passenger text, p_booking text, p_target text, p_idem text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_prev jsonb; v_cur dim_seat; v_new dim_seat; v_d dim_benefit; v_txn text; r record;
        v_price int; v_covered boolean; v_order text[] := ARRAY['STANDARD','PREFERRED','EXTRA_LEGROOM']; v_msg text;
BEGIN
  v_prev := pf_replay(p_idem, p_booking); IF v_prev IS NOT NULL THEN RETURN v_prev; END IF;
  IF p_target NOT IN ('PREFERRED','EXTRA_LEGROOM') THEN RAISE EXCEPTION 'Choose Preferred or Extra Legroom'; END IF;
  b := pf_require_window(p_passenger, p_booking, p_now);
  SELECT * INTO v_cur FROM dim_seat WHERE seat_id = b.seat_id FOR UPDATE;
  IF array_position(v_order, v_cur.seat_type) >= array_position(v_order, p_target) THEN
    RAISE EXCEPTION 'Your current seat already includes this benefit';
  END IF;
  IF b.seat_waiver_flag THEN
    RAISE EXCEPTION 'Your trip-specific seat waiver prevents a free reclaim. Seat repurchases are outside this demo';
  END IF;
  SELECT * INTO v_d FROM dim_benefit WHERE benefit_type = 'SEAT' AND seat_class = p_target;
  -- Seat access the traveller already owns (fare, tier or card) is given at no cost
  SELECT EXISTS (SELECT 1 FROM fact_passenger_benefit pb JOIN dim_benefit d USING (benefit_id)
                  WHERE pb.booking_id = p_booking AND d.benefit_type = 'SEAT'
                    AND array_position(v_order, d.seat_class) >= array_position(v_order, p_target)
                    AND (pb.eligible_quantity + pb.granted_quantity - pb.released_quantity) > 0) INTO v_covered;
  v_price := CASE WHEN v_covered THEN 0 ELSE v_d.perkflex_redeem_points END;
  SELECT * INTO v_new FROM dim_seat WHERE flight_id = b.flight_id AND seat_type = p_target
     AND seat_status IN ('AVAILABLE','RELEASED') ORDER BY row_number, seat_number LIMIT 1 FOR UPDATE;
  IF NOT FOUND THEN
    v_msg := 'No ' || v_d.benefit_name || 's are available. Your booking is unchanged.';
    v_txn := pf_record_txn(p_booking, v_d.benefit_id, 'REDEEM', 'FAILED', 0, 0, 0, v_price, NULL, p_idem, false, v_msg, p_now);
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', v_msg);
  END IF;
  v_txn := pf_record_txn(p_booking, v_d.benefit_id, 'REDEEM', 'ACCEPTED', 0, 0, 0, 0, v_new.seat_id, p_idem, false, NULL, p_now);
  IF v_price > 0 THEN
    SELECT * INTO r FROM pf_pay(p_passenger, p_booking, v_txn, v_price, p_now);
    IF NOT r.o_ok THEN
      v_msg := 'Not enough points. Your balance and benefits are unchanged.';
      UPDATE fact_perkflex_transaction SET transaction_status = 'FAILED', status_reason = v_msg,
        total_benefit_price_points = v_price, replacement_seat_id = NULL WHERE transaction_id = v_txn;
      RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', v_msg);
    END IF;
    UPDATE fact_perkflex_transaction SET perkflex_points_used = r.o_pf, rapid_rewards_points_used = r.o_rr,
      total_benefit_price_points = v_price WHERE transaction_id = v_txn;
  END IF;
  UPDATE dim_seat SET seat_status = 'ASSIGNED' WHERE seat_id = v_new.seat_id;
  UPDATE dim_seat SET seat_status = 'AVAILABLE' WHERE seat_id = v_cur.seat_id;
  UPDATE fact_booking SET seat_id = v_new.seat_id WHERE booking_id = p_booking;
  IF NOT v_covered THEN
    INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code,
      eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity)
    VALUES ('PB' || lpad(nextval('pf_txn_seq')::text, 4, '0'), p_booking, v_d.benefit_id, 'PERKFLEX', v_txn, 0, 'CHECKIN', 0, 0, 1);
  END IF;
  RETURN jsonb_build_object('ok', true, 'transaction_id', v_txn, 'old_seat', v_cur.seat_number, 'new_seat', v_new.seat_number,
    'points_charged', v_price, 'message', CASE WHEN v_covered THEN 'This seat is already covered by your benefits. No points charged.' ELSE v_d.benefit_name || ' added' END);
END $$;

-- ---------- 7. complete web check-in (locks PerkFlex) ----------
CREATE OR REPLACE FUNCTION pf_complete_checkin(p_passenger text, p_booking text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_allow int; v_bags int;
BEGIN
  b := pf_require_window(p_passenger, p_booking, p_now);
  v_allow := pf_bag_allowance(p_booking);
  v_bags := COALESCE(b.actual_bag_count, b.expected_bag_count);
  IF v_bags > v_allow THEN
    RAISE EXCEPTION 'You have more bags than your allowance. Add a bag or update the number you are bringing.';
  END IF;
  UPDATE fact_booking SET booking_status = 'CHECKED_IN', checkin_completed_time_utc = p_now,
         actual_bag_count = v_bags WHERE booking_id = p_booking;
  -- mark the bag units in use, lowest ordinal first
  UPDATE fact_passenger_benefit pb SET used_quantity = 1
    FROM dim_benefit d
   WHERE pb.benefit_id = d.benefit_id AND pb.booking_id = p_booking AND d.benefit_type = 'BAG'
     AND (pb.eligible_quantity + pb.granted_quantity - pb.released_quantity) > 0 AND d.bag_ordinal <= v_bags;
  RETURN jsonb_build_object('ok', true, 'message', 'You are checked in. PerkFlex changes are now closed.');
END $$;

-- ---------- 8. complete the flight (airline admin): post pending points exactly once ----------
CREATE OR REPLACE FUNCTION pf_complete_flight(p_flight text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE f dim_flight_schedule; v_pend record; v_posted int := 0; v_pf int := 0; v_bookings int := 0; v_id text;
BEGIN
  SELECT * INTO f FROM dim_flight_schedule WHERE flight_id = p_flight FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Flight % not found', p_flight; END IF;
  IF f.flight_status = 'COMPLETED' THEN
    RETURN jsonb_build_object('ok', true, 'posted_entries', 0, 'message', 'Flight was already completed; nothing posted');
  END IF;
  FOR v_pend IN
    SELECT pt.* FROM fact_point_transaction pt JOIN fact_booking b USING (booking_id)
     WHERE b.flight_id = p_flight AND b.booking_status = 'CHECKED_IN'
       AND pt.transaction_type IN ('RELEASE_PENDING','FLIGHT_EARN_PENDING')
       AND NOT EXISTS (SELECT 1 FROM fact_point_transaction x WHERE x.source_point_transaction_id = pt.point_transaction_id)
     ORDER BY pt.point_transaction_id FOR UPDATE OF b
  LOOP
    IF v_pend.transaction_type = 'RELEASE_PENDING' THEN
      v_id := pf_ledger(v_pend.passenger_id, v_pend.booking_id, v_pend.perkflex_transaction_id, 'PERKFLEX', 'RELEASE_POST', v_pend.points_delta, 'POSTED', false, p_now, v_pend.point_transaction_id);
      UPDATE fact_points_wallet SET perkflex_pending = perkflex_pending - v_pend.points_delta,
        perkflex_available = perkflex_available + v_pend.points_delta, wallet_version = wallet_version + 1, updated_time_utc = p_now
       WHERE passenger_id = v_pend.passenger_id;
      UPDATE fact_flight_campaign SET budget_reserved_points = budget_reserved_points - v_pend.points_delta,
        budget_settled_points = budget_settled_points + v_pend.points_delta, updated_time_utc = p_now WHERE flight_id = p_flight;
      UPDATE fact_perkflex_transaction SET transaction_status = 'SETTLED' WHERE transaction_id = v_pend.perkflex_transaction_id;
      v_pf := v_pf + v_pend.points_delta;
    ELSE
      v_id := pf_ledger(v_pend.passenger_id, v_pend.booking_id, NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_POST', v_pend.points_delta, 'POSTED', true, p_now, v_pend.point_transaction_id);
      UPDATE fact_points_wallet SET rapid_rewards_pending = rapid_rewards_pending - v_pend.points_delta,
        rapid_rewards_available = rapid_rewards_available + v_pend.points_delta, wallet_version = wallet_version + 1, updated_time_utc = p_now
       WHERE passenger_id = v_pend.passenger_id;
    END IF;
    v_posted := v_posted + 1;
  END LOOP;
  UPDATE fact_booking SET booking_status = 'FLOWN' WHERE flight_id = p_flight AND booking_status = 'CHECKED_IN';
  GET DIAGNOSTICS v_bookings = ROW_COUNT;
  UPDATE dim_flight_schedule SET flight_status = 'COMPLETED' WHERE flight_id = p_flight;
  UPDATE fact_flight_campaign SET campaign_status = 'CLOSED', updated_time_utc = p_now WHERE flight_id = p_flight;
  RETURN jsonb_build_object('ok', true, 'posted_entries', v_posted, 'perkflex_points_posted', v_pf, 'bookings_flown', v_bookings);
END $$;
