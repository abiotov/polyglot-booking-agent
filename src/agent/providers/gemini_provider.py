"""Google Gemini adapter (default: gemini-2.5-flash)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from google import genai
from google.genai import types as gtypes

from agent.types import ChatMessage, ProviderReply, ToolCall, ToolSpec


class GeminiProvider:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return f"gemini:{self._model}"

    def complete(
        self,
        system: str,
        history: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
    ) -> ProviderReply:
        response = self._client.models.generate_content(
            model=self._model,
            # cast: the SDK's ContentListUnion defeats list invariance
            contents=cast(Any, self._to_contents(history)),
            config=gtypes.GenerateContentConfig(
                system_instruction=system,
                tools=[
                    gtypes.Tool(
                        function_declarations=[self._to_declaration(t) for t in tools]
                    )
                ],
                automatic_function_calling=gtypes.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        candidate = response.candidates[0] if response.candidates else None
        parts = candidate.content.parts if candidate and candidate.content else None
        for part in parts or []:
            if part.function_call is not None:
                calls.append(
                    ToolCall(
                        # Gemini does not assign call ids; make one for the history.
                        id=part.function_call.id or f"gemini-{uuid.uuid4().hex[:8]}",
                        name=part.function_call.name or "",
                        arguments=dict(part.function_call.args or {}),
                    )
                )
            elif part.text:
                text_parts.append(part.text)
        return ProviderReply(text="".join(text_parts), tool_calls=tuple(calls))

    @staticmethod
    def _to_contents(history: Sequence[ChatMessage]) -> list[gtypes.Content]:
        contents: list[gtypes.Content] = []
        for item in history:
            if item.role == "tool":
                contents.append(
                    gtypes.Content(
                        role="user",
                        parts=[
                            gtypes.Part.from_function_response(
                                name=item.tool_name or "",
                                response={"result": item.content},
                            )
                        ],
                    )
                )
            elif item.tool_calls:
                contents.append(
                    gtypes.Content(
                        role="model",
                        parts=[
                            gtypes.Part(
                                function_call=gtypes.FunctionCall(
                                    name=call.name, args=call.arguments
                                )
                            )
                            for call in item.tool_calls
                        ],
                    )
                )
            else:
                role = "model" if item.role == "assistant" else "user"
                contents.append(
                    gtypes.Content(role=role, parts=[gtypes.Part(text=item.content)])
                )
        return contents

    @staticmethod
    def _to_declaration(spec: ToolSpec) -> gtypes.FunctionDeclaration:
        return gtypes.FunctionDeclaration(
            name=spec.name,
            description=spec.description,
            parameters=_to_genai_schema(spec.parameters),
        )


def _to_genai_schema(schema: dict[str, Any]) -> gtypes.Schema:
    """Translate plain JSON Schema into the genai Schema type.

    Only the subset our tools use: object, string, enum, required.
    """
    type_map = {"object": "OBJECT", "string": "STRING", "integer": "INTEGER"}
    kwargs: dict[str, Any] = {"type": type_map[schema["type"]]}
    if "description" in schema:
        kwargs["description"] = schema["description"]
    if "enum" in schema:
        kwargs["enum"] = list(schema["enum"])
    if "properties" in schema:
        kwargs["properties"] = {
            key: _to_genai_schema(value) for key, value in schema["properties"].items()
        }
    if "required" in schema:
        kwargs["required"] = list(schema["required"])
    return gtypes.Schema(**kwargs)
