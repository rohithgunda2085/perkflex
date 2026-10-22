-- The undo window is 1 minute (it was 5). To change it again, change the interval below AND UNDO_SECONDS in
-- backend/app/services/state.py, which only drives the countdown the traveller sees.
BEGIN;

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
  IF now() - t.recorded_at > interval '1 minute' THEN
    RAISE EXCEPTION 'The 1-minute window to undo this release has passed';
  END IF;
  IF (SELECT count(*) FROM fact_perkflex_transaction WHERE booking_id = p_booking AND transaction_status = 'VOID') >= 3 THEN
    RAISE EXCEPTION 'You have already undone 3 releases on this trip, so no more can be undone';
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

COMMIT;
