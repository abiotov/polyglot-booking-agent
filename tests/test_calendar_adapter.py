"""Integration tests: the adapter against a live Radicale server.

A real Radicale application is served in-process (wsgiref on a free
port, temporary storage folder), so these tests exercise the actual
CalDAV protocol end to end, not a mock. In-process also lets us work
around a Radicale probe that crashes on Windows (see _patched_probe).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from wsgiref.simple_server import WSGIRequestHandler, make_server

import caldav
import pytest
import radicale
import radicale.config
import radicale.pathutils

from calendar_adapter import (
    CalDAVCalendar,
    EventNotFoundError,
    NotAgentEventError,
    SlotTakenError,
)

MONDAY = date(2026, 7, 20)


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@contextmanager
def _patched_probe() -> Iterator[None]:
    """Make Radicale's symlink probe survive Windows.

    radicale.pathutils.path_supports_symlink only catches
    PermissionError, but os.symlink on Windows without Developer Mode
    raises a plain OSError (WinError 1314), crashing storage startup.
    Answering "no symlink support" is the truthful behavior.
    """
    original = radicale.pathutils.path_supports_symlink

    def safe_probe(path: str) -> bool:
        try:
            return bool(original(path))
        except OSError:
            return False

    radicale.pathutils.path_supports_symlink = safe_probe
    try:
        yield
    finally:
        radicale.pathutils.path_supports_symlink = original


@pytest.fixture(scope="module")
def radicale_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    storage = tmp_path_factory.mktemp("radicale-storage")
    configuration = radicale.config.load()
    configuration.update(
        {
            "auth": {"type": "none"},
            "storage": {"filesystem_folder": str(storage)},
        },
        "test",
        privileged=True,
    )
    with _patched_probe():
        application = radicale.Application(configuration)
    server = make_server("127.0.0.1", 0, application, handler_class=_QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def calendar(radicale_url: str, request: pytest.FixtureRequest) -> CalDAVCalendar:
    # One fresh calendar per test keeps tests independent.
    return CalDAVCalendar(
        url=radicale_url,
        username="agent",
        password="agent",
        calendar_name=f"appointments-{request.node.name}",
        timezone="Africa/Porto-Novo",
    )


def test_empty_calendar_has_no_busy_intervals(calendar: CalDAVCalendar) -> None:
    assert calendar.busy_intervals(MONDAY) == []


def test_booked_appointment_becomes_a_busy_interval(calendar: CalDAVCalendar) -> None:
    booking = calendar.book(
        start=datetime(2026, 7, 20, 8, 15),
        end=datetime(2026, 7, 20, 8, 30),
        patient_name="Jean Kokou",
        patient_phone="+22997000000",
    )
    intervals = calendar.busy_intervals(MONDAY)
    assert len(intervals) == 1
    assert intervals[0].start == booking.start
    assert intervals[0].end == booking.end
    assert intervals[0].kind == "appointment"


def test_read_before_write_refuses_a_taken_slot(calendar: CalDAVCalendar) -> None:
    calendar.book(
        start=datetime(2026, 7, 20, 9, 0),
        end=datetime(2026, 7, 20, 9, 15),
        patient_name="First Caller",
        patient_phone="+22990000001",
    )
    with pytest.raises(SlotTakenError):
        calendar.book(
            start=datetime(2026, 7, 20, 9, 0),
            end=datetime(2026, 7, 20, 9, 15),
            patient_name="Second Caller",
            patient_phone="+22990000002",
        )


def test_partial_overlap_is_also_refused(calendar: CalDAVCalendar) -> None:
    calendar.book(
        start=datetime(2026, 7, 20, 10, 0),
        end=datetime(2026, 7, 20, 10, 30),
        patient_name="Long Appointment",
        patient_phone="+22990000003",
    )
    with pytest.raises(SlotTakenError):
        calendar.book(
            start=datetime(2026, 7, 20, 10, 15),
            end=datetime(2026, 7, 20, 10, 45),
            patient_name="Overlapper",
            patient_phone="+22990000004",
        )


def test_cancel_frees_the_slot(calendar: CalDAVCalendar) -> None:
    booking = calendar.book(
        start=datetime(2026, 7, 20, 11, 0),
        end=datetime(2026, 7, 20, 11, 15),
        patient_name="Cancelling Patient",
        patient_phone="+22990000005",
    )
    calendar.cancel(booking.uid)
    assert calendar.busy_intervals(MONDAY) == []


def test_cancel_unknown_uid_raises(calendar: CalDAVCalendar) -> None:
    with pytest.raises(EventNotFoundError):
        calendar.cancel("does-not-exist")


def test_agent_never_touches_manual_events(calendar: CalDAVCalendar, radicale_url: str) -> None:
    # The practitioner creates an event by hand (a second CalDAV client,
    # exactly like Thunderbird or an iPhone would).
    uid = _create_manual_event(
        radicale_url,
        calendar_name="appointments-test_agent_never_touches_manual_events",
        start=datetime(2026, 7, 20, 12, 0),
        end=datetime(2026, 7, 20, 12, 15),
    )
    # The agent sees it as busy but refuses to delete it.
    assert len(calendar.busy_intervals(MONDAY)) == 1
    with pytest.raises(NotAgentEventError):
        calendar.cancel(uid)


def test_reschedule_moves_the_appointment(calendar: CalDAVCalendar) -> None:
    booking = calendar.book(
        start=datetime(2026, 7, 20, 8, 0),
        end=datetime(2026, 7, 20, 8, 15),
        patient_name="Moving Patient",
        patient_phone="+22990000006",
    )
    moved = calendar.reschedule(
        booking.uid,
        new_start=datetime(2026, 7, 20, 13, 0),
        new_end=datetime(2026, 7, 20, 13, 15),
    )
    intervals = calendar.busy_intervals(MONDAY)
    assert len(intervals) == 1
    assert intervals[0].start == moved.start == datetime(2026, 7, 20, 13, 0)


def test_manual_all_day_event_blocks_the_day(calendar: CalDAVCalendar, radicale_url: str) -> None:
    _create_manual_event(
        radicale_url,
        calendar_name="appointments-test_manual_all_day_event_blocks_the_day",
        start=None,
        end=None,
        all_day=MONDAY,
    )
    intervals = calendar.busy_intervals(MONDAY)
    assert len(intervals) == 1
    assert intervals[0].start == datetime(2026, 7, 20, 0, 0)
    assert intervals[0].end == datetime(2026, 7, 21, 0, 0)


def _create_manual_event(
    url: str,
    calendar_name: str,
    start: datetime | None,
    end: datetime | None,
    all_day: date | None = None,
) -> str:
    """Simulate the practitioner adding an event from their own client."""
    client = caldav.DAVClient(url=url, username="agent", password="agent")
    cal = client.principal().calendar(name=calendar_name)
    uid = f"manual-{calendar_name}"
    if all_day is not None:
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTART;VALUE=DATE:{all_day:%Y%m%d}\r\n"
            f"DTEND;VALUE=DATE:{all_day.replace(day=all_day.day + 1):%Y%m%d}\r\n"
            "SUMMARY:Vacation\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
    else:
        assert start is not None and end is not None
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTART:{start:%Y%m%dT%H%M%S}\r\n"
            f"DTEND:{end:%Y%m%dT%H%M%S}\r\n"
            "SUMMARY:Manual appointment\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
    cal.save_event(ics)
    return uid
