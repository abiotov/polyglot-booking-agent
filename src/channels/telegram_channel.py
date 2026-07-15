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

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from agent import BookingAgent
from speech.types import AudioClip, STTProvider, TTSProvider

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
        return ChannelReply(text=agent.run_turn(text))

    def handle_voice(self, chat_id: int, audio: bytes, mime_type: str) -> ChannelReply:
        """Voice note in, voice note out (plus transcript text)."""
        utterance = self._stt.transcribe(audio, mime_type)
        if not utterance.text.strip():
            return ChannelReply(text=UNHEARD_REPLY)
        agent = self._session(chat_id)
        reply_text = agent.run_turn(utterance.text, language=utterance.language)
        clip = self._tts.synthesize(reply_text, utterance.language)
        return ChannelReply(text=reply_text, voice=clip)

    def _session(self, chat_id: int) -> BookingAgent:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = self._agent_factory()
        return self._sessions[chat_id]
