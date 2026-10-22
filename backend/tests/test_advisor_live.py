"""The saved advisor cases against the real model (Amazon Bedrock). Skipped unless run with `-m live`:

    cd backend && ../../.venv/bin/python -m pytest -q -m live tests/test_advisor_live.py

For a readable report (and repeats), use scripts/eval_advisor.py instead.
"""

import os

import pytest

from app.advisor.advisor import advise
from app.advisor.types import AdviceRequest
from app.config import get_settings

from .advisor_support import context_for, load_cases, problems

pytestmark = pytest.mark.live
if not (os.environ.get("AWS_BEARER_TOKEN_BEDROCK") and get_settings().bedrock_model_id):
    pytestmark = [pytest.mark.live, pytest.mark.skip(reason="no Bedrock credentials or model id in .env")]

# Cases where the model actually gets to choose.
MODEL_CASES = [c for c in load_cases() if context_for(c).open and context_for(c).offers]


def test_the_model_meets_every_expectation_and_is_mostly_used():
    failures, ai = {}, 0
    for case in MODEL_CASES:
        ctx = context_for(case)
        r = advise(ctx, AdviceRequest(message=case.get("message")))
        ai += r.source == "ai"
        found = problems(case, ctx, r, case.get("live", {}))
        if found:
            failures[case["id"]] = found
    assert not failures, failures
    # A model that is always rejected would pass the checks above by falling back, so require real use of it.
    assert ai >= 0.7 * len(MODEL_CASES), f"only {ai} of {len(MODEL_CASES)} answers came from the model"
