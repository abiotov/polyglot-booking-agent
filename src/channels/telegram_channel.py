"""Telegram channel logic, independent from the Telegram SDK.

This class owns the channel behavior so it can be tested without
network or bot token; the thin glue in telegram_bot.py only moves bytes
between Telegram and here.

Behavior:
- Text and voice are both accepted, in any order, in one conversation.
- Modality is mirrored: text in, text out; voice in, voice out (with
  the transcript as caption, so the reply is also readable).
- Each voice note goes through STT with language detection; the
  detected language feeds the agent's [lang=xx] tag and selects the
  TTS voice. Mid-conversation language switching costs nothing.
- One agent session per Telegram chat: two callers never share state.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from agent import BookingAgent
from speech.types import AudioClip, STTProvider, TTSProvider

logger = logging.getLogger("channels.telegram")

UNHEARD_REPLY = (
    "Désolé, je n'ai pas pu entendre votre message. Pouvez-vous réessayer ? / "
    "Sorry, I could not hear your message. Could you try again?"
)


class ChannelReply(BaseModel):
    """What the glue must send back to the chat."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    text: str
    voice: AudioClip | None = None


class TelegramChannel:
    def __init__(
        self,
        agent_factory: Callable[[], BookingAgent],
        stt: STTProvider,
        tts: TTSProvider,
    ) -> None:
        self._agent_factory = agent_factory
        self._stt = stt
        self._tts = tts
        self._sessions: dict[int, BookingAgent] = {}

    def handle_text(self, chat_id: int, text: str) -> ChannelReply:
        """Typed message in, typed reply out."""
        agent = self._session(chat_id)
        started = time.perf_counter()
        reply_text = agent.run_turn(text)
        logger.info(
            "chat=%s modality=text llm=%.1fs in=%d out=%d",
            chat_id, time.perf_counter() - started, len(text), len(reply_text),
        )
        return ChannelReply(text=reply_text)

    def handle_voice(self, chat_id: int, audio: bytes, mime_type: str) -> ChannelReply:
        """Voice note in, voice note out (plus transcript text)."""
        t0 = time.perf_counter()
        utterance = self._stt.transcribe(audio, mime_type)
        t1 = time.perf_counter()
        if not utterance.text.strip():
            logger.info(
                "chat=%s modality=voice stt=%.1fs empty transcription", chat_id, t1 - t0
            )
            return ChannelReply(text=UNHEARD_REPLY)
        agent = self._session(chat_id)
        reply_text = agent.run_turn(utterance.text, language=utterance.language)
        t2 = time.perf_counter()
        clip = self._tts.synthesize(reply_text, utterance.language)
        t3 = time.perf_counter()
        logger.info(
            "chat=%s modality=voice lang=%s stt=%.1fs llm=%.1fs tts=%.1fs total=%.1fs "
            "heard=%r",
            chat_id, utterance.language, t1 - t0, t2 - t1, t3 - t2, t3 - t0,
            utterance.text[:80],
        )
        return ChannelReply(text=reply_text, voice=clip)

    def _session(self, chat_id: int) -> BookingAgent:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = self._agent_factory()
        return self._sessions[chat_id]
