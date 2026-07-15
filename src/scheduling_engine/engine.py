"""Slot ranking: hard constraints, then compaction scoring.

rank_slots() is a pure function. Given the same calendar state, client type
and configuration it always returns the same ranking, which is what makes
the engine unit-testable and property-testable.

Stage 1 (hard constraints) eliminates slots: occupied, outside opening
hours, or outside the windows allowed for the client type.

Stage 2 (compaction scoring) ranks the survivors the way an experienced
receptionist would: a free slot earns points for each occupied neighbor,
so the schedule stays compact and gaps stay usable. Isolated slots score 0
and are offered last, in chronological order.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from .models import (
    WEEKDAY_NAMES,
    BusyInterval,
    PracticeConfig,
    ScoredSlot,
    TimeWindow,
)

__all__ = ["rank_slots"]


def rank_slots(
    day: date,
    busy: Sequence[BusyInterval],
    client_type: str,
    config: PracticeConfig,
) -> list[ScoredSlot]:
    """Return every bookable slot for `day`, best first.

    Ordering is deterministic: score descending, then start time ascending.
    Raises ValueError if `client_type` is not declared in the configuration.
    """
    client = config.client_types.get(client_type)
    if client is None:
        known = ", ".join(sorted(config.client_types))
        raise ValueError(f"unknown client type {client_type!r} (known: {known})")

    weekday = WEEKDAY_NAMES[day.weekday()]
    opening = config.opening_hours.get(weekday, ())
    duration = timedelta(minutes=config.slots.duration_minutes)

    ranked: list[ScoredSlot] = []
    for window in opening:
        ranked.extend(_rank_window(day, window, busy, client.windows, duration, config))

    ranked.sort(key=lambda s: (-s.score, s.start))
    return ranked


def _rank_window(
    day: date,
    window: TimeWindow,
    busy: Sequence[BusyInterval],
    client_windows: Sequence[TimeWindow],
    duration: timedelta,
    config: PracticeConfig,
) -> list[ScoredSlot]:
    """Grid one opening window into slots, then score the free ones.

    Adjacency is evaluated inside a single opening window: slots on either
    side of a lunch break or across days are not neighbors.
    """
    starts = _slot_grid(day, window, duration)
    occupied = [_overlaps_any(start, start + duration, busy) for start in starts]

    scored: list[ScoredSlot] = []
    for i, start in enumerate(starts):
        if occupied[i]:
            continue
        end = start + duration
        if not any(cw.contains(start.time(), end.time()) for cw in client_windows):
            continue

        breakdown: dict[str, int] = {}
        if i + 1 < len(starts) and occupied[i + 1]:
            breakdown["adjacent_before"] = config.scoring.adjacent_before
        if i > 0 and occupied[i - 1]:
            breakdown["adjacent_after"] = config.scoring.adjacent_after

        scored.append(
            ScoredSlot(
                slot_id=start.isoformat(timespec="minutes"),
                start=start,
                end=end,
                score=sum(breakdown.values()),
                score_breakdown=breakdown,
            )
        )
    return scored


def _slot_grid(day: date, window: TimeWindow, duration: timedelta) -> list[datetime]:
    """All slot start times fully contained in the window."""
    start = datetime.combine(day, window.start)
    boundary = datetime.combine(day, window.end)
    starts: list[datetime] = []
    while start + duration <= boundary:
        starts.append(start)
        start += duration
    return starts


def _overlaps_any(start: datetime, end: datetime, busy: Sequence[BusyInterval]) -> bool:
    """True if [start, end) intersects any busy interval."""
    return any(b.start < end and b.end > start for b in busy)
