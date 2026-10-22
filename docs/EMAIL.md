# Email notifications (Amazon SES)

A traveller can add an email address in **Wallet > Email notifications**. PerkFlex then emails them when they book,
release a benefit, buy with points, or complete a trip. Off by default.

## How it works

1. **Add and confirm.** The address is saved unconfirmed and a confirmation email is queued. Nothing else is sent until
   the owner opens the link (`GET /api/email/confirm?token=...`). The token is random, stored only as a hash, and used once.
   This stops anyone aiming PerkFlex mail at someone else's address. Changing the address is limited to 5 times an hour.
2. **Queue.** When an action succeeds (`services/actions.py`, `perform`), a row is written to `fact_email_outbox` in the
   **same transaction**. A refused or rolled-back action sends nothing. Mail is queued only for a confirmed address with
   notifications on. A repeated request with the same idempotency key queues one email (`dedupe_key`).
3. **Send.** A small loop inside the API (`email/ses.py`) reads due rows with `FOR UPDATE SKIP LOCKED`, so several Fargate
   tasks can run it safely, and calls SES (`sesv2.send_email`) with a text and an HTML body.
4. **Retry.** A failure is retried after 1, 5, 15 and 60 minutes. After 5 attempts the row is marked `FAILED` and keeps the
   error text. A failed send never undoes the action.

The body of each email is the notice the app already showed the traveller. No model writes it.

## Turn it on

In the CloudFormation stack set **EmailFromAddress** (for example `no-reply@example.com`). The stack creates the SES
identity, gives the task role `ses:SendEmail` on that identity only, and sets `EMAIL_ENABLED`, `EMAIL_FROM` and
`PUBLIC_BASE_URL` (the confirmation link uses it). Locally, set the same three variables in `.env`.

Apply the migration: `npm run db:migrate` (`34_email.sql`).

## The SES sandbox

A new SES account is in the **sandbox**: it can send only to verified addresses and at a low rate. For a demo:

1. Open the verification email SES sends to `EmailFromAddress` and confirm it.
2. In the SES console, verify each recipient address you will demo with (your own, a colleague's).
3. For real traveller mail, ask AWS for production access, and set up SPF, DKIM and a bounce and complaint topic.

Until then, mail to an unverified recipient fails, is retried, and ends as `FAILED` in the outbox. Nothing else breaks.

## What it does not do yet

- No unsubscribe link in the email (the footer says how to turn it off in the wallet). A one-click link is the next step.
- No bounce or complaint handling. A configuration set with an SNS destination can feed that back.
- No emails for points sales or for points posting after the flight. Those need a fan-out and a scheduled job.

## Check it

`npm run test:py:offline` includes `tests/test_email.py` (templates, queue rules, retry timing, the SES call; no network).
The outbox is a plain table: `SELECT kind, to_address, status, attempts, last_error FROM fact_email_outbox ORDER BY email_id DESC;`
