"""Shared by the advisor tests, the saved evaluation cases and scripts/eval_advisor.py (no database, no network)."""

import json
from pathlib import Path
from typing import Any

from app.advisor.offers import AdvisorContext, build_context
from app.advisor.types import AdviceResponse

CASES_FILE = Path(__file__).parent / "fixtures" / "advisor_cases.json"


def state(
    *,
    balance=1200,
    pending=0,
    seat_class="extra",
    entitled="extra",
    bags=2,
    planned=0,
    redeemed_bags=0,
    released=False,
    released_seat=False,
    redeemed_seat=False,
    status="booked",
    clock=True,
    seat_pref="any",
    seats=(3, 3, 2),
    budget=20000,
    grants=16,
    booking=True,
    perks=None,
    early=False,
    perks_included=None,  # for saved cases (JSON): ids of small perks the traveller already has (even [] = none)
    perks_released=(),
    perks_bought=(),
    perks_no_room=(),  # ids whose release no longer fits under the 300-point small-perk cap
    prices=None,  # points prices on this flight (after any sale), as GET /api/state reports them
    rewards=None,  # what a release pays this traveller (policy and status bonus included)
):
    b = {
        "status": status,
        "clockAdvanced": clock,
        "seatClass": seat_class,
        "seat": "2A",
        "bags": bags,
        "actualBags": planned,
        "redeemedBags": redeemed_bags,
        "released": released,
        "releasedSeat": released_seat,
        "redeemedSeat": redeemed_seat,
        "needs": {"seat": seat_pref, "early": early},
        "perks": perks
        if perks is not None
        else (
            [
                perk(
                    i,
                    included=i in (perks_included or ()),
                    released=i in perks_released,
                    bought=i in perks_bought,
                    cap_room=i not in perks_no_room,
                )
                for i in ("boarding", "drink", "lane", "standby", "overweight")
            ]
            if perks_included is not None
            else []
        ),
        "checkinEntitlements": {"seat": entitled},
    }
    inv = {
        "seats": {c: [f"{c[0]}{i}" for i in range(n)] for c, n in zip(("standard", "preferred", "extra"), seats)},
        "budget": budget,
        "bagGrants": grants,
    }
    out = {"balance": balance, "pending": pending, "booking": b if booking else None, "inventory": inv}
    if prices is not None:
        out["prices"] = prices
    if rewards is not None:
        out["rewards"] = rewards
    return out


def perk(perk_id, *, included=False, released=False, bought=False, cap_room=True):
    """A small perk as GET /api/state reports it (values are the seeded ones)."""
    release, redeem = {
        "boarding": (100, 900), "drink": (150, 600), "lane": (50, 0), "standby": (75, 1800), "overweight": (0, 6500),
    }[perk_id]
    return {
        "id": perk_id,
        "name": {
            "boarding": "Priority boarding", "drink": "Premium drink", "lane": "Priority lane",
            "standby": "Same-day standby", "overweight": "Overweight bag allowance",
        }[perk_id],
        "included": included,
        "source": "fare" if included else "",
        "released": released,
        "bought": bought,
        "releasePoints": release,
        "redeemPoints": redeem,
        "capRoom": cap_room,
    }


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_FILE.read_text())


def context_for(case: dict[str, Any]) -> AdvisorContext:
    return build_context(state(**case.get("state", {})))


def problems(case: dict[str, Any], ctx: AdvisorContext, r: AdviceResponse, expect: dict[str, Any]) -> list[str]:
    """What is wrong with this response for this case (empty list = pass). Used for both the rules-only answer and live
    model answers, so the same expectations hold for both."""
    found: list[str] = []
    picks = [p.offer_id for p in r.picks]
    offers = {o.id: o for o in ctx.offers}
    if "picks" in expect and picks != expect["picks"]:
        found.append(f"picks {picks} != {expect['picks']}")
    for want in expect.get("includes", []):
        if want not in picks:
            found.append(f"missing {want}")
    if expect.get("includesOneOf") and not any(w in picks for w in expect["includesOneOf"]):
        found.append(f"none of {expect['includesOneOf']} in {picks}")
    for banned in expect.get("excludes", []):
        if banned in picks:
            found.append(f"must not pick {banned}")
    for offer_id, points in expect.get("offerPoints", {}).items():
        if offer_id not in offers or offers[offer_id].points != points:
            found.append(f"{offer_id} should be {points} points, got {offers[offer_id].points if offer_id in offers else 'no offer'}")
    # Always true, whatever the case:
    if any(p not in offers for p in picks):
        found.append("picked an offer that does not exist")
    if sum(1 for p in picks if p in ("RELEASE_BAG", "RELEASE_SEAT")) > 1:  # small perks sit beside it
        found.append("more than one bag-or-seat release")
    if any(p in offers and offers[p].kind == "redeem" and not offers[p].affordable for p in picks):
        found.append("picked something unaffordable")
    if len(picks) > 4:
        found.append("more than four picks")
    if not ctx.open and picks:
        found.append("picks while check-in is closed")
    return found
