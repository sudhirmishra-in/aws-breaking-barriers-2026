"""AgentCore Runtime entrypoint (HTTP protocol). Callers are IAM-authorised backend roles only."""

import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from exchange.runtime import handle_turn

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context=None):
    if isinstance(payload, dict) and payload.get("ping"):
        return {"status": "ok", "version": os.environ.get("DEPLOYED_COMMIT", "unknown")}
    return handle_turn(payload)


if __name__ == "__main__":
    app.run()
