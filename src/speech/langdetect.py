"""Tiny text-based language detection for realtime turns.

In the realtime channel the transcript arrives as streaming text; the
utterance language is decided here, from the words themselves, instead
of trusting audio-level detection (which live sessions showed to be
unreliable on short clips). Scoring is a plain marker-word and
diacritics count: transparent, fast, and easily extended with a new
word list per language.

Ambiguous turns ("ok", a name, a number) keep the previous language,
which is what a human receptionist does too.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_MARKERS: dict[str, frozenset[str]] = {
    "fr": frozenset(
        """
        le la les un une des du de au aux et ou mais donc car ne pas plus
        je tu il elle nous vous ils on ce cette ces mon ma mes votre vos
        suis est sont ai as avez voudrais aimerais peux pouvez faut
        bonjour bonsoir merci oui non peut-être s'il plait plaît
        rendez-vous reserver réserver annuler deplacer déplacer demain
        aujourd'hui matin apres-midi après-midi semaine prochain prochaine
        premier premiere première deuxieme deuxième visite lundi mardi
        mercredi jeudi vendredi samedi dimanche heure heures pour avec chez
        """.split()  # noqa: SIM905 - a word list reads better as prose
    ),
    "en": frozenset(
        """
        the a an and or but so not i you he she we they it this that my
        your is are am was have has had would like want can could may
        hello hi thanks thank yes no maybe please appointment book
        booking cancel move reschedule tomorrow today morning afternoon
        next week first second visit monday tuesday wednesday thursday
        friday saturday sunday o'clock for with at
        """.split()  # noqa: SIM905 - a word list reads better as prose
    ),
}

_FRENCH_DIACRITICS = re.compile(r"[àâäçéèêëîïôöùûüÿœ]")
_WORD = re.compile(r"[a-zA-Zàâäçéèêëîïôöùûüÿœ'-]+")


def detect_language(
    text: str,
    languages: Sequence[str] = ("fr", "en"),
    fallback: str = "fr",
) -> str:
    """Most plausible language of `text` among `languages`.

    Returns `fallback` (typically the previous turn's language) when the
    text carries no usable signal.
    """
    lowered = text.lower()
    words = _WORD.findall(lowered)
    scores: dict[str, int] = {}
    for lang in languages:
        markers = _MARKERS.get(lang)
        if markers is None:
            continue
        scores[lang] = sum(1 for w in words if w in markers)
    if "fr" in scores:
        scores["fr"] += 2 * len(_FRENCH_DIACRITICS.findall(lowered))

    best = max(scores, key=lambda lang: scores[lang], default=fallback)
    if not scores or scores[best] == 0:
        return fallback
    tied = [lang for lang, s in scores.items() if s == scores[best]]
    return fallback if len(tied) > 1 and fallback in tied else best
