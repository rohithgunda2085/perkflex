-- Benefit reuse (additive). A seat a traveller releases goes back on sale; this records who freed it and who took it,
-- so the app can show "your seat was taken by another traveller" and the airline can see what is reused.
-- Counts for bags and small perks come straight from fact_passenger_benefit, so only seats need columns.
BEGIN;

ALTER TABLE dim_seat ADD COLUMN IF NOT EXISTS freed_by_booking   text;
ALTER TABLE dim_seat ADD COLUMN IF NOT EXISTS freed_time_utc     timestamptz;
ALTER TABLE dim_seat ADD COLUMN IF NOT EXISTS reused_by_booking  text;
ALTER TABLE dim_seat ADD COLUMN IF NOT EXISTS reused_time_utc    timestamptz;

CREATE OR REPLACE FUNCTION trg_booking_seat_reuse() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.seat_id IS DISTINCT FROM OLD.seat_id THEN
    -- A release moves the booking to a replacement seat in the same update that sets the waiver.
    IF NEW.seat_waiver_flag AND NOT OLD.seat_waiver_flag AND OLD.seat_id IS NOT NULL THEN
      UPDATE dim_seat SET freed_by_booking = NEW.booking_id, freed_time_utc = now(),
             reused_by_booking = NULL, reused_time_utc = NULL
       WHERE seat_id = OLD.seat_id;
    END IF;
    -- Another traveller takes a seat that was freed.
    IF NEW.seat_id IS NOT NULL THEN
      UPDATE dim_seat SET reused_by_booking = NEW.booking_id, reused_time_utc = now()
       WHERE seat_id = NEW.seat_id AND freed_by_booking IS NOT NULL AND freed_by_booking <> NEW.booking_id
         AND reused_by_booking IS NULL;
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS booking_seat_reuse ON fact_booking;
CREATE TRIGGER booking_seat_reuse AFTER UPDATE OF seat_id ON fact_booking
  FOR EACH ROW EXECUTE FUNCTION trg_booking_seat_reuse();

COMMIT;
