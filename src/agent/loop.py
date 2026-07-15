"""The conversation loop.

One run_turn() call takes the caller's text and returns the agent's
reply, executing as many tool rounds as the model requests in between
(bounded by max_tool_rounds). All state is the neutral history plus the
toolbox's session state; the provider is stateless and swappable.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import NamedTuple

from observability import traced

from .providers.base import LLMProvider
from .tools import BookingToolbox
from .types import ChatMessage

DEFAULT_MAX_TOOL_ROUNDS = 8


class ToolRound(NamedTuple):
    """The brain is about to execute these tools (progress signal)."""

    names: tuple[str, ...]


class FinalReply(NamedTuple):
    """The brain's user-facing answer for this turn."""

    text: str


TurnEvent = ToolRound | FinalReply


class BookingAgent:
    def __init__(
        self,
        provider: LLMProvider,
        toolbox: BookingToolbox,
        system_prompt: str,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ) -> None:
        self._provider = provider
        self._toolbox = toolbox
        self._system_prompt = system_prompt
        self._max_tool_rounds = max_tool_rounds
        self.history: list[ChatMessage] = []

    @traced("conversation-turn")
    def run_turn(
        self,
        user_text: str,
        today: date | None = None,
        language: str | None = None,
    ) -> str:
        """Process one caller message and return the agent's reply."""
        for event in self.run_turn_events(user_text, today=today, language=language):
            if isinstance(event, FinalReply):
                return event.text
        raise AssertionError("run_turn_events always ends with a FinalReply")

    def run_turn_events(
        self,
        user_text: str,
        today: date | None = None,
        language: str | None = None,
    ) -> Iterator[TurnEvent]:
        """Like run_turn, but yields progress events as the turn unfolds.

        Voice channels use the ToolRound events to speak a natural filler
        ("one moment, let me check the schedule") while tool rounds cost
        their network round trips, instead of leaving dead air.

        `language` is the utterance language detected by the channel.
        When present it is prepended as a [lang=xx] tag that the system
        prompt declares authoritative, which makes mid-call language
        switching deterministic instead of hoping the model notices.
        """
        system = self._system_prompt.replace(
            "{today}", (today or date.today()).isoformat()
        )
        content = f"[lang={language}] {user_text}" if language else user_text
        self.history.append(ChatMessage(role="user", content=content))

        for _ in range(self._max_tool_rounds):
            reply = self._provider.complete(system, self.history, self._toolbox.specs())

            if not reply.tool_calls:
                self.history.append(ChatMessage(role="assistant", content=reply.text))
                yield FinalReply(reply.text)
                return

            yield ToolRound(tuple(call.name for call in reply.tool_calls))
            self.history.append(
                ChatMessage(role="assistant", content=reply.text, tool_calls=reply.tool_calls)
            )
            for call in reply.tool_calls:
                result = self._toolbox.dispatch(call.name, call.arguments)
                self.history.append(
                    ChatMessage(
                        role="tool",
                        content=result,
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                )

        # The model kept calling tools without ever answering; fail safe
        # with a polite handover instead of looping forever.
        fallback = "I am sorry, something went wrong on my side. Could you repeat that?"
        self.history.append(ChatMessage(role="assistant", content=fallback))
        yield FinalReply(fallback)
