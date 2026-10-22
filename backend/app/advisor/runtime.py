"""Runs the advisor's model loop in a separate runtime: Amazon Bedrock AgentCore Runtime.

The API sends the traveller's context and message as the payload. The runtime (backend/agent_runtime) has no database
access: it runs the same loop and returns a submission. Nothing is trusted on the way back. advise() validates the
submission against the offers exactly as it does for a local run, and any failure here becomes the rules-only advice.

Choose it with ADVISOR_RUNTIME=agentcore and AGENTCORE_RUNTIME_ARN=<the runtime's ARN>. The default is "local".
"""

import json
import uuid
from typing import Any

from .agent import Advisor, AdvisorInput, AdvisorResult, run_advisor
from .offers import ctx_to_wire


def _client() -> Any:
    import boto3
    from botocore.config import Config

    from ..config import get_settings

    return boto3.client(
        "bedrock-agentcore",
        region_name=get_settings().aws_region,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 1, "mode": "standard"}),
    )


def run_advisor_remote(inp: AdvisorInput, client: Any = None, settings: Any = None) -> AdvisorResult:
    """Invokes the AgentCore runtime. Raises on any failure; the caller falls back to the rules-only advice."""
    if settings is None:
        from ..config import get_settings

        settings = get_settings()
    arn = getattr(settings, "agentcore_runtime_arn", "")
    if not arn:
        raise RuntimeError("AGENTCORE_RUNTIME_ARN is not set")
    client = client or _client()
    request: dict[str, Any] = {
        "agentRuntimeArn": arn,
        "contentType": "application/json",
        "accept": "application/json",
        "runtimeSessionId": f"perkflex-advisor-{uuid.uuid4().hex}",  # one session per call: nothing is remembered
        "payload": json.dumps({"message": inp.message, "context": ctx_to_wire(inp.ctx)}).encode("utf-8"),
    }
    qualifier = getattr(settings, "agentcore_qualifier", "")
    if qualifier:
        request["qualifier"] = qualifier
    response = client.invoke_agent_runtime(**request)
    if response.get("statusCode", 200) != 200:
        raise RuntimeError(f"AgentCore returned status {response.get('statusCode')}")
    data = json.loads(response["response"].read())
    if not isinstance(data, dict) or data.get("error"):
        raise RuntimeError(f"AgentCore runtime error: {str(data.get('error') if isinstance(data, dict) else data)[:200]}")
    submission = data.get("submission")
    if not isinstance(submission, dict):
        raise RuntimeError("AgentCore runtime returned no submission")
    return AdvisorResult(submission, int(data.get("toolCalls", 0)))


def default_agent(settings: Any = None) -> Advisor:
    """The loop to use for this process: the local Bedrock loop, or the AgentCore runtime when it is configured."""
    if settings is None:
        from ..config import get_settings

        settings = get_settings()
    if getattr(settings, "advisor_runtime", "local") == "agentcore" and getattr(settings, "agentcore_runtime_arn", ""):
        return run_advisor_remote
    return run_advisor
