"""Text-based language detection: the realtime channel's language signal."""

from __future__ import annotations

from speech.langdetect import detect_language


def test_clear_french() -> None:
    assert detect_language("Bonjour, je voudrais un rendez-vous lundi matin.") == "fr"
    assert detect_language("C'est une première visite, je suis premium.") == "fr"


def test_clear_english() -> None:
    assert detect_language("Good morning, I would like to book an appointment.") == "en"
    assert detect_language("The first one works for me, thanks.") == "en"


def test_switch_is_per_turn() -> None:
    assert detect_language("Yes, please book it.", fallback="fr") == "en"
    assert detect_language("Oui, c'est parfait, merci.", fallback="en") == "fr"


def test_ambiguous_keeps_previous_language() -> None:
    # Names, numbers, bare acknowledgements carry no signal.
    assert detect_language("Jean Kokou, +229 97 00 00 01", fallback="fr") == "fr"
    assert detect_language("Jean Kokou, +229 97 00 00 01", fallback="en") == "en"
    assert detect_language("ok", fallback="en") == "en"
    assert detect_language("", fallback="fr") == "fr"


def test_diacritics_vote_french() -> None:
    assert detect_language("très bien, à lundi", fallback="en") == "fr"
