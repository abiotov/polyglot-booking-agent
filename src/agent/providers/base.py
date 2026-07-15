"""The LLM provider interface.

A provider is stateless: it receives the full neutral history on every
call and returns one reply. All conversation state lives in the agent
loop, which is what makes providers swappable mid-project.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from agent.types import ChatMessage, ProviderReply, ToolSpec


class LLMProvider(Protocol):
    """Anything that can complete a tool-aware chat turn."""

    @property
    def name(self) -> str: ...

    def complete(
        self,
        system: str,
        history: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
    ) -> ProviderReply: ...
