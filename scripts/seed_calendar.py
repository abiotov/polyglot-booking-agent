"""Seed the dev calendar with a realistic week.

    uv run python scripts/seed_calendar.py [--url http://127.0.0.1:5232]

Creates, for the current week (Monday onward):
- agent-booked appointments (tagged POLYGLOT-AGENT)
- a practitioner lunch block every day (tagged BLOCK, created manually,
  exactly like a block made from Thunderbird or a phone)

Run scripts/run_radicale.py first.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta

from caldav.davclient import DAVClient

from calendar_adapter import BLOCK_CATEGORY, CalDAVCalendar

APPOINTMENTS: list[tuple[int, time, str, str]] = [
    # (weekday offset, start, patient, phone)
    (0, time(8, 30), "Jean Kokou", "+22997000001"),
    (0, time(9, 45), "Awa Dossou", "+22997000002"),
    (1, time(8, 0), "Marc Adjovi", "+22997000003"),
    (1, time(10, 15), "Chantal Hounsou", "+22997000004"),
    (2, time(11, 0), "Rachid Salifou", "+22997000005"),
    (3, time(8, 45), "Grace Agbo", "+22997000006"),
]


def seed(url: str, calendar_name: str, timezone: str) -> None:
    monday = date.today() - timedelta(days=date.today().weekday())
    calendar = CalDAVCalendar(
        url=url,
        username="agent",
        password="agent",
        calendar_name=calendar_name,
        timezone=timezone,
    )

    for offset, start, name, phone in APPOINTMENTS:
        day = monday + timedelta(days=offset)
        begin = datetime.combine(day, start)
        booking = calendar.book(
            start=begin, end=begin + timedelta(minutes=15), patient_name=name, patient_phone=phone
        )
        print(f"booked   {booking.start:%a %H:%M}  {name}")

    _seed_manual_lunch_blocks(url, calendar_name, monday)
    print("done: agent appointments + manual lunch blocks for the week")


def _seed_manual_lunch_blocks(url: str, calendar_name: str, monday: date) -> None:
    """Blocks created outside the adapter, like the practitioner would."""
    client = DAVClient(url=url, username="agent", password="agent")
    cal = client.principal().calendar(name=calendar_name)
    for offset in range(5):
        day = monday + timedelta(days=offset)
        cal.save_event(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//seed//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:lunch-{day.isoformat()}\r\n"
            f"DTSTART:{day:%Y%m%d}T120000\r\n"
            f"DTEND:{day:%Y%m%d}T130000\r\n"
            "SUMMARY:Lunch (blocked)\r\n"
            f"CATEGORIES:{BLOCK_CATEGORY}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        print(f"blocked  {day:%a} 12:00-13:00  lunch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5232")
    parser.add_argument("--calendar", default="appointments")
    parser.add_argument("--timezone", default="Africa/Porto-Novo")
    args = parser.parse_args()
    seed(args.url, args.calendar, args.timezone)


if __name__ == "__main__":
    main()
