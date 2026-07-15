"""Deepgram speech-to-text adapter (prerecorded audio, e.g. voice notes).

Uses the plain REST API over a persistent HTTP client (voice notes come
in bursts; paying TLS setup per clip was measured at several seconds on
a slow uplink). Language detection is requested per utterance; the
detected language feeds the agent's [lang=xx] tag, which drives both
the reply language and the TTS voice.

Short clips defeat unrestricted language detection: live tests saw
"Premium, premiere visite" detected as German and truncated. Detection
is therefore restricted to the practice's declared languages (the
`languages` parameter), which fixed it. As a last resort, an empty
transcript is retried once with the fallback language forced, which
trades detection for recognition instead of losing the message.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx

from .types import Utterance

logger = logging.getLogger("speech.deepgram")

_ENDPOINT = "https://api.deepgram.com/v1/listen"


class DeepgramSTT:
    def __init__(
        self,
        api_key: str,
        model: str = "nova-2",
        languages: Sequence[str] = ("fr", "en"),
        fallback_language: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """`languages` are the detection candidates (the practice's languages)."""
        if not languages:
            raise ValueError("languages must not be empty")
        self._model = model
        self._languages = tuple(languages)
        self._fallback_language = fallback_language or self._languages[0]
        self._client = httpx.Client(
            headers={"Authorization": f"Token {api_key}"},
            timeout=timeout,
        )

    def transcribe(self, audio: bytes, mime_type: str) -> Utterance:
        text, language = self._request(audio, mime_type, detect=True)
        if not text.strip():
            logger.info(
                "empty transcript with detection (%d KB); retrying with lang=%s forced",
                len(audio) // 1024,
                self._fallback_language,
            )
            text, language = self._request(audio, mime_type, detect=False)
        return Utterance(text=text, language=language)

    def _request(self, audio: bytes, mime_type: str, detect: bool) -> tuple[str, str]:
        params: list[tuple[str, str]] = [
            ("model", self._model),
            ("smart_format", "true"),
        ]
        if detect:
            # Restrict detection to the practice's languages.
            params.extend(("detect_language", lang) for lang in self._languages)
        else:
            params.append(("language", self._fallback_language))
        response = self._client.post(
            _ENDPOINT,
            params=params,
            headers={"Content-Type": mime_type},
            content=audio,
        )
        response.raise_for_status()
        channel = response.json()["results"]["channels"][0]
        transcript = str(channel["alternatives"][0]["transcript"])
        language = str(channel.get("detected_language") or self._fallback_language)
        # Deepgram may return regional codes ("en-US"); keep the base tag.
        return transcript, language.split("-")[0]
