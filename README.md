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
│   │   ├── assistant/        Bedrock agent, read-only tools, validation, fallback
│   │   └── routes/           auth, travel, assistant
│   ├── db/sql/               Numbered SQL migrations
│   ├── db/certs/             RDS CA bundle
│   ├── tests/                Python tests (pricing parity fixtures in tests/fixtures)
│   ├── scripts/              Frontend data generator, throwaway-schema helper
│   └── Dockerfile
├── frontend/                 React app (calls /api, no business rules)
└── amplify.yml               Optional static-hosting build file
```

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

Open http://localhost:5173/ and sign in. Usernames: `maya`, `ravi`, `neha`, `dev`, `arjun`, `leena`, `kabir`, `sara`, `alex`, `srija`, `mahesh`, `harshini`, `manish`, `rohith`, `sean.lynch`, `lu.truong`, `justin.bundick`, `michael.rankin`, `michael.hanna`, `deeann.carlin`, plus `airline`. Passwords are in `backend/db/demo-credentials.local.md`.

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

Nothing deploys automatically. Suggested layout:

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
