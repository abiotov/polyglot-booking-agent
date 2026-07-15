"""CalDAV calendar adapter.

Translates between the scheduling engine's view (naive practice-local
BusyInterval) and any CalDAV server (Radicale in development, iCloud or
Google in production). All timezone conversion happens here; the engine
never sees an aware datetime.

Ownership rule: the adapter tags every event it creates with the
AGENT_CATEGORY marker and refuses to modify or delete anything else.
Manual events created by the practitioner are read-only facts.

Concurrency note: CalDAV has no transactions. book() re-reads the target
span immediately before writing (read-before-write), which shrinks the
race window to milliseconds; the residual race is inherent to the
protocol and acceptable for a single-practice calendar.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from caldav.davclient import DAVClient
from caldav.lib.error import NotFoundError
from icalendar import Calendar as IcsCalendar
from icalendar import Event as IcsEvent
from pydantic import BaseModel, ConfigDict

from scheduling_engine.models import BusyInterval

from .errors import EventNotFoundError, NotAgentEventError, SlotTakenError

__all__ = ["AGENT_CATEGORY", "BLOCK_CATEGORY", "Booking", "CalDAVCalendar"]

AGENT_CATEGORY = "POLYGLOT-AGENT"
BLOCK_CATEGORY = "BLOCK"


class Booking(BaseModel):
    """An appointment created by the agent."""

    model_config = ConfigDict(frozen=True)

    uid: str
    start: datetime
    end: datetime
    patient_name: str
    patient_phone: str


class CalDAVCalendar:
    """One practice calendar behind a CalDAV endpoint.

    All datetimes crossing this API are naive and interpreted in the
    practice timezone given at construction.
    """

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        calendar_name: str = "appointments",
        timezone: str = "UTC",
    ) -> None:
        self._tz = ZoneInfo(timezone)
        self._client = DAVClient(url=url, username=username, password=password)
        principal = self._client.principal()
        try:
            self._calendar = principal.calendar(name=calendar_name)
        except NotFoundError:
            self._calendar = principal.make_calendar(name=calendar_name)

    # ------------------------------------------------------------------ reads

    def busy_intervals(self, day: date) -> list[BusyInterval]:
        """Every occupied span on `day`, in naive practice-local time.

        Includes appointments and manual blocks alike; all-day events
        (vacations) block the whole day. This is the exact input shape
        rank_slots() expects.
        """
        day_start = datetime.combine(day, time.min, tzinfo=self._tz)
        day_end = day_start + timedelta(days=1)
        intervals: list[BusyInterval] = []
        for component in self._search_components(day_start, day_end):
            interval = self._to_busy_interval(component)
            if interval is not None:
                intervals.append(interval)
        return sorted(intervals, key=lambda i: i.start)

    # ----------------------------------------------------------------- writes

    def book(
        self,
        start: datetime,
        end: datetime,
        patient_name: str,
        patient_phone: str,
    ) -> Booking:
        """Create an appointment, refusing if the span is no longer free.

        Read-before-write: the span is re-checked against the live
        calendar in the same call. Raises SlotTakenError on conflict.
        """
        conflicts = [
            b for b in self.busy_intervals(start.date()) if b.start < end and b.end > start
        ]
        if conflicts:
            raise SlotTakenError(
                f"span {start:%Y-%m-%d %H:%M}-{end:%H:%M} was taken meanwhile"
            )

        booking = Booking(
            uid=str(uuid.uuid4()),
            start=start,
            end=end,
            patient_name=patient_name,
            patient_phone=patient_phone,
        )
        self._calendar.save_event(self._to_ics(booking))
        return booking

    def cancel(self, uid: str) -> None:
        """Delete an agent-created appointment.

        Raises EventNotFoundError if the UID does not exist and
        NotAgentEventError if the event was created by hand: the agent
        never touches the practitioner's own events.
        """
        event = self._event_by_uid(uid)
        if not self._is_agent_event(event.icalendar_component):
            raise NotAgentEventError(f"event {uid} was not created by the agent")
        event.delete()

    def reschedule(self, uid: str, new_start: datetime, new_end: datetime) -> Booking:
        """Move an agent-created appointment to a new, verified-free span."""
        event = self._event_by_uid(uid)
        component = event.icalendar_component
        if not self._is_agent_event(component):
            raise NotAgentEventError(f"event {uid} was not created by the agent")

        rebooked = self.book(
            start=new_start,
            end=new_end,
            patient_name=str(component.get("SUMMARY", "")),
            patient_phone=str(component.get("X-POLYGLOT-PHONE", "")),
        )
        event.delete()
        return rebooked

    # -------------------------------------------------------------- internals

    def _search_components(self, start: datetime, end: datetime) -> list[Any]:
        results = self._calendar.search(start=start, end=end, event=True)
        return [r.icalendar_component for r in results]

    def _event_by_uid(self, uid: str) -> Any:
        """Linear scan by UID.

        O(n) over the calendar is fine for a single practice (hundreds of
        events); revisit with a UID search filter if that assumption breaks.
        """
        for event in self._calendar.events():
            if str(event.icalendar_component.get("UID", "")) == uid:
                return event
        raise EventNotFoundError(f"no event with uid {uid}")

    @staticmethod
    def _is_agent_event(component: Any) -> bool:
        return AGENT_CATEGORY in _categories(component)

    def _to_busy_interval(self, component: Any) -> BusyInterval | None:
        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")
        if dtstart is None or dtend is None:
            return None
        kind: Literal["appointment", "block"] = (
            "block" if BLOCK_CATEGORY in _categories(component) else "appointment"
        )
        return BusyInterval(
            start=self._to_local(dtstart.dt),
            end=self._to_local(dtend.dt),
            kind=kind,
        )

    def _to_local(self, value: datetime | date) -> datetime:
        """Normalize any iCalendar time value to naive practice-local."""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value  # floating time: already practice-local
            return value.astimezone(self._tz).replace(tzinfo=None)
        # All-day value (a bare date): midnight local.
        return datetime.combine(value, time.min)

    def _to_ics(self, booking: Booking) -> str:
        event = IcsEvent()
        event.add("uid", booking.uid)
        event.add("dtstart", booking.start.replace(tzinfo=self._tz))
        event.add("dtend", booking.end.replace(tzinfo=self._tz))
        event.add("summary", booking.patient_name)
        event.add("categories", [AGENT_CATEGORY])
        event["X-POLYGLOT-PHONE"] = booking.patient_phone

        calendar = IcsCalendar()
        calendar.add("prodid", "-//polyglot-booking-agent//EN")
        calendar.add("version", "2.0")
        calendar.add_component(event)
        return calendar.to_ical().decode()


def _categories(component: Any) -> set[str]:
    """CATEGORIES as a plain set of strings, whatever icalendar parsed it into."""
    raw = component.get("CATEGORIES")
    if raw is None:
        return set()
    items = raw if isinstance(raw, list) else [raw]
    names: set[str] = set()
    for item in items:
        cats = getattr(item, "cats", None)
        if cats is not None:
            names.update(str(c) for c in cats)
        else:
            names.add(str(item))
    return names
