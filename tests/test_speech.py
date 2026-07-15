"""Speech-layer unit tests (pure logic; network adapters are live-tested)."""

from __future__ import annotations

from speech.langdetect import mostly_latin


def test_french_and_english_pass() -> None:
    assert mostly_latin("Ce serait le mardi prochain, première visite.")
    assert mostly_latin("Yes, please book it.")


def test_hallucinated_scripts_fail() -> None:
    # Observed live: a noisy French clip transcribed as Mandarin.
    assert not mostly_latin("事 情")
    assert not mostly_latin("Привет мир")


def test_edge_cases() -> None:
    assert mostly_latin("")  # emptiness is judged elsewhere
    assert mostly_latin("10h15 !")  # digits and punctuation are neutral
    assert mostly_latin("café 事")  # majority Latin wins
