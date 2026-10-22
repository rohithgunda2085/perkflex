"""The tools the fare assistant may call. All are read-only: none can book, spend points or change data."""

from dataclasses import dataclass
from typing import Any

from ..rules.data import FARES, SEAT_NAMES, fare_by_id
from ..rules.pricing import Inventory, Needs, entitlements, quote_fares, sanitize_needs
from ..services.context import TravellerInfo


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool may read. Built once per request, so tools never touch the database."""

    traveller: TravellerInfo
    flight_id: str  # e.g. "WN2418"
    inventory: Inventory
    base_needs: Needs


_NEEDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bags": {"type": "integer", "minimum": 0, "maximum": 3, "description": "Checked bags"},
        "seat": {
            "type": "string",
            "enum": ["any", "front", "extra"],
            "description": "front = Preferred seat near the front; extra = Extra Legroom",
        },
        "refund": {"type": "boolean", "description": "Needs a refundable ticket"},
        "flexible": {"type": "boolean", "description": "Needs flight changes included"},
        "seatNow": {"type": "boolean", "description": "Wants to choose a seat at booking"},
        "early": {"type": "boolean", "description": "Wants priority boarding"},
        "budget": {"type": "number", "description": "Maximum total in US dollars, taxes and extras included"},
    },
    "required": ["bags", "seat", "refund", "flexible", "seatNow", "early", "budget"],
}

TOOL_CONFIG: dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": "quote_fares",
                "description": (
                    "Prices all four fares for the given needs using the airline's rules. Each quote has a total in "
                    "dollars and an 'issues' list; a fare with issues does NOT meet the needs. "
                    "This is the only source of prices."
                ),
                "inputSchema": {
                    "json": {"type": "object", "properties": {"needs": _NEEDS_SCHEMA}, "required": ["needs"]}
                },
            }
        },
        {
            "toolSpec": {
                "name": "submit_recommendation",
                "description": (
                    "Final answer. Call exactly once, after you have prices. "
                    "Do not include prices you did not get from quote_fares."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "needs": _NEEDS_SCHEMA,
                            "fare": {
                                "type": "string",
                                "enum": ["basic", "choice", "preferred", "extra", "none"],
                                "description": "'none' only when every fare has issues",
                            },
                            "reasons": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 4,
                                "description": "Short reasons this fare fits this traveller",
                            },
                            "explanation": {"type": "string", "description": "At most 60 words, plain text, friendly"},
                            "alternatives": {
                                "type": "array",
                                "maxItems": 2,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "fare": {"type": "string", "enum": ["basic", "choice", "preferred", "extra"]},
                                        "tradeoff": {"type": "string"},
                                    },
                                    "required": ["fare", "tradeoff"],
                                },
                                "description": "Closest options when fare is 'none'",
                            },
                        },
                        "required": ["needs", "fare", "reasons", "explanation"],
                    }
                },
            }
        },
    ]
}


def describe_traveller(ctx: ToolContext) -> dict[str, Any]:
    """What the traveller already has, per fare. Sent in the first message to save a model round trip."""
    t = ctx.traveller
    included = []
    for fare in FARES:
        e = entitlements(t.pricing, fare.id)
        included.append(
            {
                "fare": fare.id,
                "name": fare.name,
                "bagsIncluded": e.bags,
                "bagsFrom": e.bag_source,
                "seatIncluded": SEAT_NAMES[e.seat],
                "seatFrom": e.seat_source,
                "refundable": e.refundable,
                "changesIncluded": e.flexible,
                "priorityBoarding": e.early,
                "chooseSeatAtBooking": e.choose_now,
            }
        )
    return {"tier": t.tier, "card": t.card, "pointsAvailable": t.balance, "includedWithEachFare": included}


def quote_tool(raw_needs: Any, ctx: ToolContext) -> dict[str, Any]:
    needs = sanitize_needs(raw_needs, ctx.base_needs)
    quotes = quote_fares(ctx.traveller.pricing, needs, ctx.flight_id, ctx.inventory)
    return {
        "needsUsed": needs.model_dump(by_alias=True),
        "quotes": [
            {
                "fare": q.fare,
                "name": fare_by_id(q.fare).name,
                "totalUsd": q.total,
                "addons": [a.model_dump() for a in q.addons],
                "bagsCovered": q.bags,
                "seat": SEAT_NAMES[q.seat],
                "issues": q.issues,
                "meetsAllNeeds": not q.issues,
            }
            for q in quotes
        ],
    }


def run_tool(name: str, tool_input: Any, ctx: ToolContext) -> dict[str, Any]:
    """Runs a read-only tool. Raises on unknown names so the model gets an error result."""
    if name == "quote_fares":
        raw = tool_input.get("needs") if isinstance(tool_input, dict) else None
        return quote_tool(raw, ctx)
    raise ValueError(f"Unknown tool {name}")
