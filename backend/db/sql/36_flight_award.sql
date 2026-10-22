-- Every completed flight now earns a small flat PerkFlex "flight award" (25 points) alongside Rapid Rewards, even when
-- nothing was released. New ledger type FLIGHT_AWARD (a PerkFlex lot for the 12-month expiry). Applied once, after 35.
BEGIN;

ALTER TABLE dim_reward_policy ADD COLUMN IF NOT EXISTS flight_award integer NOT NULL DEFAULT 25
  CHECK (flight_award BETWEEN 0 AND 100);

DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'fact_point_transaction'::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%''SEED''%' LOOP
    EXECUTE format('ALTER TABLE fact_point_transaction DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
ALTER TABLE fact_point_transaction DROP CONSTRAINT IF EXISTS fact_point_transaction_round6_check;
ALTER TABLE fact_point_transaction ADD CONSTRAINT fact_point_transaction_type_check CHECK (transaction_type IN
  ('SEED','FLIGHT_EARN_PENDING','FLIGHT_EARN_POST','RELEASE_PENDING','RELEASE_POST','BENEFIT_DEBIT','REFUND','VOID',
   'EXPIRY','COMPLETION_BONUS','FLIGHT_AWARD','GIFT_OUT','GIFT_IN'));
ALTER TABLE fact_point_transaction ADD CONSTRAINT fact_point_transaction_round6_check CHECK (
  transaction_type NOT IN ('COMPLETION_BONUS','FLIGHT_AWARD','GIFT_OUT','GIFT_IN')
  OR (point_type = 'PERKFLEX' AND point_status = 'POSTED'
      AND (transaction_type = 'GIFT_OUT' AND points_delta < 0 OR transaction_type <> 'GIFT_OUT' AND points_delta > 0)));

CREATE OR REPLACE FUNCTION pf_expiry_lots(p_passenger text)
RETURNS TABLE (points int, posted_at timestamptz, expires_at timestamptz) LANGUAGE plpgsql STABLE AS $$
DECLARE v_used int; r record; v_take int; v_left int;
BEGIN
  SELECT COALESCE(-sum(points_delta), 0) INTO v_used FROM fact_point_transaction
   WHERE passenger_id = p_passenger AND point_type = 'PERKFLEX' AND transaction_type IN ('BENEFIT_DEBIT','EXPIRY','GIFT_OUT');
  FOR r IN SELECT points_delta AS d, transaction_time_utc AS t FROM fact_point_transaction
            WHERE passenger_id = p_passenger AND point_type = 'PERKFLEX'
              AND transaction_type IN ('RELEASE_POST','COMPLETION_BONUS','FLIGHT_AWARD','GIFT_IN')
            ORDER BY transaction_time_utc, point_transaction_id LOOP
    v_take := LEAST(v_used, r.d); v_used := v_used - v_take; v_left := r.d - v_take;
    IF v_left > 0 THEN
      points := v_left; posted_at := r.t; expires_at := r.t + interval '12 months'; RETURN NEXT;
    END IF;
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION pf_complete_booking(p_passenger text, p_booking text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_pend record; v_posted int := 0; v_pf int := 0; v_rr int := 0; v_id text;
        v_bonus int := 0; v_award int := 0; pol dim_reward_policy; c fact_flight_campaign;
BEGIN
  SELECT * INTO b FROM fact_booking WHERE booking_id = p_booking AND passenger_id = p_passenger FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Booking % was not found for this passenger', p_booking; END IF;
  IF b.booking_status = 'FLOWN' THEN
    RETURN jsonb_build_object('ok', true, 'posted_entries', 0, 'message', 'Trip was already completed; nothing posted');
  END IF;
  IF b.booking_status <> 'CHECKED_IN' THEN
    RAISE EXCEPTION 'Complete check-in before completing your trip.';
  END IF;

  FOR v_pend IN
    SELECT pt.* FROM fact_point_transaction pt
     WHERE pt.booking_id = p_booking
       AND pt.transaction_type IN ('RELEASE_PENDING','FLIGHT_EARN_PENDING')
       AND NOT EXISTS (SELECT 1 FROM fact_point_transaction x WHERE x.source_point_transaction_id = pt.point_transaction_id)
     ORDER BY pt.point_transaction_id
  LOOP
    IF v_pend.transaction_type = 'RELEASE_PENDING' THEN
      v_id := pf_ledger(v_pend.passenger_id, v_pend.booking_id, v_pend.perkflex_transaction_id, 'PERKFLEX',
                        'RELEASE_POST', v_pend.points_delta, 'POSTED', false, p_now, v_pend.point_transaction_id);
      UPDATE fact_points_wallet SET perkflex_pending = perkflex_pending - v_pend.points_delta,
        perkflex_available = perkflex_available + v_pend.points_delta,
        wallet_version = wallet_version + 1, updated_time_utc = p_now
       WHERE passenger_id = v_pend.passenger_id;
      UPDATE fact_flight_campaign SET budget_reserved_points = budget_reserved_points - v_pend.points_delta,
        budget_settled_points = budget_settled_points + v_pend.points_delta, updated_time_utc = p_now
       WHERE flight_id = b.flight_id;
      UPDATE fact_perkflex_transaction SET transaction_status = 'SETTLED'
       WHERE transaction_id = v_pend.perkflex_transaction_id;
      v_pf := v_pf + v_pend.points_delta;
    ELSE
      v_id := pf_ledger(v_pend.passenger_id, v_pend.booking_id, NULL, 'RAPID_REWARDS', 'FLIGHT_EARN_POST',
                        v_pend.points_delta, 'POSTED', true, p_now, v_pend.point_transaction_id);
      UPDATE fact_points_wallet SET rapid_rewards_pending = rapid_rewards_pending - v_pend.points_delta,
        rapid_rewards_available = rapid_rewards_available + v_pend.points_delta,
        wallet_version = wallet_version + 1, updated_time_utc = p_now
       WHERE passenger_id = v_pend.passenger_id;
      v_rr := v_rr + v_pend.points_delta;
    END IF;
    v_posted := v_posted + 1;
  END LOOP;

  -- Completion bonus: once per trip, only when a release posted, only while the flight's budget has room for it.
  SELECT * INTO pol FROM dim_reward_policy WHERE policy_id = 1;
  IF v_pf > 0 AND pol.completion_bonus > 0 THEN
    SELECT * INTO c FROM fact_flight_campaign WHERE flight_id = b.flight_id FOR UPDATE;
    IF c.campaign_status = 'OPEN' AND c.budget_remaining_points >= pol.completion_bonus THEN
      v_id := pf_ledger(p_passenger, p_booking, NULL, 'PERKFLEX', 'COMPLETION_BONUS', pol.completion_bonus,
                        'POSTED', false, p_now, NULL);
      UPDATE fact_points_wallet SET perkflex_available = perkflex_available + pol.completion_bonus,
        wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_passenger;
      UPDATE fact_flight_campaign SET budget_settled_points = budget_settled_points + pol.completion_bonus,
        updated_time_utc = p_now WHERE flight_id = b.flight_id;
      v_bonus := pol.completion_bonus;
    END IF;
  END IF;

  -- Flight award: a small flat PerkFlex amount for every completed flight, released or not. It is a thank-you, not a
  -- release payout, so it does not use the flight's campaign budget. Rapid Rewards above stay the main earning.
  SELECT * INTO pol FROM dim_reward_policy WHERE policy_id = 1;
  IF pol.flight_award > 0 THEN
    v_id := pf_ledger(p_passenger, p_booking, NULL, 'PERKFLEX', 'FLIGHT_AWARD', pol.flight_award, 'POSTED', false, p_now, NULL);
    UPDATE fact_points_wallet SET perkflex_available = perkflex_available + pol.flight_award,
      wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_passenger;
    v_award := pol.flight_award;
  END IF;

  UPDATE fact_booking SET booking_status = 'FLOWN' WHERE booking_id = p_booking;
  RETURN jsonb_build_object('ok', true, 'posted_entries', v_posted,
                            'perkflex_points_posted', v_pf, 'rapid_rewards_points_posted', v_rr,
                            'completion_bonus', v_bonus, 'flight_award', v_award);
END $$;

COMMIT;
