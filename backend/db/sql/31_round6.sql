-- Round 6 (additive):
--   1. Reward policy: release rewards for bags and seats can follow the benefit's cash value (mode VALUE) instead of
--      the flat numbers (mode FLAT, the default). Every change is written to fact_policy_audit.
--   2. Completion bonus: a small PerkFlex bonus when a trip with a posted release is completed, paid from the
--      flight's reward budget.
--   3. Travel groups and point gifts: invite companions (they must accept), then give PerkFlex points inside the
--      group, with limits.
--   4. Points sales and price watches: the airline can discount a benefit's points price on one flight; a traveller
--      can watch a benefit and is told when its price drops. The redeem functions charge the sale price.
-- The ledger gains three types: COMPLETION_BONUS, GIFT_OUT, GIFT_IN. They count as lots for the 12-month expiry.
BEGIN;

-- ---- 1. reward policy ----
CREATE TABLE IF NOT EXISTS dim_reward_policy (
  policy_id        integer PRIMARY KEY CHECK (policy_id = 1),
  release_mode     text NOT NULL DEFAULT 'FLAT' CHECK (release_mode IN ('FLAT','VALUE')),
  value_percent    integer NOT NULL DEFAULT 18 CHECK (value_percent BETWEEN 1 AND 60),
  cents_per_point  numeric(5,2) NOT NULL DEFAULT 1 CHECK (cents_per_point > 0),
  completion_bonus integer NOT NULL DEFAULT 50 CHECK (completion_bonus BETWEEN 0 AND 500),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
INSERT INTO dim_reward_policy (policy_id) VALUES (1) ON CONFLICT (policy_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS fact_policy_audit (
  audit_id    bigserial PRIMARY KEY,
  changed_at  timestamptz NOT NULL DEFAULT now(),
  changed_by  text NOT NULL,
  setting     text NOT NULL,
  old_value   text,
  new_value   text
);

-- The reward before any status bonus. VALUE mode: percent of the cash price, at the airline's value per point.
-- Only bags and seats follow value; small perks stay flat so their 300-point cap keeps its meaning. A bag is
-- always valued at the first bag's price, so the number does not depend on which bag is released.
CREATE OR REPLACE FUNCTION pf_release_base(p_benefit text) RETURNS integer LANGUAGE sql STABLE AS $$
  SELECT CASE
           WHEN pol.release_mode = 'VALUE' AND d.benefit_type IN ('BAG','SEAT') AND d.release_eligible_flag THEN
             floor((CASE WHEN d.benefit_type = 'BAG' THEN b1.cash_addon_cents ELSE d.cash_addon_cents END)
                   * pol.value_percent / 100.0 / pol.cents_per_point + 0.5)::int
           ELSE d.perkflex_release_points END
    FROM dim_benefit d
   CROSS JOIN dim_reward_policy pol
   CROSS JOIN (SELECT cash_addon_cents FROM dim_benefit WHERE benefit_id = 'BAG1') b1
   WHERE d.benefit_id = p_benefit AND pol.policy_id = 1;
$$;

CREATE OR REPLACE FUNCTION pf_release_points(p_passenger text, p_benefit text) RETURNS integer
LANGUAGE sql STABLE AS $$
  SELECT floor(pf_release_base(p_benefit) * (100 + COALESCE(t.release_bonus_pct, 0)) / 100.0 + 0.5)::int
    FROM dim_passenger p LEFT JOIN dim_tier_bonus t ON t.tier_status = p.tier_status
   WHERE p.passenger_id = p_passenger;
$$;

-- ---- ledger: three new types ----
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
  ('SEED','FLIGHT_EARN_PENDING','FLIGHT_EARN_POST','RELEASE_PENDING','RELEASE_POST','BENEFIT_DEBIT','REFUND','VOID',
   'EXPIRY','COMPLETION_BONUS','GIFT_OUT','GIFT_IN'));
ALTER TABLE fact_point_transaction ADD CONSTRAINT fact_point_transaction_round6_check CHECK (
  transaction_type NOT IN ('COMPLETION_BONUS','GIFT_OUT','GIFT_IN')
  OR (point_type = 'PERKFLEX' AND point_status = 'POSTED'
      AND (transaction_type = 'GIFT_OUT' AND points_delta < 0 OR transaction_type <> 'GIFT_OUT' AND points_delta > 0)));

-- Unspent PerkFlex lots: releases, completion bonuses and gifts received count as earned; purchases, expiry and gifts
-- given count as spent. Oldest lots are used first.
CREATE OR REPLACE FUNCTION pf_expiry_lots(p_passenger text)
RETURNS TABLE (points int, posted_at timestamptz, expires_at timestamptz) LANGUAGE plpgsql STABLE AS $$
DECLARE v_used int; r record; v_take int; v_left int;
BEGIN
  SELECT COALESCE(-sum(points_delta), 0) INTO v_used FROM fact_point_transaction
   WHERE passenger_id = p_passenger AND point_type = 'PERKFLEX' AND transaction_type IN ('BENEFIT_DEBIT','EXPIRY','GIFT_OUT');
  FOR r IN SELECT points_delta AS d, transaction_time_utc AS t FROM fact_point_transaction
            WHERE passenger_id = p_passenger AND point_type = 'PERKFLEX'
              AND transaction_type IN ('RELEASE_POST','COMPLETION_BONUS','GIFT_IN')
            ORDER BY transaction_time_utc, point_transaction_id LOOP
    v_take := LEAST(v_used, r.d); v_used := v_used - v_take; v_left := r.d - v_take;
    IF v_left > 0 THEN
      points := v_left; posted_at := r.t; expires_at := r.t + interval '12 months'; RETURN NEXT;
    END IF;
  END LOOP;
END $$;

-- ---- 2. completion bonus ----
CREATE OR REPLACE FUNCTION pf_complete_booking(p_passenger text, p_booking text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_pend record; v_posted int := 0; v_pf int := 0; v_rr int := 0; v_id text;
        v_bonus int := 0; pol dim_reward_policy; c fact_flight_campaign;
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

  UPDATE fact_booking SET booking_status = 'FLOWN' WHERE booking_id = p_booking;
  RETURN jsonb_build_object('ok', true, 'posted_entries', v_posted,
                            'perkflex_points_posted', v_pf, 'rapid_rewards_points_posted', v_rr,
                            'completion_bonus', v_bonus);
END $$;

-- ---- 3. travel groups and gifts ----
CREATE TABLE IF NOT EXISTS fact_group_member (
  group_id     text NOT NULL REFERENCES dim_passenger(passenger_id),   -- the organiser's passenger id
  passenger_id text NOT NULL REFERENCES dim_passenger(passenger_id),
  status       text NOT NULL CHECK (status IN ('INVITED','ACTIVE')),
  invited_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, passenger_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_group ON fact_group_member (passenger_id) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS fact_gift (
  gift_id         text PRIMARY KEY,
  group_id        text NOT NULL,
  from_passenger  text NOT NULL REFERENCES dim_passenger(passenger_id),
  to_passenger    text NOT NULL REFERENCES dim_passenger(passenger_id),
  points          integer NOT NULL CHECK (points > 0),
  idempotency_key text NOT NULL UNIQUE,
  recorded_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (from_passenger <> to_passenger)
);
CREATE INDEX IF NOT EXISTS ix_gift_from ON fact_gift (from_passenger, recorded_at);
CREATE INDEX IF NOT EXISTS ix_gift_to ON fact_gift (to_passenger, recorded_at);
CREATE SEQUENCE IF NOT EXISTS pf_gift_seq START 1;

CREATE OR REPLACE FUNCTION pf_group_invite(p_organiser text, p_companion text) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE v_name text; v_size int;
BEGIN
  IF p_organiser = p_companion THEN RAISE EXCEPTION 'You cannot invite yourself'; END IF;
  SELECT passenger_name INTO v_name FROM dim_passenger WHERE passenger_id = p_companion;
  IF NOT FOUND THEN RAISE EXCEPTION 'We could not find that traveller'; END IF;
  IF EXISTS (SELECT 1 FROM fact_group_member WHERE passenger_id = p_organiser AND status = 'ACTIVE' AND group_id <> p_organiser) THEN
    RAISE EXCEPTION 'You are in someone else''s travel group. Leave it first to start your own';
  END IF;
  INSERT INTO fact_group_member (group_id, passenger_id, status) VALUES (p_organiser, p_organiser, 'ACTIVE')
    ON CONFLICT (group_id, passenger_id) DO NOTHING;
  SELECT count(*) INTO v_size FROM fact_group_member WHERE group_id = p_organiser;
  IF v_size >= 6 THEN RAISE EXCEPTION 'A travel group can have up to 6 travellers'; END IF;
  IF EXISTS (SELECT 1 FROM fact_group_member WHERE group_id = p_organiser AND passenger_id = p_companion) THEN
    RAISE EXCEPTION '% is already in your group or has been invited', v_name;
  END IF;
  IF EXISTS (SELECT 1 FROM fact_group_member WHERE passenger_id = p_companion AND status = 'ACTIVE') THEN
    RAISE EXCEPTION '% is already in another travel group', v_name;
  END IF;
  INSERT INTO fact_group_member (group_id, passenger_id, status) VALUES (p_organiser, p_companion, 'INVITED');
  RETURN jsonb_build_object('ok', true, 'message', 'Invitation sent to ' || v_name);
END $$;

CREATE OR REPLACE FUNCTION pf_group_respond(p_passenger text, p_group text, p_accept boolean) RETURNS jsonb
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM fact_group_member WHERE group_id = p_group AND passenger_id = p_passenger AND status = 'INVITED') THEN
    RAISE EXCEPTION 'That invitation is no longer available';
  END IF;
  IF NOT p_accept THEN
    DELETE FROM fact_group_member WHERE group_id = p_group AND passenger_id = p_passenger;
    RETURN jsonb_build_object('ok', true, 'message', 'Invitation declined');
  END IF;
  IF EXISTS (SELECT 1 FROM fact_group_member WHERE passenger_id = p_passenger AND status = 'ACTIVE') THEN
    RAISE EXCEPTION 'Leave your current travel group before joining another';
  END IF;
  UPDATE fact_group_member SET status = 'ACTIVE' WHERE group_id = p_group AND passenger_id = p_passenger;
  RETURN jsonb_build_object('ok', true, 'message', 'You joined the travel group');
END $$;

-- A member leaves; if the organiser leaves, the group ends.
CREATE OR REPLACE FUNCTION pf_group_leave(p_passenger text) RETURNS jsonb
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM fact_group_member WHERE group_id = p_passenger AND passenger_id = p_passenger) THEN
    DELETE FROM fact_group_member WHERE group_id = p_passenger;
    RETURN jsonb_build_object('ok', true, 'message', 'Your travel group has ended');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM fact_group_member WHERE passenger_id = p_passenger) THEN
    RAISE EXCEPTION 'You are not in a travel group';
  END IF;
  DELETE FROM fact_group_member WHERE passenger_id = p_passenger;
  RETURN jsonb_build_object('ok', true, 'message', 'You left the travel group');
END $$;

-- Gives PerkFlex points to someone in the same group. Limits (real time, not the demo clock):
--   100 to 2,000 points per gift; 3,000 given and 3,000 received per 24 hours; points you were given in the last
--   24 hours cannot be passed on (no chains). Only available PerkFlex points can be given, never pending ones.
CREATE OR REPLACE FUNCTION pf_gift_points(p_from text, p_to text, p_points int, p_idem text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_group text; v_name text; w fact_points_wallet; v_sent int; v_recv int; v_id text; v_prev fact_gift;
BEGIN
  SELECT * INTO v_prev FROM fact_gift WHERE idempotency_key = p_idem;
  IF FOUND THEN
    RETURN jsonb_build_object('ok', true, 'replayed', true, 'points', v_prev.points, 'message', 'That gift was already sent');
  END IF;
  IF p_from = p_to THEN RAISE EXCEPTION 'You cannot give points to yourself'; END IF;
  IF p_points < 100 OR p_points > 2000 THEN RAISE EXCEPTION 'A gift can be 100 to 2,000 points'; END IF;
  SELECT a.group_id INTO v_group FROM fact_group_member a JOIN fact_group_member b ON b.group_id = a.group_id
   WHERE a.passenger_id = p_from AND a.status = 'ACTIVE' AND b.passenger_id = p_to AND b.status = 'ACTIVE';
  IF v_group IS NULL THEN RAISE EXCEPTION 'You can only give points to travellers in your travel group'; END IF;
  SELECT passenger_name INTO v_name FROM dim_passenger WHERE passenger_id = p_to;
  PERFORM 1 FROM fact_points_wallet WHERE passenger_id IN (p_from, p_to) ORDER BY passenger_id FOR UPDATE;
  SELECT * INTO w FROM fact_points_wallet WHERE passenger_id = p_from;
  IF w.perkflex_available < p_points THEN
    RAISE EXCEPTION 'You have % PerkFlex points available to give', w.perkflex_available;
  END IF;
  IF EXISTS (SELECT 1 FROM fact_gift WHERE to_passenger = p_from AND recorded_at > now() - interval '24 hours') THEN
    RAISE EXCEPTION 'Points you were given in the last 24 hours cannot be passed on yet';
  END IF;
  SELECT COALESCE(sum(points), 0) INTO v_sent FROM fact_gift WHERE from_passenger = p_from AND recorded_at > now() - interval '24 hours';
  IF v_sent + p_points > 3000 THEN RAISE EXCEPTION 'You can give up to 3,000 points in 24 hours (% given so far)', v_sent; END IF;
  SELECT COALESCE(sum(points), 0) INTO v_recv FROM fact_gift WHERE to_passenger = p_to AND recorded_at > now() - interval '24 hours';
  IF v_recv + p_points > 3000 THEN RAISE EXCEPTION '% can receive up to 3,000 points in 24 hours', v_name; END IF;

  v_id := 'G' || lpad(nextval('pf_gift_seq')::text, 4, '0');
  INSERT INTO fact_gift (gift_id, group_id, from_passenger, to_passenger, points, idempotency_key)
    VALUES (v_id, v_group, p_from, p_to, p_points, p_idem);
  PERFORM pf_ledger(p_from, NULL, NULL, 'PERKFLEX', 'GIFT_OUT', -p_points, 'POSTED', false, p_now, NULL);
  PERFORM pf_ledger(p_to, NULL, NULL, 'PERKFLEX', 'GIFT_IN', p_points, 'POSTED', false, p_now, NULL);
  UPDATE fact_points_wallet SET perkflex_available = perkflex_available - p_points,
    wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_from;
  UPDATE fact_points_wallet SET perkflex_available = perkflex_available + p_points,
    wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_to;
  RETURN jsonb_build_object('ok', true, 'gift_id', v_id, 'points', p_points,
                            'message', p_points || ' PerkFlex points sent to ' || v_name);
END $$;

-- ---- 4. points sales and price watches ----
CREATE TABLE IF NOT EXISTS fact_price_sale (
  flight_id    text NOT NULL,
  benefit_key  text NOT NULL CHECK (benefit_key IN ('bag','preferred','extra','boarding','drink','standby','overweight')),
  discount_pct integer NOT NULL CHECK (discount_pct BETWEEN 5 AND 50),
  set_by       text NOT NULL,
  set_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (flight_id, benefit_key)
);
CREATE TABLE IF NOT EXISTS fact_price_watch (
  passenger_id text NOT NULL REFERENCES dim_passenger(passenger_id),
  benefit_key  text NOT NULL CHECK (benefit_key IN ('bag','preferred','extra','boarding','drink','standby','overweight')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (passenger_id, benefit_key)
);

CREATE OR REPLACE FUNCTION pf_benefit_key(p_benefit text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE p_benefit WHEN 'BAG1' THEN 'bag' WHEN 'BAG2' THEN 'bag' WHEN 'BAG3' THEN 'bag'
    WHEN 'SEAT_PREF' THEN 'preferred' WHEN 'SEAT_XL' THEN 'extra' WHEN 'PERK_BOARDING' THEN 'boarding'
    WHEN 'PERK_DRINK' THEN 'drink' WHEN 'PERK_STANDBY' THEN 'standby' WHEN 'PERK_OVERWEIGHT' THEN 'overweight' END;
$$;

-- The points price on a flight: the list price, less any sale the airline set for that flight (half up).
CREATE OR REPLACE FUNCTION pf_redeem_price(p_flight text, p_benefit text) RETURNS integer LANGUAGE sql STABLE AS $$
  SELECT floor(d.perkflex_redeem_points * (100 - COALESCE(s.discount_pct, 0)) / 100.0 + 0.5)::int
    FROM dim_benefit d
    LEFT JOIN fact_price_sale s ON s.flight_id = p_flight AND s.benefit_key = pf_benefit_key(d.benefit_id)
   WHERE d.benefit_id = p_benefit;
$$;

-- ---- the redeem functions charge the sale price (generated from the live definitions; only the price changed) ----
CREATE OR REPLACE FUNCTION pf_redeem_bag(p_passenger text, p_booking text, p_idem text, p_now timestamp with time zone DEFAULT now())
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
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
    v_txn := pf_record_txn(p_booking, v_d.benefit_id, 'REDEEM', 'FAILED', 0, 0, 0, pf_redeem_price(b.flight_id, v_d.benefit_id), NULL, p_idem, false, v_msg, p_now);
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', v_msg);
  END IF;
  v_txn := pf_record_txn(p_booking, v_d.benefit_id, 'REDEEM', 'ACCEPTED', 0, 0, 0, 0, NULL, p_idem, false, NULL, p_now);
  SELECT * INTO r FROM pf_pay(p_passenger, p_booking, v_txn, pf_redeem_price(b.flight_id, v_d.benefit_id), p_now);
  IF NOT r.o_ok THEN
    v_msg := 'Not enough points. Your balance and benefits are unchanged.';
    UPDATE fact_perkflex_transaction SET transaction_status = 'FAILED', status_reason = v_msg,
      total_benefit_price_points = pf_redeem_price(b.flight_id, v_d.benefit_id) WHERE transaction_id = v_txn;
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', v_msg);
  END IF;
  UPDATE fact_perkflex_transaction SET perkflex_points_used = r.o_pf, rapid_rewards_points_used = r.o_rr,
    total_benefit_price_points = pf_redeem_price(b.flight_id, v_d.benefit_id) WHERE transaction_id = v_txn;
  INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code,
    eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity)
  VALUES ('PB' || lpad(nextval('pf_txn_seq')::text, 4, '0'), p_booking, v_d.benefit_id, 'PERKFLEX', v_txn, 0, 'CHECKIN', 0, 0, 1);
  UPDATE fact_flight_campaign SET bag_grants_remaining = bag_grants_remaining - 1, updated_time_utc = p_now WHERE flight_id = b.flight_id;
  RETURN jsonb_build_object('ok', true, 'transaction_id', v_txn, 'perkflex_points_used', r.o_pf,
    'rapid_rewards_points_used', r.o_rr, 'message', v_d.benefit_name || ' added');
END $function$;

CREATE OR REPLACE FUNCTION pf_redeem_seat(p_passenger text, p_booking text, p_target text, p_idem text, p_now timestamp with time zone DEFAULT now())
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
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
  v_price := CASE WHEN v_covered THEN 0 ELSE pf_redeem_price(b.flight_id, v_d.benefit_id) END;
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
END $function$;

CREATE OR REPLACE FUNCTION pf_redeem_perk(p_passenger text, p_booking text, p_benefit text, p_idem text, p_now timestamp with time zone DEFAULT now())
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
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
  SELECT * INTO r FROM pf_pay(p_passenger, p_booking, v_txn, pf_redeem_price(b.flight_id, v_d.benefit_id), p_now);
  IF NOT r.o_ok THEN
    v_msg := 'Not enough points. Your balance and benefits are unchanged.';
    UPDATE fact_perkflex_transaction SET transaction_status = 'FAILED', status_reason = v_msg,
      total_benefit_price_points = pf_redeem_price(b.flight_id, v_d.benefit_id) WHERE transaction_id = v_txn;
    RETURN jsonb_build_object('ok', false, 'transaction_id', v_txn, 'message', v_msg);
  END IF;
  UPDATE fact_perkflex_transaction SET perkflex_points_used = r.o_pf, rapid_rewards_points_used = r.o_rr,
    total_benefit_price_points = pf_redeem_price(b.flight_id, v_d.benefit_id) WHERE transaction_id = v_txn;
  INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code,
    eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity)
  VALUES ('PB' || lpad(nextval('pf_txn_seq')::text, 4, '0'), p_booking, p_benefit, 'PERKFLEX', v_txn, 0, 'CHECKIN', 0, 0, 1);
  RETURN jsonb_build_object('ok', true, 'transaction_id', v_txn, 'perkflex_points_used', r.o_pf,
    'rapid_rewards_points_used', r.o_rr, 'message', v_d.benefit_name || ' added');
END $function$;

-- ---- demo reset also clears groups, gifts, sales, watches and puts the reward policy back to its defaults ----
CREATE OR REPLACE FUNCTION pf_demo_restore() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path FROM CURRENT AS $$
DECLARE t text; cols text;
BEGIN
  IF to_regclass('demo_seed_fact_booking') IS NULL THEN
    RAISE EXCEPTION 'There is no demo snapshot to restore. Run SELECT pf_demo_snapshot(true) on a clean demo first.';
  END IF;
  PERFORM pg_advisory_xact_lock(727274);  -- one reset at a time
  ALTER TABLE fact_point_transaction DISABLE TRIGGER USER;  -- the append-only guard; re-enabled below, same transaction
  TRUNCATE dim_flight_schedule, dim_seat, fact_flight_campaign, fact_booking, fact_passenger_benefit,
           fact_points_wallet, fact_perkflex_transaction, fact_point_transaction;
  FOREACH t IN ARRAY pf_demo_tables() LOOP
    cols := pf_demo_columns(t);
    EXECUTE format('INSERT INTO %I (%s) SELECT %s FROM %I', t, cols, cols, 'demo_seed_' || t);
  END LOOP;
  ALTER TABLE fact_point_transaction ENABLE TRIGGER USER;
  TRUNCATE fact_group_member, fact_gift, fact_price_sale, fact_price_watch;
  UPDATE dim_reward_policy SET release_mode = 'FLAT', value_percent = 18, cents_per_point = 1, completion_bonus = 50,
         updated_at = now() WHERE policy_id = 1;
  RETURN jsonb_build_object('ok', true);
END $$;

COMMIT;
