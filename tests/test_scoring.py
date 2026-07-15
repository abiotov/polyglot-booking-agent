"""Stage 2: compaction scoring. The engine ranks like a good receptionist."""

from __future__ import annotations

from datetime import date, datetime

from scheduling_engine import rank_slots
from scheduling_engine.models import BusyInterval, PracticeConfig

MONDAY = date(2026, 7, 20)


def _busy(*spans: tuple[int, int, int, int]) -> list[BusyInterval]:
    return [
        BusyInterval(
            start=datetime(2026, 7, 20, h1, m1),
            end=datetime(2026, 7, 20, h2, m2),
        )
        for h1, m1, h2, m2 in spans
    ]


def test_reference_example_ranking(config: PracticeConfig) -> None:
    """The worked example from the README, verified end to end.

    Booked: 08:30 and 09:45. Expected: slots adjacent-before first
    (08:15, 09:30), then adjacent-after (08:45, 10:00), then isolated.
    """
    busy = _busy((8, 30, 8, 45), (9, 45, 10, 0))
    ranked = rank_slots(MONDAY, busy, "premium", config)

    top = [s.start.strftime("%H:%M") for s in ranked[:4]]
    assert top == ["08:15", "09:30", "08:45", "10:00"]

    scores = {s.start.strftime("%H:%M"): s.score for s in ranked}
    assert scores["08:15"] == 10 and scores["09:30"] == 10
    assert scores["08:45"] == 8 and scores["10:00"] == 8
    assert scores["09:00"] == 0 and scores["09:15"] == 0


def test_sandwiched_gap_scores_highest(config: PracticeConfig) -> None:
    # Booked 08:30 and 09:00: the 08:45 hole touches both and fills a gap.
    busy = _busy((8, 30, 8, 45), (9, 0, 9, 15))
    ranked = rank_slots(MONDAY, busy, "premium", config)
    best = ranked[0]
    assert best.start.strftime("%H:%M") == "08:45"
    assert best.score == 18
    assert best.score_breakdown == {"adjacent_before": 10, "adjacent_after": 8}


def test_empty_day_offers_chronological_order(config: PracticeConfig) -> None:
    ranked = rank_slots(MONDAY, [], "premium", config)
    assert all(s.score == 0 for s in ranked)
    assert [s.start for s in ranked] == sorted(s.start for s in ranked)


def test_breakdown_always_sums_to_score(config: PracticeConfig) -> None:
    busy = _busy((8, 30, 8, 45), (9, 45, 10, 0), (12, 0, 13, 0))
    for slot in rank_slots(MONDAY, busy, "premium", config):
        assert sum(slot.score_breakdown.values()) == slot.score


def test_adjacency_counts_slots_the_client_cannot_book(config: PracticeConfig) -> None:
    # A 09:45 appointment makes 10:00 adjacent-after for a standard client,
    # even though 09:45 itself lies outside the standard booking window.
    busy = _busy((9, 45, 10, 0))
    ranked = rank_slots(MONDAY, busy, "standard", config)
    assert ranked[0].start.strftime("%H:%M") == "10:00"
    assert ranked[0].score_breakdown == {"adjacent_after": 8}
