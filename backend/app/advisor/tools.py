"""The tools the perk advisor may call. Both are read-only: nothing here can release, buy or change anything."""

from typing import Any

from ..rules.data import REDEEM_POINTS, RELEASE_POINTS
from .types import MAX_PICKS, OFFER_IDS

# Plain-language rules the model may quote. Written once here so the model never has to remember them.
RULES_TEXT: dict[str, str] = {
    "one_release": "A traveller can accept one rewarded release per flight: either a bag or a seat, not both. Small perks (priority boarding, a premium drink, priority lane) are separate and do not use that release.",
    "small_perks": "Priority boarding, a premium drink and priority lane can be released for points if the traveller's fare or status already includes them. Priority boarding and a premium drink can be bought with points if not included. Priority lane cannot be bought. Small perks can earn at most 300 points per flight and stay pending until the flight is completed.",
    "pending": "Points earned by releasing a benefit stay pending until the flight is completed. Pending points cannot be spent.",
    "payment": "Redemptions use PerkFlex points first, then Rapid Rewards points.",
    "seat_swap": "Releasing an upgraded seat moves the traveller to an available Standard seat. The upgraded seat cannot be reclaimed for free.",
    "status_bonus": "Release rewards include a bonus for status: Silver +10 percent, Gold +20 percent, Platinum +30 percent. The offers already include it, so quote the offer points. The 300-point small-perk limit counts points before the bonus.",
    "closing": "Benefit changes close when check-in is completed.",
    "budget": "Release rewards come from a budget for each flight. When it runs out, release offers disappear.",
}

TOOL_CONFIG: dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": "explain_rule",
                "description": "Returns one PerkFlex rule in plain words. Use it instead of remembering rules.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"topic": {"type": "string", "enum": sorted(RULES_TEXT)}},
                        "required": ["topic"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "submit_advice",
                "description": (
                    "Final answer. Call exactly once. Pick at most four offers by id (at most one bag-or-seat release; small perks do not count toward it), say why in "
                    "plain words, and do not state any number that is not in the offers or the traveller's balances."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string", "description": "At most 60 words, plain text, friendly"},
                            "picks": {
                                "type": "array",
                                "maxItems": MAX_PICKS,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "offerId": {"type": "string", "enum": list(OFFER_IDS)},
                                        "why": {"type": "string", "description": "One short sentence"},
                                    },
                                    "required": ["offerId", "why"],
                                },
                            },
                        },
                        "required": ["summary", "picks"],
                    }
                },
            }
        },
    ]
}


def run_tool(name: str, tool_input: Any) -> dict[str, Any]:
    """Runs a read-only tool. Raises on unknown names so the model gets an error result."""
    if name == "explain_rule":
        topic = tool_input.get("topic") if isinstance(tool_input, dict) else None
        if topic not in RULES_TEXT:
            raise ValueError("Unknown topic")
        return {"topic": topic, "rule": RULES_TEXT[topic]}
    raise ValueError(f"Unknown tool {name}")


# Re-exported so tests can check the numbers the rules text may mention are the engine's.
KNOWN_RULE_VALUES = {*RELEASE_POINTS.values(), *REDEEM_POINTS.values()}
