"""The advisor, as a function of a payload. No web framework and no database, so it is easy to test.

Payload in:  {"message": str, "context": <ctx_to_wire(...)>}
Payload out: {"submission": {...}, "toolCalls": int}  or  {"error": "..."}

The API validates the submission again against its own copy of the offers, so this side is not trusted.
The check below only lets the model correct itself once, exactly as in a local run.
"""

from typing import Any

from app.advisor.advisor import clean, validate_submission
from app.advisor.agent import Advisor, AdvisorInput, run_advisor
from app.advisor.offers import ctx_from_wire


def handle(payload: Any, agent: Advisor = run_advisor) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        ctx = ctx_from_wire(payload.get("context"))
        message = clean(payload.get("message", ""), 500)

        def check(sub: dict[str, Any]) -> None:
            validate_submission(sub, ctx)

        result = agent(AdvisorInput(message=message, ctx=ctx, check=check))
        return {"submission": result.submission, "toolCalls": result.tool_calls}
    except Exception as error:  # the API turns any error into the rules-only advice
        return {"error": f"{type(error).__name__}: {str(error)[:200]}"}
