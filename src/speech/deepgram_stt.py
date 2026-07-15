"""Deepgram speech-to-text adapter (prerecorded audio, e.g. voice notes).

Uses the plain REST API: one POST per clip, no SDK dependency. Language
detection is requested per utterance; the detected language feeds the
agent's [lang=xx] tag, which drives both the reply language and (in
voice channels) the TTS voice.
"""

from __future__ import annotations

import httpx

from .types import Utterance

_ENDPOINT = "https://api.deepgram.com/v1/listen"


class DeepgramSTT:
    def __init__(
        self,
        api_key: str,
        model: str = "nova-2",
        fallback_language: str = "fr",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._fallback_language = fallback_language
        self._timeout = timeout

    def transcribe(self, audio: bytes, mime_type: str) -> Utterance:
        response = httpx.post(
            _ENDPOINT,
            params={
                "model": self._model,
                "detect_language": "true",
                "smart_format": "true",
            },
            headers={
                "Authorization": f"Token {self._api_key}",
                "Content-Type": mime_type,
            },
            content=audio,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        channel = payload["results"]["channels"][0]
        transcript = str(channel["alternatives"][0]["transcript"])
        language = str(channel.get("detected_language") or self._fallback_language)
        # Deepgram may return regional codes ("en-US"); keep the base tag.
        return Utterance(text=transcript, language=language.split("-")[0])
