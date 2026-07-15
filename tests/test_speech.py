"""Speech-layer unit tests (pure logic; network adapters are live-tested)."""

from __future__ import annotations

from speech.deepgram_stt import _mostly_latin


def test_french_and_english_pass() -> None:
    assert _mostly_latin("Ce serait le mardi prochain, première visite.")
    assert _mostly_latin("Yes, please book it.")


def test_hallucinated_scripts_fail() -> None:
    # Observed live: a noisy French clip transcribed as Mandarin.
    assert not _mostly_latin("事 情")
    assert not _mostly_latin("Привет мир")


def test_edge_cases() -> None:
    assert _mostly_latin("")  # emptiness is judged elsewhere
    assert _mostly_latin("10h15 !")  # digits and punctuation are neutral
    assert _mostly_latin("café 事")  # majority Latin wins
