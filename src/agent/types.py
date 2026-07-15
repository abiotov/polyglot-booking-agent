"""Provider-agnostic chat types.

The agent loop and the toolbox only ever see these shapes. Each provider
adapter translates them to its native wire format, so swapping OpenAI
for Gemini (or a scripted fake in tests) never touches agent logic.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Role = Literal["user", "assistant", "tool"]


class ToolSpec(BaseModel):
    """A callable tool, described once in plain JSON Schema."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters: dict[str, Any]


class ToolCall(BaseModel):
    """The model asking for one tool execution."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]


class ChatMessage(BaseModel):
    """One entry of the conversation history.

    - user text:        role="user", content
    - assistant text:   role="assistant", content
    - assistant call:   role="assistant", tool_calls
    - tool result:      role="tool", tool_call_id, tool_name, content
    """

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None


class ProviderReply(BaseModel):
    """What a provider returns for one completion: text, tool calls, or both."""

    model_config = ConfigDict(frozen=True)

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
