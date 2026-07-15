"""Optional LLM observability (Opik), off unless configured.

Same philosophy as every provider in this project: observability is a
swappable adapter, and the system runs identically without it. When
OPIK_API_KEY (cloud) or OPIK_URL_OVERRIDE (self-hosted) is present,
decorated functions are traced to Opik: conversations become trace
trees (turn -> LLM rounds -> tool calls) and eval campaigns become
experiments. Without configuration, `traced` is a strict no-op: no
import of the opik package, no network, no warnings, which keeps tests
and CI hermetic.

Opik's own LLM-as-judge metrics are deliberately not used as a source
of truth: deterministic checks stay the verdict (design decision 8);
Opik is for seeing and comparing, not judging.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])
SpanType = Literal["general", "tool", "llm", "guardrail"]

_state: dict[str, bool] = {}


def enabled() -> bool:
    """True when an Opik destination is configured (checked once)."""
    if "enabled" not in _state:
        _state["enabled"] = bool(
            os.environ.get("OPIK_API_KEY") or os.environ.get("OPIK_URL_OVERRIDE")
        )
    return _state["enabled"]


def traced(name: str, span_type: SpanType = "general") -> Callable[[F], F]:
    """Trace a function to Opik, or leave it untouched when disabled.

    The check happens at call time, not import time, because entrypoints
    load .env inside main() after modules are imported. span_type is one
    of Opik's kinds: "general", "llm", "tool".
    """

    def decorate(fn: F) -> F:
        tracked: Callable[..., Any] | None = None

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not enabled():
                return fn(*args, **kwargs)
            nonlocal tracked
            if tracked is None:
                import opik

                tracked = opik.track(name=name, type=span_type)(fn)
            return tracked(*args, **kwargs)

        return cast(F, wrapper)

    return decorate


def flush() -> None:
    """Push any buffered traces (call before short-lived processes exit)."""
    if not enabled():
        return
    import opik

    opik.flush_tracker()
