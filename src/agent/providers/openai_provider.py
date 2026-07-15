"""OpenAI chat-completions adapter (default: gpt-4o-mini)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from openai import OpenAI

from agent.types import ChatMessage, ProviderReply, ToolCall, ToolSpec
from observability import traced


class OpenAIProvider:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    @traced("openai-complete", span_type="llm")
    def complete(
        self,
        system: str,
        history: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
    ) -> ProviderReply:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=self._to_messages(system, history),
            tools=[self._to_tool(t) for t in tools],
        )
        message = response.choices[0].message
        calls = tuple(
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=json.loads(call.function.arguments or "{}"),
            )
            for call in message.tool_calls or []
            if call.type == "function"
        )
        return ProviderReply(text=message.content or "", tool_calls=calls)

    @staticmethod
    def _to_messages(system: str, history: Sequence[ChatMessage]) -> list[Any]:
        messages: list[Any] = [{"role": "system", "content": system}]
        for item in history:
            if item.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.tool_call_id,
                        "content": item.content,
                    }
                )
            elif item.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": item.content or None,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.arguments),
                                },
                            }
                            for call in item.tool_calls
                        ],
                    }
                )
            else:
                messages.append({"role": item.role, "content": item.content})
        return messages

    @staticmethod
    def _to_tool(spec: ToolSpec) -> Any:
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
                "strict": True,
            },
        }
