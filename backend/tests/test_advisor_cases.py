"""The saved advisor evaluation cases (tests/fixtures/advisor_cases.json), offline.

Each case is a traveller situation, an optional message, and what is expected. Here every case is run through the
rules-only advice, so the offers, the fallback and the safety properties are checked with no model and no network.
The same cases run against the real model with `python scripts/eval_advisor.py` (see that file).
"""

from app.advisor.advisor import assert_text_verified, deterministic_advice, nudge, validate_submission

from .advisor_support import context_for, load_cases, problems

CASES = load_cases()


def test_there_are_enough_cases_and_ids_are_unique():
    assert len(CASES) >= 15
    assert len({c["id"] for c in CASES}) == len(CASES)


def test_every_case_matches_its_rules_only_expectations():
    failures = {}
    for case in CASES:
        ctx = context_for(case)
        r = deterministic_advice(ctx, case.get("message") or "")
        expect = case["fallback"]
        found = problems(case, ctx, r, expect)
        for needle in expect.get("summaryContains", []):
            if needle not in r.summary:
                found.append(f"summary lacks {needle!r}: {r.summary!r}")
        if found:
            failures[case["id"]] = found
    assert not failures, failures


def test_every_rules_only_answer_passes_the_validator_that_checks_model_answers():
    for case in CASES:
        ctx = context_for(case)
        if not ctx.open:
            continue
        r = deterministic_advice(ctx, case.get("message") or "")
        validate_submission({"summary": r.summary, "picks": [{"offerId": p.offer_id, "why": p.why} for p in r.picks]}, ctx)


def test_every_nudge_is_consistent_with_the_advice_and_uses_only_verified_numbers():
    shown = 0
    for case in CASES:
        ctx = context_for(case)
        n = nudge(ctx)  # a nudge is shown without a message, so it is compared with the message-free advice
        picks = [p.offer_id for p in deterministic_advice(ctx).picks]
        if not picks:
            assert n is None, case["id"]
            continue
        assert n is not None and n.offer_id in picks, case["id"]
        assert_text_verified(n.text, ctx)
        shown += 1
    assert shown >= 6


def test_a_nudge_prefers_a_needed_bag_then_a_free_seat_then_a_release():
    by_id = {c["id"]: c for c in CASES}
    assert nudge(context_for(by_id["needs-another-bag-can-afford"])).offer_id == "REDEEM_BAG"
    assert "no cost" in nudge(context_for(by_id["benefits-already-cover-extra-seat"])).text
    n = nudge(context_for(by_id["maya-unused-bag-and-extra-seat"]))
    assert n.offer_id == "RELEASE_SEAT" and "pending until you fly" in n.text
    assert nudge(context_for(by_id["check-in-not-open"])) is None
