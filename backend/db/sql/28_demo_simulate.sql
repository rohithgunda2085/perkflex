-- Demo only (additive): "other travellers" on the viewer's flight act, so the audience can watch released benefits
-- being reused. The API exposes this only when DEMO_MODE is on. It does not model payment for the seat: it stands in for
-- a standby or reassigned traveller being given the open seat. Bag purchases use the real pf_redeem_bag.
BEGIN;

CREATE OR REPLACE FUNCTION pf_demo_simulate_other(p_viewer text, p_now timestamptz DEFAULT now()) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE b fact_booking; s dim_seat; o record; r jsonb; v_allow int;
BEGIN
  SELECT * INTO b FROM fact_booking WHERE passenger_id = p_viewer AND booking_status = 'BOOKED'
   ORDER BY booking_date_utc DESC LIMIT 1;
  IF NOT FOUND THEN RETURN jsonb_build_object('ok', true, 'event', 'none'); END IF;

  -- 1. a seat the viewer released goes to someone else on the flight
  SELECT * INTO s FROM dim_seat WHERE flight_id = b.flight_id AND freed_by_booking = b.booking_id
     AND reused_by_booking IS NULL AND seat_status = 'RELEASED' ORDER BY freed_time_utc LIMIT 1 FOR UPDATE;
  IF FOUND THEN
    SELECT fb.booking_id, fb.seat_id INTO o FROM fact_booking fb JOIN dim_seat cs ON cs.seat_id = fb.seat_id
     WHERE fb.flight_id = b.flight_id AND fb.booking_status = 'BOOKED' AND fb.booking_id <> b.booking_id
       AND cs.seat_type = 'STANDARD' AND fb.seat_waiver_flag = false
     ORDER BY fb.booking_id LIMIT 1 FOR UPDATE OF fb;
    IF FOUND THEN
      UPDATE dim_seat SET seat_status = 'AVAILABLE' WHERE seat_id = o.seat_id;
      UPDATE dim_seat SET seat_status = 'ASSIGNED' WHERE seat_id = s.seat_id;
      UPDATE fact_booking SET seat_id = s.seat_id WHERE booking_id = o.booking_id;  -- the trigger marks the seat reused
      RETURN jsonb_build_object('ok', true, 'event', 'seat', 'seat', s.seat_number);
    END IF;
  END IF;

  -- 2. someone else on the flight adds a checked bag with their own points
  FOR o IN
    SELECT fb.booking_id, fb.passenger_id FROM fact_booking fb JOIN fact_points_wallet w USING (passenger_id)
     WHERE fb.flight_id = b.flight_id AND fb.booking_status = 'BOOKED' AND fb.booking_id <> b.booking_id
       AND w.perkflex_available + w.rapid_rewards_available >= 3600 AND pf_bag_allowance(fb.booking_id) < 3
     ORDER BY fb.booking_id LIMIT 6
  LOOP
    BEGIN
      PERFORM pf_open_checkin(o.passenger_id, o.booking_id, p_now);
      v_allow := pf_bag_allowance(o.booking_id);
      r := pf_redeem_bag(o.passenger_id, o.booking_id, 'sim-bag:' || o.booking_id || ':' || v_allow, p_now);
      IF (r ->> 'ok')::boolean THEN
        RETURN jsonb_build_object('ok', true, 'event', 'bag');
      END IF;
    EXCEPTION WHEN OTHERS THEN
      CONTINUE;  -- this traveller cannot add a bag right now; try the next one
    END;
  END LOOP;
  RETURN jsonb_build_object('ok', true, 'event', 'none');
END $$;

COMMIT;
