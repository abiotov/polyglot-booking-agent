"""Speech provider interfaces.

Same philosophy as the LLM providers: small stateless protocols, so
Deepgram or Cartesia can be swapped (for faster-whisper, Piper, or a
test fake) without touching any channel code.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Utterance(BaseModel):
    """One transcribed audio message."""

    model_config = ConfigDict(frozen=True)

    text: str
    language: str  # ISO 639-1, e.g. "fr", "en"


class AudioClip(BaseModel):
    """One synthesized audio reply."""

    model_config = ConfigDict(frozen=True)

    data: bytes
    mime_type: str  # e.g. "audio/mpeg"


class STTProvider(Protocol):
    """Speech to text with per-utterance language detection."""

    def transcribe(self, audio: bytes, mime_type: str) -> Utterance: ...


class TTSProvider(Protocol):
    """Text to speech with a voice per language."""

    def synthesize(self, text: str, language: str) -> AudioClip: ...
