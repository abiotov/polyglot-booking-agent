"""Cartesia Sonic text-to-speech adapter.

One voice per language, selected from the [lang=xx] tag the agent
already maintains. Output is MP3, which Telegram accepts for voice
notes and browsers can play directly.
"""

from __future__ import annotations

import httpx

from .types import AudioClip

_ENDPOINT = "https://api.cartesia.ai/tts/bytes"
_VERSION = "2025-04-16"


class CartesiaTTS:
    def __init__(
        self,
        api_key: str,
        voices: dict[str, str],
        model: str = "sonic-2",
        fallback_language: str = "fr",
        timeout: float = 60.0,
    ) -> None:
        """`voices` maps a language tag to a Cartesia voice id."""
        if fallback_language not in voices:
            raise ValueError(f"voices must include the fallback language {fallback_language!r}")
        self._api_key = api_key
        self._voices = voices
        self._model = model
        self._fallback_language = fallback_language
        self._timeout = timeout

    def synthesize(self, text: str, language: str) -> AudioClip:
        lang = language if language in self._voices else self._fallback_language
        response = httpx.post(
            _ENDPOINT,
            headers={
                "X-API-Key": self._api_key,
                "Cartesia-Version": _VERSION,
                "Content-Type": "application/json",
            },
            json={
                "model_id": self._model,
                "transcript": text,
                "language": lang,
                "voice": {"mode": "id", "id": self._voices[lang]},
                "output_format": {
                    "container": "mp3",
                    "bit_rate": 128000,
                    "sample_rate": 44100,
                },
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        return AudioClip(data=response.content, mime_type="audio/mpeg")
