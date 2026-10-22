"""The Python pricing rules must reproduce the TypeScript engine exactly.

The fixtures (fixtures/pricing_parity.json) were generated once from the original TypeScript engine over a fixed,
seeded set of inputs. The engine has since been removed, so the file is the frozen reference. Do not regenerate it
from the Python code: that would make the test compare the rules with themselves.
"""

import json
from pathlib import Path

import pytest

from app.rules.data import TIER_FLYING_BONUS_PCT, with_bonus

from app.rules.pricing import (
    Inventory,
    Needs,
    Traveller,
    entitlements,
    quote_fares,
    recommended_quote,
)

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "pricing_parity.json").read_text())


def _dump(model) -> dict:
    return model.model_dump(by_alias=True)


@pytest.mark.parametrize(
    "case",
    FIXTURES["entitlements"],
    ids=lambda c: f"{c['tier']}-{c['card']}-{c['fare']}-{c['stage']}",
)
def test_entitlements_match_typescript(case):
    got = entitlements(Traveller(case["tier"], case["card"]), case["fare"], case["stage"])
    assert _dump(got) == case["result"]


def _inventory(counts: dict | None) -> Inventory | None:
    if counts is None:
        return None
    return Inventory(
        seats={cls: [f"{cls[0]}{n}" for n in range(counts[cls])] for cls in ("standard", "preferred", "extra")}
    )


def test_quotes_match_typescript_for_every_case():
    mismatches = []
    for i, case in enumerate(FIXTURES["quotes"]):
        quotes = quote_fares(
            Traveller(case["tier"], case["card"]),
            Needs.model_validate(case["needs"]),
            case["flightId"],
            _inventory(case["inventory"]),
        )
        got = [_dump(q) for q in quotes]
        # Flying points now include the status bonus and the quote says how they were worked out; the TypeScript
        # fixtures predate both, so check those two fields separately and compare everything else as it was.
        bonus = TIER_FLYING_BONUS_PCT[case["tier"]]
        for g, want in zip(got, case["quotes"]):
            assert g.pop("statusBonus") == bonus and g.pop("rate") > 0
            assert g["points"] == with_bonus(want["points"], bonus)
            g["points"] = want["points"]
        best = recommended_quote(quotes)
        if got != case["quotes"] or (best.fare if best else None) != case["recommended"]:
            mismatches.append(i)
    assert not mismatches, f"{len(mismatches)} of {len(FIXTURES['quotes'])} cases differ, first: {mismatches[:5]}"


def test_fixtures_exercise_the_interesting_paths():
    """Guards the fixtures themselves, so a degenerate regeneration cannot make the parity test vacuous."""
    issues = {i.split(" ")[0] + " " + (i.split(" ")[1] if len(i.split(" ")) > 1 else "")
              for c in FIXTURES["quotes"] for q in c["quotes"] for i in q["issues"]}
    assert any("Over" in i for i in issues)
    assert any("Not" in i for i in issues)
    assert any("unavailable" in q_issue for c in FIXTURES["quotes"] for q in c["quotes"] for q_issue in q["issues"])
    assert sum(1 for c in FIXTURES["quotes"] if c["recommended"]) > 100
    assert sum(1 for c in FIXTURES["quotes"] if not c["recommended"]) > 100
