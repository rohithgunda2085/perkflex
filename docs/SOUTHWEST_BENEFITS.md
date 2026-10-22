# Southwest benefits catalog and PerkFlex mapping

Concept only. PerkFlex is fictional and not affiliated with Southwest Airlines. Facts below were read from southwest.com on 2026-10-22 and change often, so re-check before relying on them.

Sources:
- Fare types: https://www.southwest.com/airfare-types-benefits/
- Optional charges: https://www.southwest.com/html/customer-service/travel-fees.html
- Rapid Rewards 2027 tiers: https://www.southwest.com/rapid-rewards/2027/
- Credit cards: https://www.southwest.com/rapid-rewards/partners/credit-cards/consumer-cards/

## 1. Fare bundles

| Benefit | Basic | Choice | Choice Preferred | Choice Extra |
|---|---|---|---|---|
| Checked bags | paid | paid | paid | 2 free |
| Seat | standard, assigned at check-in | standard, chosen at booking | Preferred or standard | Extra Legroom or any |
| Boarding | last | general | group 3-4 | group 1 |
| Points per dollar (fare page) | 2x | 6x | 10x | 14x |
| Refundable | no | no | yes | yes |
| Same-day change / standby | n/a | free | free | free |
| Priority / Express lanes | no | no | yes | yes |
| Premium drink | no | no | no | 1 on flights of 251+ miles |

Note: the fare page (2x/6x/10x/14x) and the 2027 page (2x/6x/8x/10x) disagree. Treat earning rates as unconfirmed.

## 2. Optional charges (basis for point prices)

- Checked bag, mainland, booked on/after 2026-04-09: 1st $45, 2nd $55, 3rd+ $150. Before that date: $35 / $45 / $150.
- A-List: 2nd bag $35. A-List Preferred and Choice Extra: 2nd bag free.
- Overweight 51-70 lb +$100, 71-100 lb +$200. Oversize 63-80 in +$200.
- Paid seat upgrade $4-$250 per segment. Priority Boarding $10-$75 per segment.
- Wi-Fi $8 (free for Rapid Rewards members). Beer $7, wine $8, seltzer/cocktail/liquor $9.
- Pet in cabin $125 (mainland). Unaccompanied minor $100. Change and cancel fee $0.

## 3. Status benefits

Today: A-List, A-List Preferred, Companion Pass.
From 2027-01-01: Silver (was A-List), Gold (was A-List Preferred), Platinum (new).

| Tier (2027) | Qualify | Bags | Seat | Other |
|---|---|---|---|---|
| Silver | 35,000 TQP or 25 flights | 1 free | Preferred or standard free; Extra Legroom within 48h | +40% points, priority lanes, same-day standby |
| Gold | 65,000 TQP or 50 flights | 2 free | any seat incl. Extra Legroom | +60% points, 2 premium drinks, earlier boarding |
| Platinum | 140,000 TQP or 100 flights | 3 free | any seat | +120% points, unlimited Companion Pass trips |

Milestones: 20,000 TQP = 2,000 points or 2 Preferred Seat Certificates; 95,000 TQP = 3 Companion Pass trips.

## 4. Credit-card benefits

| Card | Fee | Anniversary points | Bags | Seat | Other |
|---|---|---|---|---|---|
| Plus | $99 | 3,000 | 1st free (+8 companions) | standard | 10% fare code, 25% back inflight |
| Premier | $149 | 6,000 | 1st free | Preferred or standard | 15% fare code, 1,500 TQP per $5k |
| Priority | $229 | 7,500 | 1st free | Preferred; unlimited Extra Legroom within 48h | 2,500 TQP per $5k |

All three: Group 5 boarding, no foreign transaction fee, 10,000-point Companion Pass boost per year.

## 5. Mapping to PerkFlex

Status: DONE = in the app, LATER = proposed for a next round, SKIP = not suitable.

| Benefit | PerkFlex use | Status | Points |
|---|---|---|---|
| Checked bag 1 / 2 | release and redeem | DONE | release 800; redeem 3,000 / 3,500 |
| Preferred seat | release and redeem | DONE | release 700; redeem 2,200 |
| Extra Legroom seat | release and redeem | DONE | release 1,500; redeem 4,500 |
| Bag / seat from fare, tier, card | included, never summed | DONE | 0 |
| Priority boarding | release if included; redeem if not | DONE | release 100; redeem 900 |
| Premium drink | release if included; redeem if not | DONE | release 150; redeem 600 |
| Priority lane | release if included; not for sale | DONE | release 50 |
| Third bag | redeem (bag 3) | DONE | 3,500 |
| Same-day standby | release if included; redeem if not | DONE | release 75; redeem 1,800 |
| Overweight allowance | redeem only | DONE | 6,500 |
| Airport meal voucher | redeem only (concept add-on). Southwest gives meal vouchers only after airline-caused delays of 3+ hours, on request; PerkFlex does not model that rule | DONE | 1,500 |
| Milestones, tier progress, Companion Pass | shown read-only on the Wallet page | DONE (display only) | |
| Wi-Fi | free for members, no value | SKIP | |
| Companion Pass, Milestones, anniversary points | outside check-in scope | SKIP | |
| Pet, minor, equipment fees | not a releasable perk | SKIP | |

Who already has a small perk (decided in PostgreSQL by `pf_perk_source`, from the fare and status):

| Perk | Included by fare | Included by status |
|---|---|---|
| Priority boarding | Choice Extra (Group 1) | Silver, Gold, Platinum |
| Premium drink | Choice Extra | Gold, Platinum |
| Priority lane | Choice Preferred, Choice Extra | Silver, Gold, Platinum |
| Same-day standby | Choice, Choice Preferred, Choice Extra | Silver, Gold, Platinum |

Point values keep the existing ratio: about 1 cent per point when buying, and a release pays roughly 10 to 25 percent of the buy price. The values are PerkFlex's own, not Southwest's.

## 6. The release rule (hybrid)

- The one rewarded release per flight (a bag or a seat) is unchanged.
- Small perks sit beside it and never use that slot.
- Each small perk can be released once per booking, and a booking can earn at most 300 points from small perks. With standby (75) the four release values add to 375, so the cap now binds and the last release that does not fit is refused.
- They draw on the same per-flight reward budget and stay pending until the trip is flown.
- A perk that was released cannot be bought back, and one that was bought cannot be released.

## 7. Where it lives

- Database: `backend/db/sql/22_small_perks.sql` (`pf_perk_source`, `pf_release_perk`, `pf_redeem_perk`, three new `dim_benefit` rows).
- API: `release` accepts `boarding`, `drink`, `lane`; `redeem` accepts `boarding`, `drink`. `GET /api/state` returns `booking.perks`.
- Advisor: eight small-perk offer ids; up to four picks, at most one bag-or-seat release.
- Screen: "Small perks" section on the check-in page.
