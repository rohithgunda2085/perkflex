# PerkFlex

**Find your fare. Flex your perks. Make the trip yours.**

A Southwest-inspired hackathon prototype: book a flight, review benefits at check-in, release or redeem bags and seats for points, and ask an AI assistant for the best fare. This is an independent concept, not affiliated with Southwest. Every price, point value and policy here is fictional.

## Architecture

```text
Browser (React + Vite, thin UI)
   │  cookie session (HttpOnly pf_session)
   ▼
FastAPI (backend/app)  ── pricing, booking, state view, auth, assistant
   │            │
   │            └── Amazon Bedrock (Converse + tool use) for "Find my best fare"
   ▼
Amazon RDS PostgreSQL ── pf_* SQL functions apply every state change atomically
```

- All rules, balances, inventory and actions live on the server. The browser keeps no session or state of its own; the signed cookie is the only session.
- State changes (redeem, release, check-in, complete trip, book) run in Postgres `pf_*` functions. They are row-locked and idempotent, and Python calls them.
- Money is handled in cents in Python. A parity suite proves the Python pricing matches the original TypeScript engine.
- The AI assistant never produces prices. The server re-prices every answer, rejects any dollar or points amount it did not compute, retries once, and then falls back to the rules-only result (`source: "fallback"`).

### Project map

```text
perkflex/
├── backend/
│   ├── app/                  FastAPI service
│   │   ├── main.py           App, /api/health
│   │   ├── config.py         Settings from environment (and optional perkflex/.env)
│   │   ├── db.py             Connection pool and transactions
│   │   ├── cli.py            check | inspect | migrate | seed-users
│   │   ├── rules/            Data tables and pricing
│   │   ├── security/         scrypt passwords, signed session cookie, login throttle
│   │   ├── services/         auth, context, state, booking, actions
│   │   ├── assistant/        Fare assistant: Bedrock agent, read-only tools, validation, fallback
│   │   ├── advisor/          Check-in perk advisor: offers (rules), tools, Bedrock loop, validator, fallback
│   │   └── routes/           auth, travel, assistant, advisor
│   ├── db/sql/               Numbered SQL migrations
│   ├── db/certs/             RDS CA bundle
│   ├── tests/                Python tests (pricing parity fixtures in tests/fixtures)
│   ├── scripts/              Frontend data generator, throwaway-schema helper
│   └── Dockerfile
├── frontend/                 React app (calls /api, no business rules)
└── amplify.yml               Optional static-hosting build file
```

## Demo reset

`npm run db:demo-reset -- --yes` puts the demo back to its starting state: it drops the demo schema, rebuilds it from the
migrations (fresh travellers, trips, wallets and ledger) and issues new demo passwords in
`backend/db/demo-credentials.local.md`. The points ledger is append-only, so a rebuild is the only honest reset.
It refuses to run without `--yes`, outside `DEMO_MODE`, or on the `public` schema unless you pass `--allow-public`.
Set `DB_SCHEMA` to a schema used only for the demo. Run it before each presentation.

### Two wallets

PerkFlex Rewards and Rapid Rewards are kept apart everywhere.

- **Trade** (release a benefit): the points go to the PerkFlex wallet, pending until the flight is flown. Rapid Rewards is not touched.
- **Flying**: the points for the flight go to the Rapid Rewards wallet when the trip is completed.
- **Buy** (bag, seat, small perk): PerkFlex points are used first, then Rapid Rewards. The notice, the confirmation and the
  ledger say how much came from each wallet. PerkFlex points that have posted stay in the wallet for the next flight.
- The spend order is the traveller's choice: PerkFlex first (default) or Rapid Rewards first (see Round 3 features below).
- `GET /api/state` returns `wallets` (`perkflex` and `rapidRewards`, each with `available` and `pending`), `ledger` (PerkFlex
  releases and purchases, with `wallet`, `paidPerkflex`, `paidRapid`) and `earnings` (Rapid Rewards for flying). `balance`
  is the spendable total.
- The airline view counts PerkFlex owed (the reward budget) and Rapid Rewards owed for flying separately, and splits
  points spent by wallet.

### Airline view, wallet value and presenter guide

- **Airline view.** Sign in with the airline account (no traveller view). `GET /api/admin/overview` (airline only; travellers get 403) returns,
  per flight with bookings: reward budget, points owed (pending), points paid, what is left, releases and purchases by bag, seat and small perk.
  The page shows the totals and a budget bar per flight. The estimated cost uses each flight's assumed cost per point.
- **Wallet: what your points did.** Each ledger entry carries `cashValue` (the benefit's usual add-on price). The wallet totals the extras bought with
  points and the unused benefits turned into points.
- **Presenter guide.** In demo mode a floating "Presenter guide" button walks through ten scenes (reset, release a bag, swap a seat, buy a bag, buy a seat,
  small perks both ways, the advisor, flying, the airline view). "Go to" uses the demo traveller switch; nothing is changed by the guide itself.

### Reset demo button

In demo mode the footer has a **Reset demo** button (it asks for a second click). It calls `POST /api/demo/reset`, which
runs `pf_demo_restore()` (`23_demo_restore.sql`): every traveller's trips, seats, wallets, rewards and ledger go back to a
snapshot taken when the migration first ran. Accounts and passwords are untouched and nobody is signed out. The endpoint
returns 404 when `DEMO_MODE` is off and allows 3 resets a minute. If the database was already played with before this
migration, run `SELECT pf_demo_snapshot(true);` on a clean demo (or `npm run db:demo-reset -- --yes`) to take a clean snapshot.

### Round 3 features (`24`, `25`, `26` migrations)

| Feature | What it does | Where it lives |
|---|---|---|
| Reuse visibility | A seat a traveller gives up is marked freed, then reused when another booking takes it. The traveller sees it; the airline view counts seats freed and reused. | `24_benefit_reuse.sql` (trigger on `fact_booking.seat_id`), `booking.reuse`, `ReuseCard` |
| Earned and used chart | Per-trip bars: PerkFlex earned, points used, Rapid Rewards for flying. Plain SVG with a hidden table for screen readers. | `EarningsChart` on the Wallet page |
| Next-flight preview | What the points held now cover on the next flight, following the spend order. | `NextFlightPreview` |
| Standby and overweight | Same-day standby (release 75 / buy 1,800) and the overweight allowance (buy 6,500; never released). A third bag already works through bag 3. Small-perk releases stop at 300 points per flight, so the page hides a release that no longer fits (`capRoom`). | `25_more_small_perks.sql` |
| 2027 status | Read-only card: qualifying points (sample data), next level, benefits, the 20,000 and 95,000 milestones and a Companion Pass note. PerkFlex rewards do not count toward status. | `dim_passenger.tqp_ytd`, `status` in state |
| Expiry | PerkFlex points expire 12 months after they post, oldest first. `pf_expire_points` runs on every state read and action and writes an `EXPIRY` ledger row. Manish starts with 1,500 points that expire in 12 days. | `26_...sql`, `wallets.perkflex.expiring` |
| Undo | A release can be undone for 1 real minute, while check-in is open. A seat can be undone only if nobody has taken it. It writes a `VOID` ledger row and restores the benefit; a second undo is a no-op. | `pf_undo_release`, `booking.undoable`, action `undo` |
| Spend order | Choose Rapid Rewards first or PerkFlex first. | `pf_set_pay_order`, `pf_pay`, action `payment-order`, `payRapidFirst` |
| Advisor reads the message | The rules-only answer reads typed preferences (backpack, tall, front seat, board early, heavy bag, standby, save points). It can only narrow the advice, never create an offer or change a number. | `advisor/intent.py` |

| Bag reuse note | After you release a bag, the page says how many other travellers added a bag on the flight. It does not claim your bag became theirs. | `booking.reuse.bag` |
| Points goals | "You are 800 points from same-day standby", with a progress bar and a note when pending points will cover it. | `GoalsCard` |
| Notifications | An in-app list worked out from your own data each time (points expiring within 14 days, a seat reused, bag space used, points posted). Nothing is stored. Email or push would need a sender such as SES or SNS, which is not built. | `notifications` in state |
| Fraud controls | Undos are capped at 3 per trip (database rule, `27_undo_limit.sql`). The airline view lists trips with 2 or more undos, or a bag or seat released and then bought back on the same trip. These are prompts for a person, with no names and no automatic penalty. | `flags` in the overview |
| Airport meal voucher | A buy-only small perk (1,500 points, never released). A PerkFlex concept add-on: Southwest itself only gives meal vouchers after airline-caused delays of 3+ hours. The advisor does not suggest it. | `33_meal_voucher.sql` |
| Asking for points | "Add me 15000 points" or "how do I earn points" is answered by the rules alone (`advisor/earn.py`), with no model call. The advisor says it cannot add points, shows the most this flight allows (one bag-or-seat release plus small perks under the 300-point cap, status bonus included), and, if the goal is bigger, about how many flights it would take (best case). | `tests/test_advisor_earn.py` |
| Email notifications | A traveller adds an address in the wallet, confirms it from a link, and gets emails for a booking, a release, a purchase and a completed trip. Mail is queued in the same transaction as the action (`fact_email_outbox`), sent through Amazon SES by a retrying worker, and off unless `EmailFromAddress` is set. See `docs/EMAIL.md`. | `34_email.sql`, `tests/test_email.py` |
| Fill in from your words | In the fare assistant the traveller writes about the trip in a prompt box and presses **Fill in for me**. `POST /api/assistant/understand` (`assistant/understand.py`) returns the form's settings (bags, seat, refundable, flexible, seat now, board earlier, budget), the page ticks them and marks what it set, and the traveller can change anything before **Find my best fare**. One forced Bedrock tool call, clamped by the server, with a rules-only reader when the model or guardrail is unavailable. It prices nothing and needs no new AWS resources. | `tests/test_understand.py` |
| Advisor cases | 26 saved cases, now including message-reading, standby, overweight and the 300-point cap. The cases run the message through the rules-only answer too. | `tests/fixtures/advisor_cases.json` |

| Story mode | The presenter guide can run scenes for you. "Run this scene" switches traveller and sends the scene's real actions through the API one at a time, scrolls to and highlights the result, and stops with the server's own words if a step is refused. "Play the whole story" resets the demo first and then runs every runnable scene. | `PresenterGuide.tsx` (`steps`, `timing.pause`) |
| Flight filling up | Demo only. "Other travellers" on the viewer's flight act: one takes the seat the viewer released, then others add bags with their own points (the real `pf_redeem_bag`). The seat move is a stand-in for a reassigned or standby traveller and does not model payment. `POST /api/demo/simulate` returns 404 outside demo mode and is limited to 20 a minute. | `28_demo_simulate.sql`, `pf_demo_simulate_other` |
| With and without PerkFlex | The airline view compares reward cost with the resale value of seats that other travellers took (valued at list add-on prices). The assumptions are printed under the table. Bags and small perks are not counted as revenue, so the estimate is cautious and can be negative on a small demo. | `model` in `/api/admin/overview` |

The undo window uses real time (`recorded_at`) because the demo clock is pinned. Run `npm run db:demo-reset` or press
Reset demo to restore the starting data, including the expiring points.

## Small perks

Priority boarding, a premium drink and priority lane sit beside the one rewarded bag-or-seat release. Travellers who
already have a perk (from their fare or status) can release it for pending points; those who lack boarding or a
drink can buy it with points. Small perks never use the one release, earn at most 300 points per flight, and are
settled in PostgreSQL (`22_small_perks.sql`). See `docs/SOUTHWEST_BENEFITS.md` for the values and who has what.

## Perk advisor (check-in agent)

At web check-in, "Ask the advisor" (a panel above the offers) tells the traveller which of their offers suit them, for
example "release your unused bag for 800 points" or "your benefits already cover Preferred". `POST /api/assistant/perk-advice`
returns `{ source, summary, picks, offers }`.

- **Advice only.** The agent has two read-only tools (`explain_rule`, `submit_advice`). It cannot release, buy or change anything;
  the traveller still presses the buttons, which run the existing `pf_*` functions.
- **The rules decide, the model chooses.** `app/advisor/offers.py` computes which offers exist and their points from the
  traveller's state (the same data as `GET /api/state`). The model picks at most two (at most one release) and explains.
- **Server-side checks** (`advisor.py`): unknown or unavailable offers, unaffordable purchases, two releases, any dollar amount, or any
  points amount that is not a balance, an offer amount or a shortfall are rejected. One retry, then a rules-only answer (`source: "fallback"`).
  With no offers, or check-in closed, no model call is made.
- **Ready for AgentCore.** `AdvisorContext` is plain data and the loop has no database access, so `run_advisor` can later run in an
  AgentCore Runtime container that receives the context as its payload. FastAPI would still validate the answer.
- **Proactive tip.** `GET /api/assistant/perk-nudge` returns one rules-written hint (no model call, no model rate limit) that the panel
  shows without being asked: a bag the traveller needs, then something their benefits already cover, then a release.
- Rate limit: 12 advice calls per minute per traveller.
- **Tests (no database or network):** `test_advisor.py` (offers, validator, fallback, fake Bedrock loop), `test_advisor_cases.py`
  (16 saved cases, `tests/fixtures/advisor_cases.json`, plus nudges), `test_advisor_route.py` (handlers). End to end against the
  throwaway schema: the advisor tests at the end of `test_api.py` (marked `db`). UI: the advisor tests at the end of `frontend/tests/ui.test.tsx`.
- **Evaluating the real model.** `npm run eval:advisor` runs the saved cases against Bedrock and prints source (ai or fallback), latency,
  picks and a pass/fail against each case's `live` expectations (`--repeat 3` shows how much answers vary, `--show` prints the wording).
  `pytest -m live tests/test_advisor_live.py` does the same as a test. Add a case to the JSON file whenever a live run shows something wrong.

## Run locally

Requirements: Node 24+, Python 3.12, a reachable Postgres (the project uses an RDS instance).

```bash
# 1. Configuration: copy .env.example to .env and fill in DB_*, SESSION_SECRET, Bedrock settings
# 2. Python environment (once)
python3.12 -m venv ../.venv
../.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
npm ci

# 3. Database
npm run db:check          # connectivity
npm run db:migrate        # apply SQL migrations
npm run db:seed-users     # writes passwords to backend/db/demo-credentials.local.md (git-ignored)

# 4. Run (two terminals)
npm run api           # FastAPI on 127.0.0.1:3001
npm run dev           # Vite on :5173, proxies /api to :3001 (override with API_PROXY)
```

Open http://localhost:5173/ and sign in. Usernames: `maya`, `ravi`, `neha`, `dev`, `arjun`, `leena`, `kabir`, `sara`, `alex`, `srija`, `mahesh`, `harshini`, `manish`, `rohith`, `sean.lynch`, `lu.truong`, `justin.bundick`, `michael.rankin`, `michael.hanna`, `deeann.carlin`, `nadia.brooks`, `owen.patel`, `priya.nair`, `marcus.reed`, `elena.cruz`, `tyrone.hayes`, `sofia.marin`, `daniel.kim`, plus `airline`. Passwords are in `backend/db/demo-credentials.local.md`.

With `DEMO_MODE=true` a signed-in user can switch to another demo traveller for presentations. Turn it off for anything real.

### Configuration

| Variable                                                  | Purpose                                                                                    |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL connection                                                                      |
| `DB_SSL`                                                  | `verify` (default), `no-verify`, `disable`                                                 |
| `SESSION_SECRET`                                          | Signs the login cookie                                                                     |
| `AWS_REGION`, `BEDROCK_MODEL_ID`                          | Bedrock model (default Claude Haiku 4.5 inference profile)                                 |
| `AWS_BEARER_TOKEN_BEDROCK`                                | Bedrock API key for development. Use the task IAM role in production                       |
| `DEMO_MODE`                                               | Allow the traveller switcher                                                               |
| `DEMO_NOW`                                                | Pins "now" for check-in windows (seed flights are in 2026/2027). Empty uses the real clock |
| `ENVIRONMENT`                                             | `production` marks the session cookie `Secure`                                             |

## Tests

```bash
npm test                                           # UI tests + offline Python tests (fast)
npm run test:py                                    # whole Python suite (db tests included, slow)
cd backend && ../../.venv/bin/python -m pytest -q -m db                      # database tests only, needs RDS
cd backend && ../../.venv/bin/python -m pytest -q -m live tests/test_assistant_live.py   # real Bedrock
npm run test:frontend                              # UI tests against a scripted fake API
npm run build                                      # typecheck + production build into frontend/dist
```

`db` tests create a throwaway `pf_test_*` schema and drop it afterwards, so the real tables are never modified. Each file takes a few minutes because every schema is built over the network.

`backend/scripts/e2e_schema.py create` prints a throwaway schema name for manual end-to-end runs. Pass it as `DB_SCHEMA`, and clean up with `e2e_schema.py drop <name>`.

If you change the rules tables in `backend/app/rules/data.py`, regenerate the display constants the UI uses:

```bash
cd backend && ../../.venv/bin/python scripts/generate_frontend_data.py
```

## Deploying to AWS

Nothing deploys automatically. `infra/perkflex-stack.yaml` builds a working version: ECS on Fargate (not Express Mode) behind an ALB, S3 + CloudFront, Secrets Manager and a Bedrock task role, reusing your RDS. It has no WAF, VPC endpoints or private-subnet layout; those are the hardened target in `docs/ARCHITECTURE.md`. Suggested layout:

- **API:** container on **Amazon ECS Express Mode** (Fargate behind a managed ALB with HTTPS). AWS App Runner stopped accepting new customers on 30 April 2026, so it is not an option for a new account.
- **Why not Lambda as the main host:** API Gateway caps a request at about 29-30 seconds, and the assistant can take 5-18 seconds, so there is little margin. A VPC Lambda talking to RDS also needs RDS Proxy and has cold starts, and the login throttle is in memory per container. Lambda is workable for a later split of the assistant endpoint, not the first choice.
- **Frontend:** `npm run build`, then serve `frontend/dist` from S3 + CloudFront (or Amplify via `amplify.yml`). Route `/api/*` on the same domain to the API so the cookie stays first-party.
- **Database:** keep RDS private. Put the service in the same VPC and allow 5432 from the service security group only.

Container image:

```bash
docker build -t perkflex-api backend
```

The image listens on port 8080, runs as a non-root user, and reads all settings from environment variables. No `.env` is baked in. The Dockerfile has not been built on the development machine (no Docker there), so run the build once in CI or on a machine with Docker before relying on it.

Production settings:

- `ENVIRONMENT=production`, `DEMO_MODE=false`, `DEMO_NOW` empty.
- `DB_PASSWORD` and `SESSION_SECRET` from AWS Secrets Manager.
- Bedrock through the task IAM role (`bedrock:InvokeModel` on the chosen inference profile). Do not set `AWS_BEARER_TOKEN_BEDROCK`.
- Health check path: `/api/health` (it also checks the database).
- Run migrations once per release (`python -m app.cli migrate`) from a one-off task, not on every container start.
- A single in-memory login throttle is per container. If you run several tasks, move it to a shared store before relying on it.

## Behaviour differences from the original browser-only demo

- Completing a trip also posts the Rapid Rewards earn. Rohith goes from 12,450 to 15,950 points (12,450 + 800 release + 2,700 flight earn).
- Every route between the five demo airports (Dallas Love Field, Denver, Las Vegas, Phoenix, Nashville) can be booked. Each route has the same three departures (WN 2418, 968, 1820) on 16 Dec 2027, each with its own 96 seats and reward budget, added by `backend/db/sql/21_more_routes.sql`. Quotes and the assistant now take the route as well as the flight number.
- The booking date snaps to the nearest scheduled flight date.
- "Start over" is gone, because state is now real database state.
- Switching traveller (demo mode) remounts the screen, so the welcome overlay shows again.
- Greetings use full names for every traveller.
- Business-rule refusals (not enough points, seat taken, and so on) return HTTP 200 with the current state and `error: true`. Auth and validation problems use real 4xx codes.

## Scenarios

| Traveller           | Starting context                            | What to show                                       |
| ------------------- | ------------------------------------------- | -------------------------------------------------- |
| Maya                | Member, Choice Extra, 1,200 pts             | Release an unused bag for 800 pending points       |
| Ravi                | Member, Basic, 6,000 pts                    | Redeem 3,000 pts for a bag                         |
| Neha                | Member, Choice Preferred, 800 pts           | Swap Preferred for Standard, earn 700 pending      |
| Dev                 | Member, Choice, 6,000 pts                   | 2,200 pts for a Preferred seat                     |
| Arjun               | Silver, Choice Extra, 3,000 pts             | Extra Legroom not sold as a guarantee at booking   |
| Leena               | Gold, Choice Preferred, 10,000 pts          | Gold already covers premium seat and two bags      |
| Kabir               | Platinum, Choice, 20,000 pts                | Release an unused bag; allowances do not stack     |
| Sara                | Plus card, Basic, 2,000 pts                 | First bag already covered                          |
| Alex                | New member, Basic, 0 pts                    | Redemptions disabled when unaffordable             |
| Srija Panchagnula   | Gold + Premier card, Choice, 4,000 pts      | Benefits do not stack                              |
| Mahesh Ammanaganti  | Silver, Choice Preferred, 15,000 pts        | Extra Legroom free at check-in                     |
| Harshini Bhavisetty | Platinum + Priority card, Choice, 9,000 pts | Release an unused allowance                        |
| Manish Galigini     | Member, Choice, 25,000 pts                  | Redeem 4,500 pts for Extra Legroom                 |
| Rohith Gunda        | Silver, Choice Extra, 12,450 pts            | Trip 22 Oct 2026, release a bag, complete the trip |
| Sean Lynch          | Platinum, Choice, 30,000 pts                | Release an unused bag allowance                    |
| Lu Truong           | Gold, Choice Preferred, 18,000 pts          | No duplicate charges                               |
| Justin Bundick      | Gold, Basic, 7,000 pts                      | Gold lifts Basic to two bags and Extra Legroom     |
| Michael Rankin      | New traveller, no trip, 0 pts               | Lands on Book a flight after login                 |
| Michael Hanna       | Silver, Choice, 8,000 pts                   | Add a second bag with points                       |
| Dee Ann Carlin      | Silver, Basic, 2,500 pts                    | Silver gives Basic a bag and a front seat          |
| Nadia Brooks        | New traveller, Basic, 1,500 pts             | Nothing included: every benefit is a purchase      |
| Owen Patel          | Silver, Choice, 6,000 pts                   | Preferred seat now, Extra Legroom at check-in      |
| Priya Nair          | Gold, Choice Preferred, 14,000 pts          | Two bags and Extra Legroom covered, one planned    |
| Marcus Reed         | Platinum, Choice Extra, 40,000 pts          | Three bags covered, two planned: release the third |
| Elena Cruz          | Plus card, Basic, 3,200 pts                 | The card covers the first bag                      |
| Tyrone Hayes        | Premier card, Choice Preferred, 9,500 pts   | Card bag, fare Preferred seat                      |
| Sofia Marin         | Priority card, Choice, 22,000 pts           | Preferred seat now, Extra Legroom at check-in      |
| Daniel Kim          | Silver + Priority card, Choice, 11,000 pts  | Tier and card together: the best of each, no stack |

## Rules summary

Bag allowances from fare, tier and card use the maximum applicable allowance, not their sum. Premium fares are recommended only when their benefits justify the cost.

| Benefit                                            | Receiver cost | Giver's pending reward |
| -------------------------------------------------- | ------------: | ---------------------: |
| First bag grant / unused included bag release      |     3,000 pts |                800 pts |
| Additional bag grant / unused included bag release |     3,500 pts |                800 pts |
| Preferred seat                                     |     2,200 pts |                700 pts |
| Extra Legroom seat                                 |     4,500 pts |              1,500 pts |

- At most one rewarded release per traveller per flight.
- A redeemed benefit cannot be released again.
- Seat swaps reserve an available Standard replacement before releasing the old seat.
- Insufficient points, unavailable seats or an exhausted reward budget leave inventory, wallet and booking unchanged.
- Pending points cannot be spent. They post once after check-in and flight completion.
- Benefit changes close when check-in is completed. Refundability and change conditions stay with the purchased fare.

## Security notes

- Passwords are stored as scrypt hashes. The session cookie is HttpOnly, SameSite=Lax and signed.
- Credentials that were pasted into chat during development (the database password and the Bedrock API key) should be rotated. The Bedrock long-term key expires on 26 October 2026.
- The login throttle is in memory. Use a shared store and a real identity provider before exposing real customer data.
- No secrets belong in the frontend code or in the container image.

## Known limits

One adult and one active trip per traveller, synthetic domestic nonstop flights, no payments, cancellations, waitlists or live demand pricing. PerkFlex awards are not Tier Qualifying Points. Do not present the exchanges as existing Southwest policy.


## Round 6

| Feature | What it does | Where |
|---|---|---|
| Status bonus | Flying points: Silver +40%, Gold +60%, Platinum +120%. Release rewards: Silver +10%, Gold +20%, Platinum +30%. | migration 30, `app/rules/data.py` |
| Value-based rewards (option B) | The airline can switch bag and seat releases from flat numbers to a percent of the benefit's cash price (default 18% at 1 cent per point). Small perks stay flat. The default stays flat, so nothing changes until the airline switches it. | migration 31 `dim_reward_policy`, airline page "Settings" |
| Completion bonus (option C) | 50 PerkFlex points when a trip with a posted release is completed, once per trip, paid from the flight's reward budget. Zero switches it off. | `pf_complete_booking` |
| Status nudge | The status card says what the next level would pay on the traveller's next trip. | `services/extras.py`, `StatusNudgeLine` |
| Travel groups | Invite a companion (sign-in name or Rapid Rewards number); they must accept; up to 6 travellers; one group each. Members see each other's trip and whether a benefit was released. | `pf_group_*`, `GroupCard` |
| Point gifts | Give PerkFlex points inside a group: 100 to 2,000 per gift, 3,000 given and 3,000 received per 24 hours, available points only, and points you were just given cannot be passed on for 24 hours. Gifts count as lots for the 12-month expiry. | `pf_gift_points` |
| Points sales | The airline puts a benefit on sale (5 to 50% off in points) on one flight; the redeem functions charge the sale price. Travellers on that flight see the old and new price in an "On sale for your flight" card and in Notifications. Nothing to set up. | `fact_price_sale`, `pf_redeem_price`, `SalesCard` |
| Flight award | 25 PerkFlex points on every completed flight, released or not, once per trip, not taken from the flight's reward budget (`dim_reward_policy.flight_award`, migration 36). Rapid Rewards stay the main earning. | `pf_complete_booking` |
| Seasons and festivals | The flight award is multiplied (1 to 3) for flights in airline-set date windows: off-peak seasons and US holiday windows (Memorial Day, Independence Day, Labor Day, Thanksgiving, Christmas and New Year, the days around each). The higher rule applies, never both. Shown as a badge on fare results and as a note in the points history. Managed on the airline Settings panel with a change log (migration 37). | `pf_season_award`, `services/seasons.py`, `AdminControls.tsx` |
| Advertising the boost | A promo strip on Book a flight (soonest active or upcoming boost), a badge and a "better nearby date" hint on fare results (only real scheduled flights are suggested), a line in the fare assistant and the check-in advisor (written by rules, not the model), and an open-bookings count per rule on the airline Settings panel. | `promos_view`, `nearby_better` |
| Airline settings | Reward mode, value percent, cents per point, completion bonus and sales, with a change log (who, when, old and new). | `services/controls.py`, `AdminControls.tsx` |
| Advisor evaluation | `scripts/eval_advisor.py` now saves a report, compares it with an earlier one, can fail a build when the model's own answers fall below a rate, and has an `--offline` mode that needs no model. Three new cases cover sale prices and value-based rewards. | `backend/scripts/eval_advisor.py` |

Three new presenter scenes: completion bonus (Sean), points sale (Dev) and travel group with a gift (Manish and Kabir).

### Things to know

- Numbers shown to the traveller come from the database (`pf_release_points`, `pf_redeem_price`), so the screen, the advisor and the database always agree. The advisor reads sale prices and release rewards from the state.
- `app/assistant/best_fare.py` (the booking-time assistant) still checks numbers against the flat reward values. In value mode its explanations may fall back to the plain text answer.
- Gifts are limited to a group so points cannot flow to strangers. The 24-hour rule uses real time, not the pinned demo clock; the demo reset clears gifts, groups, sales and puts the policy back to flat.
- The reward policy, sale discounts and gift limits are concept settings. Confirm them before any real use.

### Running the advisor evaluation

```
cd backend
../../.venv/bin/python scripts/eval_advisor.py --offline                      # no model, no cost
../../.venv/bin/python scripts/eval_advisor.py --repeat 3 --report evals/run.json
../../.venv/bin/python scripts/eval_advisor.py --report evals/new.json --compare evals/run.json --min-ai-rate 0.8
```

## Advisor safety and hosting (optional AWS layers)

- **Bedrock Guardrails**: a second layer beside the validator. Set `BEDROCK_GUARDRAIL_ID` (the stack creates one when `EnableGuardrail=true`). Blocked text or replies fall back to the rules-only advice.
- **Bedrock AgentCore Runtime**: `ADVISOR_RUNTIME=agentcore` plus `AGENTCORE_RUNTIME_ARN` runs the advisor loop in AgentCore. Default is `local`. The API validates the answer either way.

Details, steps and caveats: [docs/AGENTCORE.md](docs/AGENTCORE.md). Tests: `backend/tests/test_guardrails_runtime.py` (fake clients, no AWS needed).

## Benefits inventory pool (airline page)

The airline page lists a pool card for every flight: reward budget left, bag grants left, and free seats by class
(with how many were given back by travellers and how many of those another traveller has taken). The numbers come
from `fact_flight_campaign` and `dim_seat` (`POOL_SQL` and `BAGS_SQL` in `backend/app/services/admin.py`). Releasing a
seat frees it in `dim_seat`; buying one takes it out. Each card also lists every benefit released and bought on that flight (`BENEFITS_SQL`). Nothing new is stored, so there is no migration.

## Routes (round 7)

The frontend has real addresses, so a page can be linked to, refreshed, and left with the Back button.

| Address | Page |
|---|---|
| `/` | Redirects to `/checkin` (traveller with a trip) or `/book` (no trip) |
| `/book`, `/checkin`, `/trips`, `/wallet` | The four traveller pages |
| `/admin` | The airline view and settings (the airline account lands here after sign-in; a traveller who opens it is sent to their own page) |
| anything else | "Page not found" |

Signed-out visitors see the sign-in page at any address and land on the page they asked for after signing in. No router library is used: `App.tsx` keeps the address and the page in step with `history.pushState` and a `popstate` listener (`pageFromPath`). CloudFront rewrites extension-less paths to `index.html` (the stack's `SpaRewriteFunction`), and the Vite dev server does the same.

Signing out clears the address, and who is signed in decides whether the address may be `/admin`: a traveller is never left on it.

Price watch was removed (migration `32_drop_price_watch.sql`): sales are shown to everyone on the flight instead of needing a switch.
