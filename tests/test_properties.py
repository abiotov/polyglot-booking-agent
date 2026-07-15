"""Property-based tests: invariants that hold for any calendar state.

Hypothesis generates random busy patterns; each property below must hold
for every one of them. This is the guarantee a fixed set of examples
cannot give.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from scheduling_engine import rank_slots
from scheduling_engine.models import BusyInterval, PracticeConfig

from .conftest import REFERENCE_CONFIG

MONDAY = date(2026, 7, 20)
DAY_START = datetime(2026, 7, 20, 8, 0)
CONFIG = PracticeConfig.model_validate(REFERENCE_CONFIG)


@st.composite
def busy_patterns(draw: st.DrawFn) -> list[BusyInterval]:
    """Random appointments on the Monday grid (08:00-14:00, 15-minute slots)."""
    n = draw(st.integers(min_value=0, max_value=12))
    intervals: list[BusyInterval] = []
    for _ in range(n):
        slot_index = draw(st.integers(min_value=0, max_value=23))
        length = draw(st.integers(min_value=1, max_value=3))
        start = DAY_START + timedelta(minutes=15 * slot_index)
        end = min(start + timedelta(minutes=15 * length), datetime(2026, 7, 20, 14, 0))
        intervals.append(BusyInterval(start=start, end=end))
    return intervals


@settings(max_examples=200)
@given(busy=busy_patterns())
def test_offered_slots_are_always_free(busy: list[BusyInterval]) -> None:
    for slot in rank_slots(MONDAY, busy, "premium", CONFIG):
        for interval in busy:
            assert not (interval.start < slot.end and interval.end > slot.start)


@settings(max_examples=200)
@given(busy=busy_patterns())
def test_offered_slots_stay_inside_opening_hours(busy: list[BusyInterval]) -> None:
    for slot in rank_slots(MONDAY, busy, "premium", CONFIG):
        assert slot.start >= datetime(2026, 7, 20, 8, 0)
        assert slot.end <= datetime(2026, 7, 20, 14, 0)
        assert (slot.start - DAY_START) % timedelta(minutes=15) == timedelta(0)


@settings(max_examples=200)
@given(busy=busy_patterns())
def test_no_avoidable_fragmentation(busy: list[BusyInterval]) -> None:
    """If any adjacent slot exists, an isolated slot is never ranked first.

    This is the compaction guarantee: the engine only proposes a
    fragmenting slot when no better option exists.
    """
    ranked = rank_slots(MONDAY, busy, "premium", CONFIG)
    if any(s.score > 0 for s in ranked):
        assert ranked[0].score > 0


@settings(max_examples=100)
@given(busy=busy_patterns())
def test_ranking_is_deterministic(busy: list[BusyInterval]) -> None:
    first = rank_slots(MONDAY, busy, "premium", CONFIG)
    second = rank_slots(MONDAY, busy, "premium", CONFIG)
    assert first == second


@settings(max_examples=200)
@given(busy=busy_patterns())
def test_scores_are_sorted_and_traceable(busy: list[BusyInterval]) -> None:
    ranked = rank_slots(MONDAY, busy, "premium", CONFIG)
    scores = [s.score for s in ranked]
    assert scores == sorted(scores, reverse=True)
    for slot in ranked:
        assert sum(slot.score_breakdown.values()) == slot.score
