"""How a traveller can earn points on this flight. Rules only: no model, no network, no database.

Used when someone asks the advisor to add points ("add me 15000 points") or how to get more. The advisor cannot add
points, so it answers with what the rules say is possible, and says plainly when a goal is out of reach.
Every number here comes from the offers the rules already computed for this traveller (status bonus included).
"""

from dataclasses import dataclass
from itertools import combinations
from math import ceil

from .offers import AdvisorContext
from .types import BIG_RELEASES, Offer

# Small-perk releases stop at 300 base points per flight (pf_release_perk enforces the same number). The offers carry
# points with the status bonus added, so the cap is applied to these base values. tests/test_advisor_earn.py keeps
# them in step with the seeded perk values.
PERK_CAP = 300
SMALL_BASE = {"RELEASE_BOARDING": 100, "RELEASE_DRINK": 150, "RELEASE_LANE": 50, "RELEASE_STANDBY": 75}
MAX_TARGET = 10_000_000  # a bigger number is treated as "no number given"


@dataclass(frozen=True)
class EarnPlan:
    big: Offer | None  # the one rewarded bag-or-seat release this flight allows
    small: tuple[Offer, ...]  # small-perk releases that fit under the cap together
    flight_total: int  # the most this traveller can earn on this flight (pending until they fly)
    target: int  # what they asked for (0 = no number)
    flights_needed: int | None  # best case: the same earnings again on each later flight; None if nothing is earnable


def plan(ctx: AdvisorContext, target: int = 0) -> EarnPlan:
    target = target if 0 < target <= MAX_TARGET else 0
    bigs = [o for o in ctx.offers if o.id in BIG_RELEASES and o.kind == "release"]
    big = max(bigs, key=lambda o: o.points, default=None)  # only one of the two can be taken per flight
    smalls = [o for o in ctx.offers if o.kind == "release" and o.id in SMALL_BASE]
    best: tuple[Offer, ...] = ()
    for r in range(len(smalls), 0, -1):
        for combo in combinations(smalls, r):
            if sum(SMALL_BASE[o.id] for o in combo) <= PERK_CAP and sum(o.points for o in combo) > sum(o.points for o in best):
                best = combo
    total = (big.points if big else 0) + sum(o.points for o in best)
    needed = ceil(target / total) if target and total > 0 else None
    return EarnPlan(big=big, small=tuple(sorted(best, key=lambda o: -o.points)), flight_total=total, target=target, flights_needed=needed)


def _n(v: int) -> str:
    return f"{v:,}"


def summary(ctx: AdvisorContext, p: EarnPlan) -> str:
    """The honest answer. Never promises more than one flight's limits allow."""
    text = "I can't add points to your account. Points come only from releasing benefits or flying, and they stay pending until you fly."
    if p.flight_total == 0:
        text += (
            " On this flight there is nothing left to release for points"
            + (" (your one rewarded release is already used)." if ctx.released else ".")
            + " Flying earns Rapid Rewards, which is a separate wallet, and group members can gift you PerkFlex points."
        )
        return text
    text += f" On this flight you can earn up to {_n(p.flight_total)} points by releasing what you may not use."
    text += " Only one bag-or-seat release is allowed per flight, and small perks stop at 300 base points."
    if p.target:
        if p.flight_total >= p.target:
            text += f" That covers the {_n(p.target)} you asked for."
        else:
            text += (
                f" Reaching {_n(p.target)} would take about {_n(p.flights_needed or 0)} flights like this one,"
                " and only if you can release the same on each."
            )
    text += f" You have {_n(ctx.balance)} points to spend"
    text += f" and {_n(ctx.pending)} pending." if ctx.pending else "."
    return text
