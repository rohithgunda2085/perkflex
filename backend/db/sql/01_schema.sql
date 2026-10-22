-- PerkFlex data model v2: PostgreSQL schema (RDS PostgreSQL 14+)
-- Run order: 01_schema.sql, 02_seed.sql, 03_functions.sql
-- All data is synthetic. Booleans, enums and money follow PerkFlex_Data_Model_v2.xlsx.

-- ===================== DIMENSIONS =====================
CREATE TABLE dim_passenger (
  passenger_id              text PRIMARY KEY,
  rapid_rewards_account_id  text UNIQUE,
  passenger_name            text NOT NULL,
  tier_status               text NOT NULL CHECK (tier_status IN ('NONE','SILVER','GOLD','PLATINUM')),
  credit_card_type          text NOT NULL CHECK (credit_card_type IN ('NONE','PLUS','PREMIER','PRIORITY')),
  primary_cardholder_flag   boolean NOT NULL DEFAULT false,
  demo_story                text NOT NULL,
  CHECK (credit_card_type = 'NONE' OR primary_cardholder_flag)
);

CREATE TABLE dim_user_account (
  user_id              text PRIMARY KEY,
  passenger_id         text REFERENCES dim_passenger(passenger_id),
  login_id             text NOT NULL UNIQUE CHECK (login_id = lower(login_id)),
  password_hash        text NOT NULL,
  user_role            text NOT NULL CHECK (user_role IN ('PASSENGER','AIRLINE_ADMIN')),
  is_active_flag       boolean NOT NULL DEFAULT true,
  last_login_time_utc  timestamptz,
  CHECK ((user_role = 'PASSENGER') = (passenger_id IS NOT NULL))
);

CREATE TABLE dim_flight_schedule (
  flight_id              text PRIMARY KEY,
  carrier_code           text NOT NULL,
  flight_number          text NOT NULL,
  flight_date            date NOT NULL,
  origin_airport         text NOT NULL,
  destination_airport    text NOT NULL,
  departure_time_utc     timestamptz NOT NULL,
  arrival_time_utc       timestamptz NOT NULL,
  checkin_open_time_utc  timestamptz NOT NULL,
  fare_offset_cents      integer NOT NULL DEFAULT 0 CHECK (fare_offset_cents >= 0),
  aircraft_type          text,
  aircraft_capacity      integer CHECK (aircraft_capacity >= 0),
  distance_miles         integer CHECK (distance_miles >= 0),
  flight_status          text NOT NULL DEFAULT 'SCHEDULED' CHECK (flight_status IN ('SCHEDULED','COMPLETED','CANCELLED')),
  UNIQUE (carrier_code, flight_number, flight_date),
  CHECK (origin_airport <> destination_airport),
  CHECK (arrival_time_utc > departure_time_utc),
  CHECK (checkin_open_time_utc < departure_time_utc)
);

CREATE TABLE dim_fare (
  fare_id                        text PRIMARY KEY,
  fare_name                      text NOT NULL,
  base_fare_cents                integer NOT NULL CHECK (base_fare_cents >= 0),
  tax_cents                      integer NOT NULL CHECK (tax_cents >= 0),
  seat_access                    text NOT NULL,
  included_bags                  integer NOT NULL CHECK (included_bags BETWEEN 0 AND 3),
  boarding_group                 text NOT NULL,
  change_policy                  text NOT NULL,
  cancellation_outcome           text NOT NULL,
  flight_credit_validity_months  integer CHECK (flight_credit_validity_months > 0),
  same_day_change_standby_flag   boolean NOT NULL,
  priority_lane_flag             boolean NOT NULL,
  premium_drink_flag             boolean NOT NULL,
  refundable_flag                boolean NOT NULL,
  change_allowed_flag            boolean NOT NULL,
  earning_multiplier             integer NOT NULL CHECK (earning_multiplier > 0)
);

CREATE TABLE dim_benefit (
  benefit_id               text PRIMARY KEY,
  benefit_name             text NOT NULL,
  benefit_type             text NOT NULL CHECK (benefit_type IN ('BAG','SEAT')),
  bag_ordinal              integer CHECK (bag_ordinal BETWEEN 1 AND 3),
  seat_class               text CHECK (seat_class IN ('STANDARD','PREFERRED','EXTRA_LEGROOM')),
  perkflex_release_points  integer NOT NULL CHECK (perkflex_release_points >= 0),
  perkflex_redeem_points   integer NOT NULL CHECK (perkflex_redeem_points >= 0),
  release_eligible_flag    boolean NOT NULL,
  cash_addon_cents         integer NOT NULL CHECK (cash_addon_cents >= 0),
  CHECK ((benefit_type = 'BAG'  AND bag_ordinal IS NOT NULL AND seat_class IS NULL) OR
         (benefit_type = 'SEAT' AND seat_class  IS NOT NULL AND bag_ordinal IS NULL))
);

CREATE TABLE dim_seat (
  seat_id        text PRIMARY KEY,
  flight_id      text NOT NULL REFERENCES dim_flight_schedule(flight_id),
  seat_number    text NOT NULL,
  row_number     integer NOT NULL CHECK (row_number > 0),
  seat_type      text NOT NULL CHECK (seat_type IN ('STANDARD','PREFERRED','EXTRA_LEGROOM')),
  seat_position  text NOT NULL CHECK (seat_position IN ('WINDOW','AISLE','MIDDLE')),
  seat_status    text NOT NULL DEFAULT 'AVAILABLE' CHECK (seat_status IN ('AVAILABLE','ASSIGNED','RELEASED')),
  UNIQUE (flight_id, seat_number)
);
CREATE INDEX ix_seat_inventory ON dim_seat (flight_id, seat_type, seat_status, row_number, seat_number);

-- ===================== FACTS =====================
CREATE TABLE fact_booking (
  booking_id                  text PRIMARY KEY,
  passenger_id                text NOT NULL REFERENCES dim_passenger(passenger_id),
  flight_id                   text NOT NULL REFERENCES dim_flight_schedule(flight_id),
  fare_id                     text NOT NULL REFERENCES dim_fare(fare_id),
  seat_id                     text REFERENCES dim_seat(seat_id),
  booking_date_utc            timestamptz NOT NULL,
  booking_status              text NOT NULL CHECK (booking_status IN ('BOOKED','CHECKED_IN','FLOWN','CANCELLED','NO_SHOW')),
  cash_total_cents            integer NOT NULL CHECK (cash_total_cents >= 0),
  expected_bag_count          integer NOT NULL CHECK (expected_bag_count BETWEEN 0 AND 3),
  actual_bag_count            integer CHECK (actual_bag_count BETWEEN 0 AND 3),
  checkin_opened_time_utc     timestamptz,
  checkin_completed_time_utc  timestamptz,
  reward_release_used_flag    boolean NOT NULL DEFAULT false,
  seat_waiver_flag            boolean NOT NULL DEFAULT false,
  pref_seat                   text NOT NULL DEFAULT 'ANY' CHECK (pref_seat IN ('ANY','FRONT','EXTRA')),
  pref_refundable_flag        boolean NOT NULL DEFAULT false,
  pref_flexible_flag          boolean NOT NULL DEFAULT false,
  pref_seat_now_flag          boolean NOT NULL DEFAULT false,
  pref_early_boarding_flag    boolean NOT NULL DEFAULT false,
  pref_budget_cents           integer NOT NULL DEFAULT 45000 CHECK (pref_budget_cents > 0),
  CHECK (checkin_completed_time_utc IS NULL OR booking_status IN ('CHECKED_IN','FLOWN'))
);
-- A seat can be held by only one live booking
CREATE UNIQUE INDEX uq_booking_live_seat ON fact_booking (seat_id)
  WHERE seat_id IS NOT NULL AND booking_status IN ('BOOKED','CHECKED_IN');
CREATE INDEX ix_booking_passenger ON fact_booking (passenger_id);
CREATE INDEX ix_booking_flight ON fact_booking (flight_id, booking_status);

CREATE TABLE fact_passenger_benefit (
  passenger_benefit_id  text PRIMARY KEY,
  booking_id            text NOT NULL REFERENCES fact_booking(booking_id),
  benefit_id            text NOT NULL REFERENCES dim_benefit(benefit_id),
  benefit_source        text NOT NULL CHECK (benefit_source IN ('FARE','TIER','CARD','PERKFLEX')),
  source_code           text NOT NULL,
  eligible_quantity     integer NOT NULL CHECK (eligible_quantity IN (0,1)),
  available_from        text NOT NULL CHECK (available_from IN ('BOOKING','CHECKIN')),
  used_quantity         integer NOT NULL DEFAULT 0 CHECK (used_quantity IN (0,1)),
  released_quantity     integer NOT NULL DEFAULT 0 CHECK (released_quantity IN (0,1)),
  granted_quantity      integer NOT NULL DEFAULT 0 CHECK (granted_quantity IN (0,1)),
  UNIQUE (booking_id, benefit_id, benefit_source),
  CHECK (released_quantity <= eligible_quantity + granted_quantity),
  CHECK (used_quantity <= eligible_quantity + granted_quantity)
);

CREATE TABLE fact_flight_campaign (
  flight_id                     text PRIMARY KEY REFERENCES dim_flight_schedule(flight_id),
  reward_budget_points          integer NOT NULL CHECK (reward_budget_points >= 0),
  budget_reserved_points        integer NOT NULL DEFAULT 0 CHECK (budget_reserved_points >= 0),
  budget_settled_points         integer NOT NULL DEFAULT 0 CHECK (budget_settled_points >= 0),
  budget_remaining_points       integer GENERATED ALWAYS AS (reward_budget_points - budget_reserved_points - budget_settled_points) STORED,
  bag_grants_total              integer NOT NULL CHECK (bag_grants_total >= 0),
  bag_grants_remaining          integer NOT NULL CHECK (bag_grants_remaining >= 0),
  assumed_cost_per_point_cents  integer NOT NULL DEFAULT 1 CHECK (assumed_cost_per_point_cents >= 0),
  campaign_status               text NOT NULL DEFAULT 'OPEN' CHECK (campaign_status IN ('OPEN','CLOSED')),
  updated_time_utc              timestamptz NOT NULL DEFAULT now(),
  CHECK (budget_reserved_points + budget_settled_points <= reward_budget_points),
  CHECK (bag_grants_remaining <= bag_grants_total)
);

CREATE TABLE fact_points_wallet (
  passenger_id                  text PRIMARY KEY REFERENCES dim_passenger(passenger_id),
  rapid_rewards_available       integer NOT NULL CHECK (rapid_rewards_available >= 0),
  rapid_rewards_pending         integer NOT NULL DEFAULT 0 CHECK (rapid_rewards_pending >= 0),
  perkflex_available            integer NOT NULL DEFAULT 0 CHECK (perkflex_available >= 0),
  perkflex_pending              integer NOT NULL DEFAULT 0 CHECK (perkflex_pending >= 0),
  total_available_for_perkflex  integer GENERATED ALWAYS AS (rapid_rewards_available + perkflex_available) STORED,
  wallet_version                integer NOT NULL DEFAULT 1,
  updated_time_utc              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE fact_perkflex_transaction (
  transaction_id              text PRIMARY KEY,
  booking_id                  text NOT NULL REFERENCES fact_booking(booking_id),
  benefit_id                  text NOT NULL REFERENCES dim_benefit(benefit_id),
  action_type                 text NOT NULL CHECK (action_type IN ('RELEASE','REDEEM','SWAP')),
  transaction_status          text NOT NULL CHECK (transaction_status IN ('OFFERED','ACCEPTED','SETTLED','DECLINED','EXPIRED','FAILED','REFUNDED','VOID')),
  perkflex_points_earned      integer NOT NULL DEFAULT 0 CHECK (perkflex_points_earned >= 0),
  perkflex_points_used        integer NOT NULL DEFAULT 0 CHECK (perkflex_points_used >= 0),
  rapid_rewards_points_used   integer NOT NULL DEFAULT 0 CHECK (rapid_rewards_points_used >= 0),
  total_benefit_price_points  integer NOT NULL DEFAULT 0 CHECK (total_benefit_price_points >= 0),
  replacement_seat_id         text REFERENCES dim_seat(seat_id),
  transaction_time_utc        timestamptz,
  idempotency_key             text,
  rewarded_flag               boolean NOT NULL DEFAULT false,
  swap_group_id               text,
  status_reason               text,
  CHECK (transaction_status NOT IN ('ACCEPTED','SETTLED')
         OR perkflex_points_used + rapid_rewards_points_used = total_benefit_price_points),
  CHECK (action_type <> 'RELEASE' OR (perkflex_points_used = 0 AND rapid_rewards_points_used = 0)),
  CHECK (action_type <> 'REDEEM' OR perkflex_points_earned = 0),
  CHECK (transaction_status <> 'FAILED' OR status_reason IS NOT NULL)
);
CREATE UNIQUE INDEX uq_pf_txn_idempotency ON fact_perkflex_transaction (idempotency_key) WHERE idempotency_key IS NOT NULL;
-- One rewarded release per booking
CREATE UNIQUE INDEX uq_pf_txn_one_reward ON fact_perkflex_transaction (booking_id)
  WHERE rewarded_flag AND transaction_status IN ('ACCEPTED','SETTLED');
CREATE INDEX ix_pf_txn_booking ON fact_perkflex_transaction (booking_id);

CREATE TABLE fact_point_transaction (
  point_transaction_id         text PRIMARY KEY,
  passenger_id                 text NOT NULL REFERENCES dim_passenger(passenger_id),
  booking_id                   text REFERENCES fact_booking(booking_id),
  perkflex_transaction_id      text REFERENCES fact_perkflex_transaction(transaction_id),
  point_type                   text NOT NULL CHECK (point_type IN ('RAPID_REWARDS','PERKFLEX')),
  transaction_type             text NOT NULL CHECK (transaction_type IN ('SEED','FLIGHT_EARN_PENDING','FLIGHT_EARN_POST','RELEASE_PENDING','RELEASE_POST','BENEFIT_DEBIT','REFUND','VOID')),
  points_delta                 integer NOT NULL,
  point_status                 text NOT NULL CHECK (point_status IN ('AVAILABLE','PENDING','POSTED','REFUNDED','VOID')),
  tqp_eligible_flag            boolean NOT NULL DEFAULT false,
  transaction_time_utc         timestamptz NOT NULL,
  reversal_transaction_id      text REFERENCES fact_point_transaction(point_transaction_id),
  source_point_transaction_id  text REFERENCES fact_point_transaction(point_transaction_id),
  CHECK (transaction_type NOT IN ('RELEASE_PENDING','RELEASE_POST') OR point_type = 'PERKFLEX'),
  CHECK (transaction_type NOT IN ('FLIGHT_EARN_PENDING','FLIGHT_EARN_POST') OR point_type = 'RAPID_REWARDS'),
  CHECK (transaction_type NOT IN ('RELEASE_PENDING','FLIGHT_EARN_PENDING') OR point_status = 'PENDING'),
  CHECK (transaction_type NOT IN ('RELEASE_POST','FLIGHT_EARN_POST') OR (point_status = 'POSTED' AND source_point_transaction_id IS NOT NULL)),
  CHECK (transaction_type <> 'BENEFIT_DEBIT' OR points_delta <= 0),
  CHECK (tqp_eligible_flag = false OR point_type = 'RAPID_REWARDS')
);
-- A pending entry is settled by exactly one POST entry
CREATE UNIQUE INDEX uq_point_post_once ON fact_point_transaction (source_point_transaction_id, transaction_type)
  WHERE source_point_transaction_id IS NOT NULL;
CREATE INDEX ix_point_passenger ON fact_point_transaction (passenger_id, transaction_time_utc);
CREATE INDEX ix_point_booking ON fact_point_transaction (booking_id);

-- The ledger is append-only: history is never edited or deleted
CREATE OR REPLACE FUNCTION trg_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'fact_point_transaction is append-only (% not allowed)', TG_OP;
END $$;
CREATE TRIGGER ledger_no_update BEFORE UPDATE OR DELETE ON fact_point_transaction
  FOR EACH ROW EXECUTE FUNCTION trg_ledger_append_only();
CREATE TRIGGER ledger_no_truncate BEFORE TRUNCATE ON fact_point_transaction
  FOR EACH STATEMENT EXECUTE FUNCTION trg_ledger_append_only();

-- Id sequences for new rows (seed data uses T01.. and PT001..)
CREATE SEQUENCE pf_txn_seq START 100;
CREATE SEQUENCE pf_point_seq START 100;

-- ===================== DATABASE ROLES (run on RDS only, not in a throwaway test) =====================
-- CREATE ROLE app_writer LOGIN PASSWORD '...';   -- the rules engine
-- CREATE ROLE app_reader LOGIN PASSWORD '...';   -- the chat agent tools
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_writer;
-- REVOKE UPDATE, DELETE ON fact_point_transaction FROM app_writer;
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_writer;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_reader;
-- REVOKE SELECT (password_hash) ON dim_user_account FROM app_reader;
