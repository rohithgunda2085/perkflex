-- Price watches were removed from the product (they were confusing next to the sale prices, which every traveller on
-- the flight already sees). Sales stay. Applied once, after 31.
BEGIN;

DROP TABLE IF EXISTS fact_price_watch;

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
  TRUNCATE fact_group_member, fact_gift, fact_price_sale;
  UPDATE dim_reward_policy SET release_mode = 'FLAT', value_percent = 18, cents_per_point = 1, completion_bonus = 50,
         updated_at = now() WHERE policy_id = 1;
  RETURN jsonb_build_object('ok', true);
END $$;

COMMIT;
