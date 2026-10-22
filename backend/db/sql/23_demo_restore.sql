-- Demo restore (additive). Lets the app's "Reset demo" button put the demo back to its starting point.
--
-- The points ledger is append-only, so rows cannot be deleted one by one. Instead the tables a traveller can change
-- are copied once (pf_demo_snapshot) and put back whole (pf_demo_restore). Travellers, accounts, fares and benefit
-- definitions are never touched, so nobody is signed out and passwords stay as they are.
--
-- The snapshot is taken by this migration if none exists. On a fresh database (npm run db:demo-reset) that is the
-- pristine seeded state. On a database people have already played with, run it again on a clean state:
--   SELECT pf_demo_snapshot(true);
BEGIN;

CREATE OR REPLACE FUNCTION pf_demo_tables() RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
  -- Parents before children: restored in this order.
  SELECT ARRAY['dim_flight_schedule','dim_seat','fact_flight_campaign','fact_booking','fact_passenger_benefit',
               'fact_points_wallet','fact_perkflex_transaction','fact_point_transaction'];
$$;

-- Columns that can be written (generated columns are recomputed).
CREATE OR REPLACE FUNCTION pf_demo_columns(p_table text) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum)
    FROM pg_attribute WHERE attrelid = p_table::regclass AND attnum > 0 AND NOT attisdropped AND attgenerated = '';
$$;

CREATE OR REPLACE FUNCTION pf_demo_snapshot(p_force boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path FROM CURRENT AS $$
DECLARE t text; cols text; n int := 0;
BEGIN
  IF to_regclass('demo_seed_fact_booking') IS NOT NULL AND NOT p_force THEN
    RETURN jsonb_build_object('ok', true, 'snapshot', 'kept');
  END IF;
  FOREACH t IN ARRAY pf_demo_tables() LOOP
    EXECUTE format('DROP TABLE IF EXISTS %I', 'demo_seed_' || t);
    cols := pf_demo_columns(t);
    EXECUTE format('CREATE TABLE %I AS SELECT %s FROM %I', 'demo_seed_' || t, cols, t);
    n := n + 1;
  END LOOP;
  RETURN jsonb_build_object('ok', true, 'snapshot', 'taken', 'tables', n);
END $$;

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
  RETURN jsonb_build_object('ok', true);
END $$;

SELECT pf_demo_snapshot(false);

COMMIT;
