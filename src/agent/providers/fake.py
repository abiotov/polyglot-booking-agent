"""A scripted provider for tests.

Plays back a fixed sequence of replies, so the agent loop and the
toolbox can be tested end to end without any API key or network. The
"LLM" here is the test scenario itself.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent.types import ChatMessage, ProviderReply, ToolSpec


class ScriptedProvider:
    """Returns pre-recorded replies in order; records what it was asked."""

    def __init__(self, replies: Sequence[ProviderReply]) -> None:
        self._replies = list(replies)
        self._cursor = 0
        self.seen_histories: list[tuple[ChatMessage, ...]] = []

    @property
    def name(self) -> str:
        return "scripted"

    def complete(
        self,
        system: str,
        history: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
    ) -> ProviderReply:
        self.seen_histories.append(tuple(history))
        if self._cursor >= len(self._replies):
            raise AssertionError("scripted provider ran out of replies")
        reply = self._replies[self._cursor]
        self._cursor += 1
        return reply
