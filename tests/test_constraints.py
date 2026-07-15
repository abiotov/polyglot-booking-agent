"""Stage 1: hard constraints. A slot that violates any of them is never offered."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from scheduling_engine import rank_slots
from scheduling_engine.models import BusyInterval, PracticeConfig

MONDAY = date(2026, 7, 20)
FRIDAY = date(2026, 7, 24)
SATURDAY = date(2026, 7, 25)


def _starts(slots) -> list[str]:
    return [s.start.strftime("%H:%M") for s in slots]


def test_closed_day_yields_no_slots(config: PracticeConfig) -> None:
    assert rank_slots(SATURDAY, [], "premium", config) == []


def test_occupied_slots_are_excluded(config: PracticeConfig) -> None:
    busy = [BusyInterval(start=datetime(2026, 7, 20, 8, 30), end=datetime(2026, 7, 20, 8, 45))]
    assert "08:30" not in _starts(rank_slots(MONDAY, busy, "premium", config))


def test_manual_block_excludes_like_an_appointment(config: PracticeConfig) -> None:
    block = BusyInterval(
        start=datetime(2026, 7, 20, 9, 0), end=datetime(2026, 7, 20, 12, 0), kind="block"
    )
    offered = _starts(rank_slots(MONDAY, [block], "premium", config))
    assert all(not ("09:00" <= s < "12:00") for s in offered)


def test_partial_overlap_excludes_the_slot(config: PracticeConfig) -> None:
    # An appointment covering 08:20-08:40 straddles two grid slots; both are gone.
    busy = [BusyInterval(start=datetime(2026, 7, 20, 8, 20), end=datetime(2026, 7, 20, 8, 40))]
    offered = _starts(rank_slots(MONDAY, busy, "premium", config))
    assert "08:15" not in offered and "08:30" not in offered


def test_client_windows_restrict_offers(config: PracticeConfig) -> None:
    # Standard clients may only book from 10:00.
    offered = _starts(rank_slots(MONDAY, [], "standard", config))
    assert offered and min(offered) >= "10:00"


def test_slots_never_cross_an_opening_boundary(config: PracticeConfig) -> None:
    # Friday has a break 10:00-11:00; nothing may be offered inside it.
    offered = _starts(rank_slots(FRIDAY, [], "premium", config))
    assert all(not ("10:00" <= s < "11:00") for s in offered)


def test_unknown_client_type_raises(config: PracticeConfig) -> None:
    with pytest.raises(ValueError, match="unknown client type"):
        rank_slots(MONDAY, [], "vip", config)
