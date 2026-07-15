"""Observability must be a strict no-op when not configured.

Tests and CI never talk to Opik; the decorated functions must behave
exactly like the originals when no key is present.
"""

from __future__ import annotations

import sys

import pytest

import observability
from observability import flush, traced


@pytest.fixture(autouse=True)
def no_opik_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPIK_API_KEY", raising=False)
    monkeypatch.delenv("OPIK_URL_OVERRIDE", raising=False)
    observability._state.clear()  # re-evaluate against the clean env


def test_traced_is_a_passthrough_without_config() -> None:
    calls: list[int] = []

    @traced("test-span")
    def add(a: int, b: int) -> int:
        calls.append(a)
        return a + b

    assert add(2, 3) == 5
    assert calls == [2]
    assert add.__name__ == "add"  # wraps preserved


def test_flush_is_silent_without_config() -> None:
    flush()  # must not raise, must not import opik


def test_opik_is_never_imported_when_disabled() -> None:
    @traced("test-span")
    def fn() -> str:
        return "ok"

    before = "opik" in sys.modules
    fn()
    flush()
    # traced/flush must not pull the SDK in when disabled. If opik was
    # already imported by an unrelated test, this still holds vacuously.
    assert ("opik" in sys.modules) == before


def test_exceptions_propagate_unchanged() -> None:
    @traced("test-span")
    def boom() -> None:
        raise ValueError("original")

    with pytest.raises(ValueError, match="original"):
        boom()
