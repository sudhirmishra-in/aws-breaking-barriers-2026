"""An offline stand-in for Bedrock: replays a script and records what each model call received."""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from strands.models import Model


def say(text: str) -> dict[str, Any]:
    return {"text": text}


def call(name: str, **tool_input: Any) -> dict[str, Any]:
    return {"tool": name, "input": tool_input}


@dataclass(frozen=True)
class ModelCall:
    system_prompt: str
    tool_names: tuple[str, ...]
    messages: list[dict[str, Any]]


class ScriptedModel(Model):
    """`script` receives each call and returns the content blocks for the model's reply."""

    def __init__(self, script: Callable[[ModelCall], list[dict[str, Any]]]) -> None:
        self._script = script
        self.calls: list[ModelCall] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {}

    async def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs: Any):
        tool_names = tuple(sorted(spec["name"] for spec in tool_specs or []))
        model_call = ModelCall(system_prompt or "", tool_names, json.loads(json.dumps(messages)))
        self.calls.append(model_call)
        blocks = self._script(model_call)
        yield {"messageStart": {"role": "assistant"}}
        for block in blocks:
            if "tool" in block:
                start = {"toolUse": {"name": block["tool"], "toolUseId": uuid.uuid4().hex}}
                yield {"contentBlockStart": {"start": start}}
                delta = {"toolUse": {"input": json.dumps(block["input"], ensure_ascii=False)}}
                yield {"contentBlockDelta": {"delta": delta}}
            else:
                yield {"contentBlockStart": {"start": {}}}
                yield {"contentBlockDelta": {"delta": {"text": block["text"]}}}
            yield {"contentBlockStop": {}}
        stop_reason = "tool_use" if any("tool" in block for block in blocks) else "end_turn"
        yield {"messageStop": {"stopReason": stop_reason}}
        usage = {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}
        yield {"metadata": {"usage": usage, "metrics": {"latencyMs": 1}}}
