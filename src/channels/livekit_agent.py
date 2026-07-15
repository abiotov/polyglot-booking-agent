"""Realtime voice channel: LiveKit Agents wired to the same brain.

    uv run python -m channels.livekit_agent console   # local mic, no server
    uv run python -m channels.livekit_agent dev       # LiveKit server/cloud

Requires scripts/run_radicale.py running and, in .env: DEEPGRAM_API_KEY,
CARTESIA_API_KEY plus the LLM key (OPENAI_API_KEY by default).

Design: LiveKit provides the realtime plumbing (mic, VAD, streaming STT,
barge-in, TTS playback); the conversation brain stays OUR BookingAgent,
plugged in by overriding Agent.llm_node. LiveKit never sees the tools or
the calendar; it hands us the caller's transcribed turn and receives the
reply text. One brain, three channels, as the architecture demands.

Language switching: the turn's language is detected from the transcript
text (speech.langdetect) because audio-level detection proved unreliable
on short clips in live Telegram sessions. The detected tag drives the
agent's [lang=xx] tag and the Cartesia voice via update_options, so the
receptionist keeps one identity across languages.

Tradeoff accepted for v1: our brain runs its tool loop to completion and
the reply is yielded as one chunk, so TTS starts after the LLM finishes
instead of streaming token by token. Costs roughly a second of latency;
keeps a single tested brain. Revisit only if latency data demands it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterable
from typing import Any

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, llm
from livekit.plugins import cartesia, deepgram, silero

from agent import BookingAgent, BookingToolbox, build_system_prompt
from agent.providers import get_provider
from calendar_adapter import CalDAVCalendar
from scheduling_engine import load_config
from speech.langdetect import detect_language

logger = logging.getLogger("channels.livekit")

_AMELIE = "faa75703-00e3-4a57-9955-0703001e3231"
DEFAULT_VOICES = {"fr": _AMELIE, "en": _AMELIE}

GREETING = (
    "Bonjour, vous êtes bien à l'accueil. Comment puis-je vous aider ? "
    "Hello, you have reached the reception. How can I help?"
)


class RealtimeReceptionist(Agent):
    """LiveKit Agent whose 'LLM' is the project's BookingAgent."""

    def __init__(
        self,
        brain: BookingAgent,
        tts: cartesia.TTS,
        voices: dict[str, str],
        languages: tuple[str, ...],
    ) -> None:
        # instructions are required by LiveKit but unused: the brain owns
        # its own system prompt.
        super().__init__(instructions="handled by BookingAgent")
        self._brain = brain
        # Named to avoid colliding with livekit.agents.Agent's own _tts.
        self._voice_tts = tts
        self._voices = voices
        self._languages = languages
        self._last_language = languages[0]

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: Any,
    ) -> AsyncIterable[str]:
        user_text = _last_user_text(chat_ctx)
        if not user_text.strip():
            yield GREETING
            return

        language = detect_language(
            user_text, languages=self._languages, fallback=self._last_language
        )
        self._last_language = language
        # The reply will be voiced in the caller's language.
        self._voice_tts.update_options(language=language, voice=self._voices[language])

        reply = await asyncio.to_thread(
            self._brain.run_turn, user_text, None, language
        )
        logger.info("lang=%s heard=%r reply_len=%d", language, user_text[:80], len(reply))
        yield reply


def _last_user_text(chat_ctx: llm.ChatContext) -> str:
    for item in reversed(chat_ctx.items):
        if isinstance(item, llm.ChatMessage) and item.role == "user":
            text = item.text_content
            return text if isinstance(text, str) else ""
    return ""


def _build_brain() -> tuple[BookingAgent, tuple[str, ...]]:
    config = load_config(os.environ.get("PRACTICE_CONFIG", "config/practice.example.yaml"))
    calendar = CalDAVCalendar(
        url=os.environ.get("CALDAV_URL", "http://127.0.0.1:5232"),
        username="agent",
        password="agent",
        calendar_name=os.environ.get("CALDAV_CALENDAR", "appointments"),
        timezone=config.practice.timezone,
    )
    provider = get_provider(os.environ.get("AGENT_LLM_PROVIDER", "openai"))
    brain = BookingAgent(
        provider=provider,
        toolbox=BookingToolbox(calendar, config),
        system_prompt=build_system_prompt(config),
    )
    return brain, tuple(config.practice.languages)


async def entrypoint(ctx: JobContext) -> None:
    brain, languages = _build_brain()
    voices = {
        "fr": os.environ.get("CARTESIA_VOICE_FR", DEFAULT_VOICES["fr"]),
        "en": os.environ.get("CARTESIA_VOICE_EN", DEFAULT_VOICES["en"]),
    }
    tts = cartesia.TTS(model="sonic-3", language=languages[0], voice=voices[languages[0]])
    session: AgentSession[Any] = AgentSession(
        stt=deepgram.STT(model="nova-3", language="multi"),
        tts=tts,
        vad=silero.VAD.load(),
    )
    await session.start(
        agent=RealtimeReceptionist(brain, tts, voices, languages),
        room=ctx.room,
    )
    await session.say(GREETING)


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))


if __name__ == "__main__":
    main()
