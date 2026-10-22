"""Finding the traveller's best fare.

The model reads the request and explains. The rules engine prices everything. This module rejects any model answer
that disagrees with the engine, and falls back to a rules-only answer whenever the model is unavailable or wrong.
"""

import json
import logging
import re
import time
from typing import Any

from ..rules.data import FARES, RELEASE_POINTS, REDEEM_POINTS, SEAT_NAMES, TAX_CENTS
from ..rules.pricing import Needs, Quote, entitlements, quote_fares, recommended_quote, sanitize_needs
from ..services.context import TravellerInfo
from .agent import Agent, AgentInput, run_agent
from .tools import ToolContext
from .types import Alternative, BestFareRequest, BestFareResponse, Recommendation

log = logging.getLogger("perkflex.assistant")

FARE_IDS = {f.id for f in FARES}


class SubmissionRejected(ValueError):
    """The model's answer contradicts the pricing rules."""


def clean(value: Any, limit: int) -> str:
    """Strips control characters, collapses whitespace and caps the length."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]+", " ", value)).strip()[:limit]


# "$282.60", "282.60 dollars", "282.60 USD" and "USD 282.60" are all checked.
_DOLLAR_FORMS = (
    re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)"),
    re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)\s*(?:dollars?|usd|bucks)\b", re.IGNORECASE),
    re.compile(r"\busd\s?(\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE),
)
_POINTS_FORM = re.compile(r"(\d[\d,]*)\s*(?:points|pts)\b", re.IGNORECASE)


def assert_amounts_verified(text: str, quotes: list[Quote], needs: Needs, traveller: TravellerInfo) -> None:
    """Every dollar amount in model text must be one the engine produced (a total, a base fare, an add-on, the
    budget) or a difference between two of them; every points amount must be a known balance or rule value."""
    usd: list[float] = [needs.budget, TAX_CENTS / 100]
    for q in quotes:
        usd += [q.total, q.base, q.tax, abs(needs.budget - q.total), *(a.price for a in q.addons)]
        usd += [abs(q.total - other.total) for other in quotes]
    for form in _DOLLAR_FORMS:
        for m in form.finditer(text):
            value = float(m.group(1).replace(",", ""))
            if not any(abs(a - value) < 0.006 for a in usd):
                raise SubmissionRejected(f"unverified amount {m.group(0)}")
    points = {traveller.balance, *RELEASE_POINTS.values(), *REDEEM_POINTS.values(), *(q.points for q in quotes)}
    for m in _POINTS_FORM.finditer(text):
        if int(m.group(1).replace(",", "")) not in points:
            raise SubmissionRejected(f"unverified points {m.group(0)}")


def closest_alternatives(quotes: list[Quote]) -> list[Alternative]:
    ranked = sorted(quotes, key=lambda q: (len(q.issues), q.total))[:2]
    return [Alternative(fare=q.fare, total=q.total, tradeoff=" · ".join(q.issues) or "Meets your needs") for q in ranked]


def validate_submission(sub: dict[str, Any], ctx: ToolContext, has_message: bool) -> BestFareResponse:
    """Turns the model's submission into a response, or raises SubmissionRejected."""
    fare = sub.get("fare")
    if not isinstance(fare, str) or not (fare == "none" or fare in FARE_IDS):
        raise SubmissionRejected("invalid fare id")

    # Without a message the form is the source of truth; the model cannot loosen the requirements.
    needs = sanitize_needs(sub.get("needs"), ctx.base_needs) if has_message else ctx.base_needs
    quotes = quote_fares(ctx.traveller.pricing, needs, ctx.flight_id, ctx.inventory)
    valid = [q for q in quotes if not q.issues]

    explanation = clean(sub.get("explanation"), 400)
    if not explanation:
        raise SubmissionRejected("empty explanation")
    raw_reasons = sub.get("reasons")
    reasons = [r for r in (clean(x, 180) for x in (raw_reasons if isinstance(raw_reasons, list) else [])) if r][:4]
    for text in (explanation, *reasons):
        assert_amounts_verified(text, quotes, needs, ctx.traveller)

    if fare == "none":
        if valid:
            raise SubmissionRejected("model said no fare fits, but the rules engine found one")
        seen: set[str] = set()
        alternatives: list[Alternative] = []
        raw_alts = sub.get("alternatives")
        for raw in raw_alts if isinstance(raw_alts, list) else []:
            q = next((x for x in quotes if isinstance(raw, dict) and x.fare == raw.get("fare")), None)
            if q is None or q.fare in seen:
                continue
            seen.add(q.fare)
            tradeoff = clean(raw.get("tradeoff"), 160) or " · ".join(q.issues)
            assert_amounts_verified(tradeoff, quotes, needs, ctx.traveller)
            alternatives.append(Alternative(fare=q.fare, total=q.total, tradeoff=tradeoff))
            if len(alternatives) == 2:
                break
        return BestFareResponse(
            source="ai",
            understood=needs,
            recommendation=Recommendation(fare=None, total=None, reasons=reasons),
            alternatives=alternatives or closest_alternatives(quotes),
            explanation=explanation,
            quotes=quotes,
        )

    chosen = next((q for q in valid if q.fare == fare), None)
    if chosen is None:
        raise SubmissionRejected("recommended fare does not meet the stated needs")
    return BestFareResponse(
        source="ai",
        understood=needs,
        recommendation=Recommendation(fare=chosen.fare, total=chosen.total, reasons=reasons),
        alternatives=[],
        explanation=explanation,
        quotes=quotes,
    )


def deterministic_best_fare(ctx: ToolContext, needs: Needs) -> BestFareResponse:
    """The rules-only answer, used whenever the model is unavailable or fails validation."""
    quotes = quote_fares(ctx.traveller.pricing, needs, ctx.flight_id, ctx.inventory)
    best = recommended_quote(quotes)
    if best is None:
        return BestFareResponse(
            source="fallback",
            understood=needs,
            recommendation=Recommendation(fare=None, total=None, reasons=[]),
            alternatives=closest_alternatives(quotes),
            explanation="No fare meets every selection within your budget. Try a larger budget or remove an optional preference.",
            quotes=quotes,
        )
    e = entitlements(ctx.traveller.pricing, best.fare)
    reasons: list[str] = []
    if needs.refund:
        reasons.append("A refundable fare protects your changing plans.")
    if needs.seat != "any":
        through = f" through {e.seat_source}" if "benefits" in e.seat_source else ""
        reasons.append(f"{SEAT_NAMES[best.seat]} is included in your quote{through}.")
    if needs.bags > 0:
        covered = f" by {e.bag_source}" if e.bags >= needs.bags else " in your total"
        reasons.append(f"{needs.bags} checked bag{'s are' if needs.bags > 1 else ' is'} covered{covered}.")
    if needs.flexible:
        reasons.append("Flight changes are included; fare differences may apply.")
    if needs.seat_now:
        reasons.append("You can select an available seat when you book.")
    if needs.early:
        reasons.append("Priority boarding fits your preference.")
    if not reasons:
        reasons.append("You’re travelling light. This is the lowest-priced fit.")

    if best.fare == "extra":
        tip = "You’re choosing Extra for benefits you need today. Any unused-benefit offer comes later, before check-in."
    elif ctx.traveller.tier in ("Gold", "Platinum"):
        tip = "Your status already covers premium seating and bags. We recommend a higher fare only when its extra features help."
    else:
        tip = "You can explore eligible points offers before check-in. Future rewards are not counted as a discount today."
    return BestFareResponse(
        source="fallback",
        understood=needs,
        recommendation=Recommendation(fare=best.fare, total=best.total, reasons=reasons),
        alternatives=[],
        explanation=tip,
        quotes=quotes,
    )


def best_fare(ctx: ToolContext, request: BestFareRequest, agent: Agent = run_agent) -> BestFareResponse:
    """Needs no database: `ctx` was read beforehand, so no connection is held during the (slow) model call."""
    message = clean(request.message, 500)
    base = ctx.base_needs
    started = time.monotonic()

    def check(sub: dict[str, Any]) -> None:
        validate_submission(sub, ctx, bool(message))

    try:
        result = agent(AgentInput(message=message, needs=base, ctx=ctx, check=check))
        response = validate_submission(result.submission, ctx, bool(message))
        log.info(json.dumps({"evt": "assistant.best_fare", "source": "ai", "ms": int((time.monotonic() - started) * 1000), "toolCalls": result.tool_calls}))
        return response
    except Exception as error:  # the model, the network or validation failed: the traveller still gets an answer
        log.warning(
            json.dumps(
                {"evt": "assistant.best_fare", "source": "fallback", "ms": int((time.monotonic() - started) * 1000), "reason": str(error)[:200]}
            )
        )
        return deterministic_best_fare(ctx, base)
