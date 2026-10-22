"""Bedrock Guardrails around the advisor: a second layer beside the validator, never a replacement for it.

Two uses, both optional (they switch on when BEDROCK_GUARDRAIL_ID is set):
  * screen_message: the traveller's free text is checked with ApplyGuardrail before any model call. If the guardrail
    intervenes, or cannot be reached, the text is dropped and the advice is built from the rules alone.
  * guardrail_config / raise_if_blocked: every Converse call runs under the guardrail, and a reply it blocks is
    treated as a failure, so the traveller gets the rules-only advice.
The validator in advisor.py still checks every answer: offers, affordability, and every number.
"""

import json
import logging
from typing import Any

log = logging.getLogger("perkflex.advisor")


class GuardrailBlocked(RuntimeError):
    """The guardrail stopped the model's reply."""


def _settings(settings: Any = None) -> Any:
    if settings is not None:
        return settings
    from ..config import get_settings

    return get_settings()


def guardrail_config(settings: Any = None) -> dict[str, Any] | None:
    """The `guardrailConfig` argument for Converse, or None when no guardrail is configured."""
    s = _settings(settings)
    gid = getattr(s, "bedrock_guardrail_id", "") or ""
    if not gid:
        return None
    return {
        "guardrailIdentifier": gid,
        "guardrailVersion": getattr(s, "bedrock_guardrail_version", "") or "DRAFT",
        "trace": "enabled",
    }


def converse_extras(settings: Any = None) -> dict[str, Any]:
    """Keyword arguments to splat into client.converse(...): empty without a guardrail."""
    cfg = guardrail_config(settings)
    return {"guardrailConfig": cfg} if cfg else {}


def raise_if_blocked(response: dict[str, Any]) -> None:
    if response.get("stopReason") == "guardrail_intervened":
        raise GuardrailBlocked("the guardrail blocked the model's reply")


def screen_message(text: str, settings: Any = None, client: Any = None) -> bool:
    """True when the free text must not reach the model. Without a guardrail nothing is blocked here.

    Fails closed: if the guardrail cannot be reached, the text is treated as blocked (and the advice is built from
    the rules alone), so an outage never lets unscreened text through.
    """
    cfg = guardrail_config(settings)
    if not cfg or not text:
        return False
    try:
        if client is None:
            from ..assistant.agent import _bedrock

            client = _bedrock()
        response = client.apply_guardrail(
            guardrailIdentifier=cfg["guardrailIdentifier"],
            guardrailVersion=cfg["guardrailVersion"],
            source="INPUT",
            content=[{"text": {"text": text}}],
        )
    except Exception as error:
        log.warning(json.dumps({"evt": "guardrail.input", "result": "unreachable", "reason": str(error)[:200]}))
        return True
    blocked = response.get("action") == "GUARDRAIL_INTERVENED"
    log.info(json.dumps({"evt": "guardrail.input", "result": "blocked" if blocked else "passed"}))
    return blocked
