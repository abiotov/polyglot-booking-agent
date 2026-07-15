"""CalDAV calendar adapter: the engine's window onto the real calendar.

Public API:

    from calendar_adapter import CalDAVCalendar, Booking
    from calendar_adapter.errors import SlotTakenError, NotAgentEventError
"""

from .adapter import (
    AGENT_CATEGORY,
    BLOCK_CATEGORY,
    Booking,
    CalDAVCalendar,
    phones_match,
)
from .errors import (
    CalendarError,
    EventNotFoundError,
    NotAgentEventError,
    SlotTakenError,
)

__all__ = [
    "AGENT_CATEGORY",
    "BLOCK_CATEGORY",
    "Booking",
    "CalDAVCalendar",
    "CalendarError",
    "EventNotFoundError",
    "NotAgentEventError",
    "SlotTakenError",
    "phones_match",
]
