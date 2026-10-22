"""Entry point for Amazon Bedrock AgentCore Runtime (listens on 8080: POST /invocations, GET /ping)."""

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent_runtime.handler import handle

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    return handle(payload)


if __name__ == "__main__":
    app.run()
