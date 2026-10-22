-- Email notifications (Amazon SES). Additive.
--   * A traveller can add an email address and turn notifications on. The address is not trusted until its owner opens
--     the link in a confirmation email (email_verified_flag), so nobody can aim PerkFlex mail at someone else.
--   * Mail is written to fact_email_outbox in the same transaction as the action that caused it, then sent by a worker.
--     A failed send never blocks a release or a purchase, and dedupe_key stops a retry sending the same mail twice.
BEGIN;

ALTER TABLE dim_user_account
  ADD COLUMN IF NOT EXISTS email               text,
  ADD COLUMN IF NOT EXISTS email_verified_flag boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS email_opt_in_flag   boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS email_token_hash    text;

ALTER TABLE dim_user_account DROP CONSTRAINT IF EXISTS ck_user_email_shape;
ALTER TABLE dim_user_account ADD CONSTRAINT ck_user_email_shape
  CHECK (email IS NULL OR (length(email) <= 254 AND email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'));

CREATE TABLE IF NOT EXISTS fact_email_outbox (
  email_id         bigserial PRIMARY KEY,
  passenger_id     text NOT NULL REFERENCES dim_passenger(passenger_id),
  kind             text NOT NULL CHECK (kind IN ('CONFIRM','BOOKED','RELEASE','PURCHASE','COMPLETE')),
  to_address       text NOT NULL,
  subject          text NOT NULL,
  body_text        text NOT NULL,
  dedupe_key       text UNIQUE,
  status           text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SENT','FAILED')),
  attempts         integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_error       text,
  created_time_utc timestamptz NOT NULL DEFAULT now(),
  next_attempt_utc timestamptz NOT NULL DEFAULT now(),
  sent_time_utc    timestamptz
);
CREATE INDEX IF NOT EXISTS ix_email_outbox_due ON fact_email_outbox (next_attempt_utc) WHERE status = 'PENDING';

COMMIT;
