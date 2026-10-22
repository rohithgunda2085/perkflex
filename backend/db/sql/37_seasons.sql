-- Seasonal and festival PerkFlex: the flight award (25 points) is multiplied by the airline's rule for the flight's date.
-- Rules are date windows (SEASON or FESTIVAL) with a multiplier of 1 to 3; where windows overlap the higher one applies,
-- never both. Seeded: off-peak seasons and US holiday windows (the days around each holiday). Applied once, after 36.
BEGIN;

CREATE TABLE IF NOT EXISTS dim_season_rule (
  rule_id      serial PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('SEASON','FESTIVAL')),
  name         text NOT NULL CHECK (char_length(name) BETWEEN 2 AND 60),
  start_date   date NOT NULL,
  end_date     date NOT NULL,
  multiplier   numeric(2,1) NOT NULL CHECK (multiplier BETWEEN 1.0 AND 3.0),
  active_flag  boolean NOT NULL DEFAULT true,
  created_by   text NOT NULL DEFAULT 'seed',
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (end_date >= start_date AND end_date - start_date <= 120)
);

INSERT INTO dim_season_rule (kind, name, start_date, end_date, multiplier)
SELECT * FROM (VALUES
  ('SEASON',   'Autumn off-peak',     DATE '2026-10-05', DATE '2026-11-19', 2.0),
  ('FESTIVAL', 'Thanksgiving',        DATE '2026-11-23', DATE '2026-11-30', 2.0),
  ('FESTIVAL', 'Christmas and New Year', DATE '2026-12-18', DATE '2027-01-03', 2.0),
  ('SEASON',   'Winter off-peak',     DATE '2027-01-11', DATE '2027-02-11', 2.0),
  ('FESTIVAL', 'Memorial Day',        DATE '2027-05-28', DATE '2027-06-01', 2.0),
  ('FESTIVAL', 'Independence Day',    DATE '2027-07-01', DATE '2027-07-06', 2.0),
  ('FESTIVAL', 'Labor Day',           DATE '2027-09-03', DATE '2027-09-07', 2.0),
  ('SEASON',   'Autumn off-peak',     DATE '2027-09-08', DATE '2027-11-19', 2.0),
  ('FESTIVAL', 'Thanksgiving',        DATE '2027-11-22', DATE '2027-11-29', 2.0),
  ('FESTIVAL', 'Christmas and New Year', DATE '2027-12-18', DATE '2028-01-02', 2.0)
) v(kind, name, start_date, end_date, multiplier)
WHERE NOT EXISTS (SELECT 1 FROM dim_season_rule);

-- The rule that applies to a flight date: the highest multiplier, a festival winning a tie. No row means x1.
CREATE OR REPLACE FUNCTION pf_season_award(p_date date)
RETURNS TABLE (multiplier numeric, label text) LANGUAGE sql STABLE AS $$
  SELECT r.multiplier, r.name FROM dim_season_rule r
   WHERE r.active_flag AND p_date BETWEEN r.start_date AND r.end_date
   ORDER BY r.multiplier DESC, (r.kind = 'FESTIVAL') DESC, r.rule_id
   LIMIT 1
$$;

ALTER TABLE fact_point_transaction ADD COLUMN IF NOT EXISTS award_note text;

CREATE OR REPLACE FUNCTION pf_complete_booking(p_passenger text, p_booking text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_pend record; v_posted int := 0; v_pf int := 0; v_rr int := 0; v_id text;
        v_bonus int := 0; v_award int := 0; v_mult numeric := 1; v_label text; v_note text; pol dim_reward_policy; c fact_flight_campaign;
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

  -- Flight award: a small flat PerkFlex amount for every completed flight, released or not, scaled by the airline's
  -- season or festival rule for the flight's date (the higher one, never both). A loyalty award, not a release payout,
  -- so it does not use the flight's campaign budget. Rapid Rewards above stay the main earning.
  SELECT * INTO pol FROM dim_reward_policy WHERE policy_id = 1;
  IF pol.flight_award > 0 THEN
    SELECT s.multiplier, s.label INTO v_mult, v_label
      FROM pf_season_award((SELECT flight_date FROM dim_flight_schedule WHERE flight_id = b.flight_id)) s;
    v_mult := COALESCE(v_mult, 1);
    v_award := ROUND(pol.flight_award * v_mult)::int;
    IF v_label IS NOT NULL AND v_mult > 1 THEN
      v_note := v_label || ' x' || regexp_replace(v_mult::text, '\.0+$', '');
    END IF;
    v_id := 'PT' || lpad(nextval('pf_point_seq')::text, 4, '0');
    INSERT INTO fact_point_transaction (point_transaction_id, passenger_id, booking_id, perkflex_transaction_id,
      point_type, transaction_type, points_delta, point_status, tqp_eligible_flag, transaction_time_utc,
      source_point_transaction_id, award_note)
    VALUES (v_id, p_passenger, p_booking, NULL, 'PERKFLEX', 'FLIGHT_AWARD', v_award, 'POSTED', false, p_now, NULL, v_note);
    UPDATE fact_points_wallet SET perkflex_available = perkflex_available + v_award,
      wallet_version = wallet_version + 1, updated_time_utc = p_now WHERE passenger_id = p_passenger;
  END IF;

  UPDATE fact_booking SET booking_status = 'FLOWN' WHERE booking_id = p_booking;
  RETURN jsonb_build_object('ok', true, 'posted_entries', v_posted,
                            'perkflex_points_posted', v_pf, 'rapid_rewards_points_posted', v_rr,
                            'completion_bonus', v_bonus, 'flight_award', v_award, 'award_note', v_note);
END $$;

COMMIT;
