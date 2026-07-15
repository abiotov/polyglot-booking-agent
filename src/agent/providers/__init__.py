"""LLM provider adapters and factory.

Selecting a provider is configuration, not code:

    provider = get_provider("openai")   # or "gemini"

Models can be overridden with OPENAI_MODEL / GEMINI_MODEL.
"""

from __future__ import annotations

import os

from .base import LLMProvider
from .fake import ScriptedProvider

__all__ = ["LLMProvider", "ScriptedProvider", "get_provider"]


def get_provider(name: str) -> LLMProvider:
    """Build a provider from environment variables.

    Raises ValueError for an unknown name or a missing API key, so a
    misconfiguration fails at startup, not mid-conversation.
    """
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=_require_env("OPENAI_API_KEY"),
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )
    if name == "gemini":
        from .gemini_provider import GeminiProvider

        return GeminiProvider(
            api_key=_require_env("GEMINI_API_KEY"),
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        )
    raise ValueError(f"unknown provider {name!r} (known: openai, gemini)")


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise ValueError(f"{key} is not set; put it in .env or the environment")
    return value
