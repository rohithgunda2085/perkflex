"""What a traveller can do at check-in, computed from their state. No model, no database, no network.

The state is the same dictionary GET /api/state returns, so the offers always agree with the check-in screen. The
`pf_*` database functions remain the final authority when an action is taken: these offers only say what to show.
"""

from dataclasses import dataclass, fields
from typing import Any

from ..rules.data import REDEEM_POINTS, RELEASE_POINTS, SEAT_NAMES, seat_rank


def _release_table(state: dict[str, Any]) -> dict[str, int]:
    """What a release pays this traveller (status bonus included). Older callers without `rewards` get the base values."""
    r = state.get("rewards") or {}
    return {k: int(r.get(k, v)) for k, v in RELEASE_POINTS.items()}
from .types import SMALL_PERK_OFFERS, Offer


@dataclass(frozen=True)
class AdvisorContext:
    """Everything the advisor (and any agent hosting it) may read. Plain data, so it can cross a process boundary."""

    open: bool  # a trip exists, check-in is open and benefit changes are still allowed
    reason_closed: str
    balance: int
    pending: int
    perkflex: int  # PerkFlex rewards available (spent first)
    rapid_rewards: int  # Rapid Rewards available (spent after PerkFlex)
    seat_class: str
    seat: str
    bags: int  # allowance
    planned_bags: int  # what the traveller expects to check
    seat_preference: str  # any | front | extra
    wants_early_boarding: bool  # the traveller said earlier boarding matters to them
    released: bool  # the one rewarded release for this flight is already used
    offers: tuple[Offer, ...]

    def offer(self, offer_id: str) -> Offer | None:
        return next((o for o in self.offers if o.id == offer_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "open": self.open,
            "balance": self.balance,
            "pending": self.pending,
            "perkflexPoints": self.perkflex,
            "rapidRewardsPoints": self.rapid_rewards,
            "paymentOrder": "PerkFlex first, then Rapid Rewards",
            "seatClass": SEAT_NAMES.get(self.seat_class, self.seat_class),  # type: ignore[call-overload]
            "seat": self.seat,
            "bagAllowance": self.bags,
            "plannedBags": self.planned_bags,
            "seatPreference": self.seat_preference,
            "wantsEarlyBoarding": self.wants_early_boarding,
            "rewardedReleaseAlreadyUsed": self.released,
            "offers": [o.model_dump(by_alias=True) for o in self.offers],
        }


def _price(state: dict[str, Any], key: str) -> int:
    """The points price on this flight (after any sale). Older callers without `prices` get the list price."""
    return int((state.get("prices") or {}).get(key, REDEEM_POINTS[key]))


def _wallets(state: dict[str, Any]) -> tuple[int, int]:
    """(PerkFlex, Rapid Rewards) available. Older callers without `wallets` count everything as Rapid Rewards."""
    w = state.get("wallets")
    if not w:
        return 0, int(state.get("balance", 0))
    return int(w["perkflex"]["available"]), int(w["rapidRewards"]["available"])


def _closed(reason: str, state: dict[str, Any]) -> AdvisorContext:
    b = state.get("booking") or {}
    return AdvisorContext(
        open=False,
        reason_closed=reason,
        balance=int(state.get("balance", 0)),
        pending=int(state.get("pending", 0)),
        perkflex=_wallets(state)[0],
        rapid_rewards=_wallets(state)[1],
        seat_class=str(b.get("seatClass", "standard")),
        seat=str(b.get("seat", "")),
        bags=int(b.get("bags", 0)),
        planned_bags=int(b.get("actualBags", 0)),
        seat_preference=str((b.get("needs") or {}).get("seat", "any")),
        wants_early_boarding=bool((b.get("needs") or {}).get("early", False)),
        released=bool(b.get("released", False)),
        offers=(),
    )


def build_context(state: dict[str, Any]) -> AdvisorContext:
    """Turns the traveller's state into the advisor's context, with the offers that are available right now."""
    b = state.get("booking")
    if not b:
        return _closed("You have no trip to check in for.", state)
    if b["status"] != "booked":
        return _closed("Check-in is complete, so benefit changes are closed.", state)
    if not b.get("clockAdvanced"):
        return _closed("Check-in has not opened yet. PerkFlex offers appear once it does.", state)

    inv = state.get("inventory") or {"seats": {"standard": [], "preferred": [], "extra": []}, "budget": 0, "bagGrants": 0}
    seats = inv["seats"]
    balance = int(state["balance"])
    held: str = b["seatClass"]
    entitled: str = b["checkinEntitlements"]["seat"]
    offers: list[Offer] = []
    pay = _release_table(state)

    # Release an unused bag: only a bag the traveller does not plan to check, and while the budget lasts.
    if (
        b["bags"] > b["actualBags"]
        and b["bags"] - b["redeemedBags"] > 0
        and not b["released"]
        and inv["budget"] >= pay["bag"]
    ):
        offers.append(Offer(id="RELEASE_BAG", kind="release", label="Release an unused bag", points=pay["bag"]))

    # Release an upgraded seat for a Standard one (the swap is atomic with the replacement).
    if (
        held != "standard"
        and not b["redeemedSeat"]
        and not b["released"]
        and seats["standard"]
        and inv["budget"] >= pay[held]  # type: ignore[index]
    ):
        offers.append(
            Offer(
                id="RELEASE_SEAT",
                kind="release",
                label=f"Swap {SEAT_NAMES[held]} for a Standard seat",  # type: ignore[index]
                points=pay[held],  # type: ignore[index]
            )
        )

    # Add a bag with points.
    if b["bags"] < 3 and inv["bagGrants"] > 0:
        cost = _price(state, "bag1" if b["bags"] == 0 else "bag2")
        offers.append(
            Offer(
                id="REDEEM_BAG",
                kind="redeem",
                label="Add a checked bag",
                points=cost,
                affordable=balance >= cost,
                shortfall=max(0, cost - balance),
                needed=b["actualBags"] > b["bags"],
            )
        )

    # Upgrade a seat.
    for seat in ("preferred", "extra"):
        if seat_rank(seat) > seat_rank(held) and not b["releasedSeat"] and seats[seat]:  # type: ignore[arg-type]
            cost = _price(state, seat)
            free = seat_rank(entitled) >= seat_rank(seat)  # type: ignore[arg-type]
            offers.append(
                Offer(
                    id="REDEEM_PREFERRED" if seat == "preferred" else "REDEEM_EXTRA",
                    kind="redeem",
                    label=f"{SEAT_NAMES[seat]} seat",  # type: ignore[index]
                    points=0 if free else cost,
                    included=free,
                    affordable=free or balance >= cost,
                    shortfall=0 if free else max(0, cost - balance),
                )
            )

    # Small perks (priority boarding, premium drink, priority lane). The page's state says which the traveller has.
    # They never use the one rewarded release, but they do draw on the same flight budget.
    for perk in b.get("perks") or []:
        name = SMALL_PERK_OFFERS.get(perk["id"])
        if name is None:
            continue
        label = str(perk["name"]).lower()
        room = perk.get("capRoom", True)  # the 300-point small-perk cap has room for this release
        if perk["included"] and not perk["released"] and room and inv["budget"] >= perk["releasePoints"] > 0:
            offers.append(
                Offer(id=f"RELEASE_{name}", kind="release", label=f"Release {label}", points=perk["releasePoints"])  # type: ignore[arg-type]
            )
        elif not perk["included"] and not perk["bought"] and perk["redeemPoints"] > 0:
            cost = perk["redeemPoints"]
            offers.append(
                Offer(
                    id=f"REDEEM_{name}",  # type: ignore[arg-type]
                    kind="redeem",
                    label=f"Add {label}",
                    points=cost,
                    affordable=balance >= cost,
                    shortfall=max(0, cost - balance),
                )
            )

    return AdvisorContext(
        open=True,
        reason_closed="",
        balance=balance,
        pending=int(state.get("pending", 0)),
        perkflex=_wallets(state)[0],
        rapid_rewards=_wallets(state)[1],
        seat_class=held,
        seat=str(b["seat"]),
        bags=int(b["bags"]),
        planned_bags=int(b["actualBags"]),
        seat_preference=str((b.get("needs") or {}).get("seat", "any")),
        wants_early_boarding=bool((b.get("needs") or {}).get("early", False)),
        released=bool(b["released"]),
        offers=tuple(offers),
    )


def ctx_to_wire(ctx: AdvisorContext) -> dict[str, Any]:
    """The context as plain JSON, to send to a separate runtime (for example Amazon Bedrock AgentCore Runtime)."""
    out = {f.name: getattr(ctx, f.name) for f in fields(ctx) if f.name != "offers"}
    out["offers"] = [o.model_dump(by_alias=True) for o in ctx.offers]
    return out


def ctx_from_wire(data: dict[str, Any]) -> AdvisorContext:
    """The reverse of ctx_to_wire. Raises (ValueError or a pydantic error) on anything malformed."""
    names = {f.name for f in fields(AdvisorContext)}
    unknown = set(data) - names
    if unknown:
        raise ValueError(f"unexpected context fields: {sorted(unknown)}")
    return AdvisorContext(**{**{k: v for k, v in data.items() if k != "offers"}, "offers": tuple(Offer.model_validate(o) for o in data.get("offers", []))})
