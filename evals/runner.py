"""Run one scenario: a fresh world, two players, full capture.

Everything real, nothing mocked: the agent under test is the production
BookingAgent with its toolbox against a live Radicale calendar seeded
per scenario. The runner captures the transcript, the tool trace and
the final calendar state; verdicts are computed elsewhere (checks.py).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent import BookingAgent, BookingToolbox, build_system_prompt
from agent.providers.base import LLMProvider
from calendar_adapter import BLOCK_CATEGORY, Booking, CalDAVCalendar
from calendar_adapter.adapter import DAVClient
from scheduling_engine.models import BusyInterval, PracticeConfig

from .persona import END_MARKER, SimulatedPatient
from .schema import Scenario


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    arguments: dict[str, Any]
    result: str


class Exchange(BaseModel):
    model_config = ConfigDict(frozen=True)

    speaker: str  # "patient" | "agent"
    text: str
    language: str | None = None


class ConversationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    transcript: tuple[Exchange, ...]
    tool_trace: tuple[ToolCallRecord, ...]
    final_bookings: tuple[Booking, ...]  # agent-owned, whole horizon
    final_busy: tuple[BusyInterval, ...]  # target day, all kinds
    target_day: date
    turns: int
    ended_reason: str  # "goal" | "max_turns" | "error:<...>"


class RecordingToolbox(BookingToolbox):
    """The production toolbox, with a flight recorder on dispatch."""

    def __init__(self, calendar: CalDAVCalendar, config: PracticeConfig) -> None:
        super().__init__(calendar, config)
        self.records: list[ToolCallRecord] = []

    def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        result = super().dispatch(name, arguments)
        self.records.append(
            ToolCallRecord(name=name, arguments=dict(arguments), result=result)
        )
        return result


def next_monday(today: date | None = None) -> date:
    base = today or date.today()
    return base + timedelta(days=(7 - base.weekday()) % 7 or 7)


def run_scenario(
    scenario: Scenario,
    agent_provider: LLMProvider,
    persona_provider: LLMProvider,
    radicale_url: str,
    config: PracticeConfig,
) -> ConversationResult:
    target_day = next_monday()
    calendar = CalDAVCalendar(
        url=radicale_url,
        username="agent",
        password="agent",
        calendar_name=f"eval-{scenario.id}-{uuid.uuid4().hex[:6]}",
        timezone=config.practice.timezone,
    )
    _seed(calendar, scenario, target_day, config, radicale_url)

    toolbox = RecordingToolbox(calendar, config)
    agent = BookingAgent(agent_provider, toolbox, build_system_prompt(config))
    patient = SimulatedPatient(scenario.persona, persona_provider, target_day)

    transcript: list[Exchange] = []
    ended_reason = "max_turns"
    turns = 0
    text, language = patient.reply(None)
    try:
        while turns < scenario.max_turns:
            if text == END_MARKER:
                ended_reason = "goal"
                break
            transcript.append(Exchange(speaker="patient", text=text, language=language))
            reply = agent.run_turn(text, language=language)
            transcript.append(Exchange(speaker="agent", text=reply))
            turns += 1
            text, language = patient.reply(reply)
    except Exception as exc:  # noqa: BLE001 - a failing scenario must not kill the campaign
        ended_reason = f"error:{type(exc).__name__}: {exc}"

    return ConversationResult(
        scenario_id=scenario.id,
        transcript=tuple(transcript),
        tool_trace=tuple(toolbox.records),
        final_bookings=tuple(calendar.find_bookings(start=target_day - timedelta(days=30))),
        final_busy=tuple(calendar.busy_intervals(target_day)),
        target_day=target_day,
        turns=turns,
        ended_reason=ended_reason,
    )


def _seed(
    calendar: CalDAVCalendar,
    scenario: Scenario,
    target_day: date,
    config: PracticeConfig,
    radicale_url: str,
) -> None:
    """Materialize the scenario's initial calendar state."""
    slot = timedelta(minutes=config.slots.duration_minutes)
    for event in scenario.calendar_seed:
        day = target_day + timedelta(days=event.day_offset)
        start = datetime.combine(day, time.fromisoformat(event.start))
        end = (
            datetime.combine(day, time.fromisoformat(event.end))
            if event.end
            else start + slot
        )
        if event.owner == "agent":
            identity = event.identity or scenario.persona.identity
            calendar.book(
                start=start,
                end=end,
                patient_name=identity.name,
                patient_phone=identity.phone,
            )
        else:
            _manual_event(radicale_url, calendar, start, end, event.kind)


def _manual_event(
    radicale_url: str,
    calendar: CalDAVCalendar,
    start: datetime,
    end: datetime,
    kind: str,
) -> None:
    """An event the practitioner created by hand (not agent-owned)."""
    client = DAVClient(url=radicale_url, username="agent", password="agent")
    name = calendar._calendar.name  # noqa: SLF001 - eval-only shortcut
    cal = client.principal().calendar(name=name)
    categories = f"CATEGORIES:{BLOCK_CATEGORY}\r\n" if kind == "block" else ""
    cal.save_event(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//evals//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:seed-{uuid.uuid4().hex[:10]}\r\n"
        f"DTSTART:{start:%Y%m%dT%H%M%S}\r\n"
        f"DTEND:{end:%Y%m%dT%H%M%S}\r\n"
        f"SUMMARY:{'Blocked' if kind == 'block' else 'Manual appointment'}\r\n"
        f"{categories}"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
