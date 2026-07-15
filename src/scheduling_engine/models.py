"""Domain models for the scheduling engine.

The engine works in naive local time: every datetime is interpreted in the
practice timezone declared in the configuration. Timezone conversion is the
calendar adapter's job, not the engine's.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

WeekdayName = Literal[
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]

WEEKDAY_NAMES: tuple[WeekdayName, ...] = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


def _parse_window(value: Any) -> Any:
    """Accept the compact "HH:MM-HH:MM" string form used in YAML."""
    if isinstance(value, str):
        start_raw, sep, end_raw = value.partition("-")
        if not sep:
            raise ValueError(f"expected 'HH:MM-HH:MM', got {value!r}")
        return {"start": start_raw.strip(), "end": end_raw.strip()}
    return value


class TimeWindow(BaseModel):
    """A half-open daily interval [start, end)."""

    model_config = ConfigDict(frozen=True)

    start: time
    end: time

    @model_validator(mode="after")
    def _check_order(self) -> TimeWindow:
        if self.start >= self.end:
            raise ValueError(f"window start {self.start} must be before end {self.end}")
        return self

    def contains(self, start: time, end: time) -> bool:
        """True if [start, end) fits entirely inside this window.

        A slot ending exactly at midnight is represented by end == time.min
        and is only contained by a window that also ends at midnight; the
        engine never generates such slots, so the simple comparison holds.
        """
        return self.start <= start and end <= self.end


Window = Annotated[TimeWindow, BeforeValidator(_parse_window)]


class ScoringWeights(BaseModel):
    """Points awarded to a free slot for each occupied neighbor."""

    model_config = ConfigDict(frozen=True)

    adjacent_before: int = 10
    adjacent_after: int = 8


class ClientTypeConfig(BaseModel):
    """A bookable client category (e.g. premium, standard)."""

    model_config = ConfigDict(frozen=True)

    priority: int = Field(ge=1, description="1 is the highest priority")
    windows: tuple[Window, ...]
    escalation_contact: str | None = None


class VisitTypeConfig(BaseModel):
    """A visit category with per-language labels (e.g. {'fr': ..., 'en': ...})."""

    model_config = ConfigDict(frozen=True)

    labels: dict[str, str]


class SlotsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    duration_minutes: int = Field(default=15, gt=0, le=240)


class PracticeInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    timezone: str = "UTC"
    languages: tuple[str, ...] = ("fr", "en")


class PracticeConfig(BaseModel):
    """Everything the engine decides with. Nothing else is consulted."""

    model_config = ConfigDict(frozen=True)

    practice: PracticeInfo
    slots: SlotsConfig = SlotsConfig()
    opening_hours: dict[WeekdayName, tuple[Window, ...]]
    client_types: dict[str, ClientTypeConfig]
    visit_types: dict[str, VisitTypeConfig] = {}
    scoring: ScoringWeights = ScoringWeights()


class BusyInterval(BaseModel):
    """An occupied span of the calendar: an appointment or a manual block.

    Manual blocks behave exactly like appointments for availability, but are
    kept distinct so adapters and UIs can display them differently.
    """

    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime
    kind: Literal["appointment", "block"] = "appointment"

    @model_validator(mode="after")
    def _check_order(self) -> BusyInterval:
        if self.start >= self.end:
            raise ValueError(f"busy interval start {self.start} must be before end {self.end}")
        return self


class ScoredSlot(BaseModel):
    """A bookable slot with its explainable score.

    score_breakdown maps a reason to the points it contributed, e.g.
    {"adjacent_before": 10}. The total score is always the sum of the
    breakdown, so every ranking decision can be traced.
    """

    model_config = ConfigDict(frozen=True)

    slot_id: str
    start: datetime
    end: datetime
    score: int
    score_breakdown: dict[str, int]

    @model_validator(mode="after")
    def _check_consistency(self) -> ScoredSlot:
        if sum(self.score_breakdown.values()) != self.score:
            raise ValueError("score must equal the sum of score_breakdown")
        return self
