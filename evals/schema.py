"""Scenario schema: an eval case is a verifiable contract.

The `expected` block is written in mechanically checkable terms (an
event exists with this exact identity, inside this window), never in
vibes ("the agent should be helpful"). That is what makes campaigns
reproducible and regressions unambiguous.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Goal = Literal["book", "cancel", "reschedule", "ask_hours", "impossible"]
Outcome = Literal["booked", "cancelled", "rescheduled", "none", "escalated"]


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    phone: str


class PersonaSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    goal: Goal
    script_hint: str
    identity: Identity
    client_type: str = "standard"
    visit_type: str = "first_visit"
    languages: tuple[str, ...] = ("fr",)


class SeedEvent(BaseModel):
    """Initial calendar state, relative to the scenario's target day."""

    model_config = ConfigDict(frozen=True)

    day_offset: int = 0
    start: str  # "HH:MM"
    end: str | None = None  # defaults to start + slot duration
    kind: Literal["appointment", "block"] = "appointment"
    owner: Literal["manual", "agent"] = "manual"
    # agent-owned seeds (something the caller booked earlier) carry an
    # identity so cancel/reschedule scenarios can find them by phone.
    identity: Identity | None = None


class Expected(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    identity_exact: bool = True
    window: str | None = None  # client_type whose windows must contain the slot
    language_follow: bool = True


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    description: str = ""
    persona: PersonaSpec
    calendar_seed: tuple[SeedEvent, ...] = ()
    expected: Expected
    max_turns: int = Field(default=14, ge=2, le=30)


def load_scenarios(directory: str | Path) -> list[Scenario]:
    """Every .yaml file under `directory` is one scenario."""
    scenarios = [
        Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(Path(directory).glob("*.yaml"))
    ]
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate scenario ids in {directory}")
    return scenarios
