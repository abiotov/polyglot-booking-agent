"""Deterministic, explainable appointment slot ranking.

Public API:

    from scheduling_engine import load_config, rank_slots
    from scheduling_engine.models import BusyInterval, PracticeConfig, ScoredSlot
"""

from .config import load_config
from .engine import rank_slots
from .models import (
    BusyInterval,
    ClientTypeConfig,
    PracticeConfig,
    ScoredSlot,
    ScoringWeights,
    TimeWindow,
)

__all__ = [
    "BusyInterval",
    "ClientTypeConfig",
    "PracticeConfig",
    "ScoredSlot",
    "ScoringWeights",
    "TimeWindow",
    "load_config",
    "rank_slots",
]
