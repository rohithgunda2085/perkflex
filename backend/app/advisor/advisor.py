"""The check-in perk advisor.

The rules decide which offers exist and what they cost or pay (offers.py). The model only chooses among them and
explains. This module rejects any model answer that invents an offer, suggests something unaffordable, or states a
number the rules did not produce, and falls back to a rules-only answer whenever the model is unavailable or wrong.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from . import earn
from .agent import Advisor, AdvisorInput
from .guardrails import GuardrailBlocked, screen_message
from .intent import Intent, parse_intent
from .offers import AdvisorContext
from .runtime import default_agent
from .types import BIG_RELEASES, MAX_PICKS, AdviceRequest, AdviceResponse, Nudge, Offer, Pick

log = logging.getLogger("perkflex.advisor")


class AdviceRejected(ValueError):
    """The model's answer contradicts the offers."""


def clean(value: Any, limit: int) -> str:
    """Strips control characters, collapses whitespace and caps the length."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]+", " ", value)).strip()[:limit]


# Dollar amounts are never allowed: the advisor deals in points only.
_DOLLARS = re.compile(r"\$\s?\d|\d\s*(?:dollars?|usd|bucks)\b|\busd\s?\d", re.IGNORECASE)
_POINTS = re.compile(r"(\d[\d,]*)\s*(?:points|pts)\b", re.IGNORECASE)


def allowed_points(ctx: AdvisorContext) -> set[int]:
    """Every points amount the advisor may mention: balances, offer amounts, shortfalls and what is left after a buy."""
    values = {ctx.balance, ctx.pending, ctx.perkflex, ctx.rapid_rewards}
    for o in ctx.offers:
        values.add(o.points)
        values.add(o.shortfall)
        if o.kind == "redeem" and o.affordable and not o.included:
            values.add(ctx.balance - o.points)
    values.add(earn.plan(ctx).flight_total)  # the most this flight can pay, worked out by the rules (see earn.py)
    return values


def assert_text_verified(text: str, ctx: AdvisorContext) -> None:
    if _DOLLARS.search(text):
        raise AdviceRejected("dollar amounts are not allowed")
    allowed = allowed_points(ctx)
    for m in _POINTS.finditer(text):
        if int(m.group(1).replace(",", "")) not in allowed:
            raise AdviceRejected(f"unverified points {m.group(0)}")


def validate_submission(sub: dict[str, Any], ctx: AdvisorContext) -> AdviceResponse:
    """Turns the model's submission into a response, or raises AdviceRejected."""
    if not ctx.open:
        raise AdviceRejected("check-in offers are not open")
    summary = clean(sub.get("summary"), 400)
    if not summary:
        raise AdviceRejected("empty summary")
    assert_text_verified(summary, ctx)

    raw = sub.get("picks")
    picks: list[Pick] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            raise AdviceRejected("malformed pick")
        offer = ctx.offer(str(item.get("offerId")))
        if offer is None:
            raise AdviceRejected(f"offer {item.get('offerId')!r} is not available")
        if offer.id in seen:
            raise AdviceRejected("duplicate pick")
        if offer.kind == "redeem" and not offer.affordable:
            raise AdviceRejected(f"{offer.id} is not affordable")
        why = clean(item.get("why"), 200)
        if not why:
            raise AdviceRejected("empty reason")
        assert_text_verified(why, ctx)
        seen.add(offer.id)
        picks.append(Pick(offer_id=offer.id, why=why))
    if len(picks) > MAX_PICKS:
        raise AdviceRejected("too many picks")
    # Small perks sit beside the one rewarded release (a bag or a seat) and do not count against it.
    if sum(1 for p in picks if p.offer_id in BIG_RELEASES) > 1:
        raise AdviceRejected("only one rewarded release is allowed per flight")
    return AdviceResponse(source="ai", summary=summary, picks=picks, offers=list(ctx.offers))


def _n(value: int) -> str:
    return f"{value:,}"


def earn_advice(ctx: AdvisorContext, target: int = 0) -> AdviceResponse:
    """The answer to "add me 15000 points" or "how do I earn points": what this flight allows, said honestly.

    Built from the rules alone. The model is not asked, so it cannot promise points the rules do not allow.
    """
    p = earn.plan(ctx, target)
    chosen = ([p.big] if p.big else []) + list(p.small)
    picks = [
        Pick(offer_id=o.id, why=f"Earn {_n(o.points)} points, pending until you fly.")
        for o in sorted(chosen, key=lambda o: -o.points)[:MAX_PICKS]
    ]
    return AdviceResponse(source="fallback", summary=earn.summary(ctx, p), picks=picks, offers=list(ctx.offers))


def deterministic_advice(ctx: AdvisorContext, message: str = "") -> AdviceResponse:
    """The rules-only advice, used whenever the model is unavailable or fails validation.

    `message` is what the traveller typed. It is read for plain preferences (intent.py) that can only narrow the
    advice: drop a release they do not want, or put an existing offer first.
    """
    intent = parse_intent(message)
    if not ctx.open:
        return AdviceResponse(source="fallback", summary=ctx.reason_closed, picks=[], offers=[])
    if intent.wants_points:
        return earn_advice(ctx, intent.points_target)
    if not ctx.offers:
        return AdviceResponse(
            source="fallback",
            summary="There is nothing to release or add right now. Your benefits already fit this trip.",
            picks=[],
            offers=[],
        )

    picks: list[Pick] = []

    # One rewarded release at most: an unused bag first; a premium seat only if the traveller does not need it.
    bag = None if intent.keep_bag else ctx.offer("RELEASE_BAG")
    seat = None if (intent.keep_seat or intent.wants_front_seat) else ctx.offer("RELEASE_SEAT")
    release: Offer | None = None
    if bag and seat and intent.prefers_bag_release:
        release = bag
    elif bag and seat and ctx.seat_preference == "any":
        release = max(bag, seat, key=lambda o: o.points)
    elif bag:
        release = bag
    elif seat and ctx.seat_preference == "any":
        release = seat
    if release:
        why = (
            f"Earn {_n(release.points)} points, pending until you fly."
            if release.id == "RELEASE_BAG"
            else f"Move to a Standard seat and earn {_n(release.points)} points, pending until you fly."
        )
        if bag and seat and ctx.seat_preference == "any":
            why += " Only one rewarded release is allowed per flight."
        picks.append(Pick(offer_id=release.id, why=why))

    # One redeem at most: a bag they need, otherwise the seat they want.
    redeem: Pick | None = None
    needed = ctx.offer("REDEEM_BAG")
    seat_pref = "extra" if intent.wants_extra_seat else "front" if intent.wants_front_seat else ctx.seat_preference
    if needed and needed.needed and needed.affordable:
        redeem = Pick(offer_id="REDEEM_BAG", why=f"Your planned luggage is more than your allowance. It costs {_n(needed.points)} points.")
    if redeem is None:
        wanted = {"extra": "REDEEM_EXTRA", "front": "REDEEM_PREFERRED"}.get(seat_pref)
        chosen = ctx.offer(wanted) if wanted else None
        if intent.saving and not (chosen and chosen.included):
            chosen = None  # they would rather keep their points; a seat their benefits cover is still free
        if chosen is None and seat_pref == "any":
            included = [o for o in ctx.offers if o.kind == "redeem" and o.included and o.id != "REDEEM_BAG"]
            chosen = included[-1] if included else None  # the highest seat their benefits cover
        if chosen is not None and chosen.affordable:
            redeem = Pick(
                offer_id=chosen.id,
                why="Your own benefits already cover this seat." if chosen.included else f"It matches the seat you wanted and costs {_n(chosen.points)} points.",
            )
    if redeem:
        picks.append(redeem)

    # Things the traveller asked for by name, when the offer exists and they can afford it.
    asked = [
        (intent.heavy_bag, "REDEEM_OVERWEIGHT", "You mentioned a heavy bag. The overweight allowance costs {p} points."),
        (intent.wants_standby, "REDEEM_STANDBY", "You may want to change flights. Same-day standby costs {p} points."),
        (intent.wants_drink, "REDEEM_DRINK", "You mentioned a drink. It costs {p} points."),
    ]
    if not intent.saving:
        for wanted_flag, offer_id, text in asked:
            o = ctx.offer(offer_id)
            if wanted_flag and o and o.affordable and len(picks) < MAX_PICKS:
                picks.append(Pick(offer_id=o.id, why=text.format(p=_n(o.points))))

    # Small perks. Boarding is bought only by someone who said they want it, and never released by them.
    boarding = ctx.offer("REDEEM_BOARDING")
    early = ctx.wants_early_boarding or intent.wants_boarding
    if early and boarding and boarding.affordable and not intent.saving and len(picks) < MAX_PICKS:
        picks.append(Pick(offer_id=boarding.id, why=f"You asked for earlier boarding. It costs {_n(boarding.points)} points."))
    small = [
        o
        for o in ctx.offers
        if o.kind == "release" and o.id not in BIG_RELEASES and not (o.id == "RELEASE_BOARDING" and early)
    ]
    for o in sorted(small, key=lambda o: -o.points):
        if len(picks) >= MAX_PICKS:
            break
        picks.append(Pick(offer_id=o.id, why=f"Earn {_n(o.points)} points for a perk you may not use, pending until you fly."))

    parts = [f"You have {_n(ctx.balance)} points to spend"]
    if ctx.pending:
        parts[0] += f" and {_n(ctx.pending)} pending"
    summary = parts[0] + "."
    if needed and needed.needed and not needed.affordable:
        summary += f" Your planned luggage needs another bag, which is {_n(needed.shortfall)} points away."
    wanted_offer = ctx.offer({"extra": "REDEEM_EXTRA", "front": "REDEEM_PREFERRED"}.get(seat_pref, ""))
    if wanted_offer and not wanted_offer.affordable:
        summary += f" The seat you wanted is {_n(wanted_offer.shortfall)} points away."
    if intent.any and picks:
        summary += " I used what you told me to narrow this."
    elif not picks:
        summary += " Nothing stands out for this trip, but every option is listed below."
    else:
        summary += " Here is what fits this trip best."
    return AdviceResponse(source="fallback", summary=summary, picks=picks, offers=list(ctx.offers))


def advise(
    ctx: AdvisorContext,
    request: AdviceRequest,
    agent: Advisor | None = None,
    screen: Callable[[str], bool] = screen_message,
) -> AdviceResponse:
    """Needs no database: `ctx` was built beforehand, so no connection is held during the (slow) model call.

    `agent` defaults to the loop this process is configured for (local Bedrock, or an AgentCore runtime). `screen`
    is the guardrail check on the traveller's free text; text it blocks is dropped and the rules alone decide.
    """
    message = clean(request.message, 500)
    if ctx.open and parse_intent(message).wants_points:
        return deterministic_advice(ctx, message)  # a points request is answered by the rules alone: no model, no guardrail call
    if not ctx.open or not ctx.offers:
        return deterministic_advice(ctx, message)  # nothing to choose between, so no model call and no model spend
    if message and screen(message):
        message = ""
    agent = agent or default_agent()
    started = time.monotonic()

    def check(sub: dict[str, Any]) -> None:
        validate_submission(sub, ctx)

    try:
        result = agent(AdvisorInput(message=message, ctx=ctx, check=check))
        response = validate_submission(result.submission, ctx)
        log.info(json.dumps({"evt": "assistant.perk_advice", "source": "ai", "ms": int((time.monotonic() - started) * 1000), "toolCalls": result.tool_calls}))
        return response
    except Exception as error:  # the model, the network or validation failed: the traveller still gets advice
        log.warning(
            json.dumps({"evt": "assistant.perk_advice", "source": "fallback", "ms": int((time.monotonic() - started) * 1000), "reason": str(error)[:200], "guardrail": isinstance(error, GuardrailBlocked)})
        )
        return deterministic_advice(ctx, message)


def nudge(ctx: AdvisorContext) -> Nudge | None:
    """One proactive hint, or None. Rules only: it costs no model call, so it can be shown on every check-in.

    Order of value to the traveller: a bag they need, something their benefits already cover (free), then a release.
    """
    if not ctx.open or not ctx.offers:
        return None
    picks = deterministic_advice(ctx).picks
    offers = [o for p in picks if (o := ctx.offer(p.offer_id))]
    if not offers:
        return None

    def rank(o: Offer) -> int:
        if o.id == "REDEEM_BAG" and o.needed:
            return 0
        if o.included:
            return 1
        if o.kind == "release":
            return 2 if o.id in BIG_RELEASES else 3
        return 4

    best = min(offers, key=rank)
    if best.id == "REDEEM_BAG":
        text = f"Your planned luggage needs another bag. It costs {_n(best.points)} points and you have enough."
    elif best.included:
        text = f"Your benefits already cover {best.label}. You can use it at no cost."
    elif best.id == "RELEASE_BAG":
        text = f"You are not using one of your bags. Release it to earn {_n(best.points)} points, pending until you fly."
    elif best.id == "RELEASE_SEAT":
        text = f"You could swap to a Standard seat and earn {_n(best.points)} points, pending until you fly."
    elif best.id.startswith("RELEASE_"):  # a small perk
        text = f"Not using it? {best.label} to earn {_n(best.points)} points, pending until you fly."
    elif best.id in ("REDEEM_BOARDING", "REDEEM_DRINK", "REDEEM_STANDBY", "REDEEM_OVERWEIGHT"):
        text = f"{best.label} for {_n(best.points)} points."
    else:
        text = f"{best.label} matches the seat you wanted, for {_n(best.points)} points."
    return Nudge(offer_id=best.id, kind=best.kind, text=text, points=best.points)
