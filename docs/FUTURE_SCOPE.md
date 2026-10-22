# Earning PerkFlex rewards by fare and status

> **Status:** All three are **built**. Part 1 (status bonus on flying points), option A (status multiplier on release rewards, migration 30), option B (value-based rewards, an airline setting that defaults to flat) and option C (completion bonus, default 50 points) are in migration 31 and the airline Settings panel. What remains open: confirm the rates with the airline, decide the reward budget size, and re-check the with/without estimate once real data exists. The small-perk cap of 300 points per booking counts base points, before the bonus.


Originally a proposal; now built (see the note above). PerkFlex is a fictional concept and is not affiliated with Southwest Airlines.

## Why

Rapid Rewards points for flying depend on what the traveller paid: a points-per-dollar rate by fare, plus a bonus for status. They post after the flight. Today PerkFlex rewards are different: each release pays a fixed number (bag 800, Preferred seat 700, Extra Legroom 1,500, small perks 50 to 150). Nothing depends on the fare or the traveller. The demo's Rapid Rewards flying points are also a flat number (for example 1,140) and not calculated.

This scope makes both earn rules follow the same idea: **the reward reflects the value of what the traveller gave up or paid for, and the rate is a setting the airline controls.**

## Part 1 (prerequisite): calculate Rapid Rewards flying points

- Store a points-per-dollar rate for each fare and a bonus percent for each status in a small table (for example `dim_earn_rate`).
- At booking, `points = base fare in dollars x fare rate x (1 + status bonus)`. The result is still pending until the flight is flown, and posts on Complete Trip as it does now.
- The Southwest fare page and the 2027 page disagree on the rates, so the rates must be settings and confirmed before anyone quotes them.
- Replace the flat seeded numbers; show the working on the booking review ("6x on $89 + 40% Silver bonus").

## Part 2: calculate PerkFlex rewards

Three options, from smallest to largest. They can be combined.

| Option | What it does | Example |
|---|---|---|
| A. Status multiplier | A release pays more for higher status, like the Rapid Rewards bonus. | Bag release 800 becomes 880 for Silver (+10%), 960 for Gold (+20%) |
| B. Value-based reward | A release pays a percent of the benefit's cash value, so the number follows the real price. | Bag $45 at 18% and 1 cent per point is about 800 points; if the bag price changes to $50, the reward follows |
| C. Completion bonus | A small bonus for completing a trip on which at least one benefit was released. Capped per trip and funded from the flight's reward budget. | +50 PerkFlex when the trip is flown |

Recommended order: A, then B. Leave C until the airline view shows how much budget is left in practice.

## How to build it

1. **Database (one new migration):**
   - `dim_perkflex_rate(tier, multiplier)` and, for option B, a `reward_percent` on `dim_benefit`.
   - A function `pf_release_reward(booking, benefit)` returns the points. All release functions call it in place of the fixed `perkflex_release_points`.
   - Ledger: record the base and the bonus as separate rows or fields so the audit trail shows where the number came from. Add a type such as `RELEASE_BONUS` if rows are kept separate.
   - Keep the rules that already exist: one rewarded bag-or-seat release per flight, the 300-point small-perk cap, the reward budget check, pending until flown, 12-month expiry and the undo limits. The cap and budget must apply to the **multiplied** amount.
2. **Backend:** `state.py` reports each offer's points from the function, not from a constant; `rules/data.py` stops holding a second copy of the numbers. The advisor builds its offers from state, so the validator keeps working: every amount it allows already comes from the offers.
3. **Frontend:** show the working next to the number ("800 + 10% Silver bonus = 880") on the confirmation dialog and the Wallet page. Update the next-flight preview and goals card, which use these amounts.
4. **Airline view:** the cost estimate must use the multiplied points. Add a setting for the multipliers and log every change (who, when, old and new value).
5. **Tests:** a table of fare and status combinations with the expected points; the cap and budget at the boundary; undo returns the multiplied amount; replaying a request does not double-count; the demo reset restores the rates.

## Risks and decisions to settle first

- **Budget:** higher rewards drain a flight's reward budget faster. Decide the budget size (10,000 or 20,000 points) first.
- **Fairness:** a status multiplier rewards people who already have benefits. Decide whether that is the intent.
- **Gaming:** release then undo or rebuy is already limited (3 undos per trip and the airline flag list). A multiplier raises the value of gaming, so keep those controls.
- **Liability:** points owed are a cost to the airline. The with/without model in the airline view must be re-checked.
- **Messaging:** PerkFlex points do not count toward status, and this scope does not change that.

## Open questions for the team

1. Which option (A, B, C) goes first?
2. Are the rates fixed by the airline, or may they change by flight or demand?
3. Do we confirm the real Rapid Rewards rates before quoting any?
4. Should the traveller see the working on every reward, or only in the Wallet?
