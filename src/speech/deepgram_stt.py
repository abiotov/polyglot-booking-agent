"""Deepgram speech-to-text adapter (prerecorded audio, e.g. voice notes).

Uses the plain REST API over a persistent HTTP client (voice notes come
in bursts; paying TLS setup per clip was measured at several seconds on
a slow uplink).

Language handling evolved through live sessions, in three steps:
1. nova-2 with unrestricted detect_language lost short clips entirely
   ("Premium, premiere visite" detected as German, empty transcripts).
2. Restricting detection to the practice's languages fixed short clips
   but nova-2's French stayed mediocre on real phone audio ("Ce serait
   le mardi" heard as "Se croire le mardi").
3. nova-3 with language=multi transcribes both well AND tags every word
   with its language, so the utterance language is computed here as the
   dominant word language. That tag feeds the agent's [lang=xx] tag and
   the TTS voice.

As a last resort, an empty transcript is retried once with the fallback
language forced, which trades detection for recognition instead of
losing the message.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from typing import Any

import httpx

from observability import traced

from .langdetect import mostly_latin
from .types import Utterance

logger = logging.getLogger("speech.deepgram")

_ENDPOINT = "https://api.deepgram.com/v1/listen"

Params = list[tuple[str, str | int | float | bool | None]]


class DeepgramSTT:
    def __init__(
        self,
        api_key: str,
        model: str = "nova-3",
        languages: Sequence[str] = ("fr", "en"),
        fallback_language: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """`languages` are the practice's languages; the dominant word
        language is only ever chosen among them."""
        if not languages:
            raise ValueError("languages must not be empty")
        self._model = model
        self._languages = tuple(languages)
        self._fallback_language = fallback_language or self._languages[0]
        self._client = httpx.Client(
            headers={"Authorization": f"Token {api_key}"},
            timeout=timeout,
        )

    @traced("deepgram-stt", span_type="tool")
    def transcribe(self, audio: bytes, mime_type: str) -> Utterance:
        text, language = self._multilingual_request(audio, mime_type)
        if not text.strip() or not mostly_latin(text):
            # Multi mode covers ~10 languages and can hallucinate one on a
            # noisy short clip (a live session was transcribed in Mandarin).
            # The practice's languages are Latin-script, so a mostly
            # non-Latin transcript is a recognition failure, not a caller
            # speaking Chinese.
            logger.info(
                "unusable transcript in multi mode (%d KB, %r); "
                "retrying with lang=%s forced",
                len(audio) // 1024,
                text[:40],
                self._fallback_language,
            )
            text, language = self._forced_request(audio, mime_type)
        return Utterance(text=text, language=language)

    def _multilingual_request(self, audio: bytes, mime_type: str) -> tuple[str, str]:
        params: Params = [
            ("model", self._model),
            ("smart_format", "true"),
            ("language", "multi"),
        ]
        alternative = self._post(params, audio, mime_type)
        transcript = str(alternative.get("transcript", ""))
        word_languages = [
            str(word["language"]).split("-")[0]
            for word in alternative.get("words", [])
            if word.get("language")
        ]
        counts = Counter(lang for lang in word_languages if lang in self._languages)
        dominant = counts.most_common(1)[0][0] if counts else self._fallback_language
        return transcript, dominant

    def _forced_request(self, audio: bytes, mime_type: str) -> tuple[str, str]:
        params: Params = [
            ("model", self._model),
            ("smart_format", "true"),
            ("language", self._fallback_language),
        ]
        alternative = self._post(params, audio, mime_type)
        return str(alternative.get("transcript", "")), self._fallback_language

    def _post(self, params: Params, audio: bytes, mime_type: str) -> dict[str, Any]:
        response = self._client.post(
            _ENDPOINT,
            params=params,
            headers={"Content-Type": mime_type},
            content=audio,
        )
        response.raise_for_status()
        alternative: dict[str, Any] = response.json()["results"]["channels"][0][
            "alternatives"
        ][0]
        return alternative
