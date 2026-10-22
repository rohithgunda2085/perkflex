-- Support for the Python API (additive; nothing existing is dropped or rewritten).
--   1. confirmation_code: the code travellers see ("R8H6WF"); booking_id stays the internal key.
--   2. pf_booking_seq: ids for bookings made through the API.
--   3. pf_complete_booking: completes ONE traveller's trip and posts that booking's pending points exactly once.
--      (pf_complete_flight completes every checked-in traveller on the flight, which is not what a single
--      traveller pressing "Complete trip" should do.)
BEGIN;

ALTER TABLE fact_booking ADD COLUMN IF NOT EXISTS confirmation_code text;
UPDATE fact_booking SET confirmation_code = booking_id WHERE confirmation_code IS NULL;
-- Rohith's presentation trip keeps the confirmation code used in the demo script.
UPDATE fact_booking SET confirmation_code = 'R8H6WF' WHERE booking_id = 'B14' AND confirmation_code = 'B14';
ALTER TABLE fact_booking ALTER COLUMN confirmation_code SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_confirmation ON fact_booking (confirmation_code);

CREATE SEQUENCE IF NOT EXISTS pf_booking_seq START 100;

CREATE OR REPLACE FUNCTION pf_complete_booking(p_passenger text, p_booking text, p_now timestamptz DEFAULT now())
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b fact_booking; v_pend record; v_posted int := 0; v_pf int := 0; v_rr int := 0; v_id text;
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

  UPDATE fact_booking SET booking_status = 'FLOWN' WHERE booking_id = p_booking;
  RETURN jsonb_build_object('ok', true, 'posted_entries', v_posted,
                            'perkflex_points_posted', v_pf, 'rapid_rewards_points_posted', v_rr);
END $$;

COMMIT;
