"""Calendar adapter exceptions.

Every error the agent layer needs to react to conversationally has its
own type, so the tool layer can map exceptions to user-facing messages
without string matching.
"""

from __future__ import annotations


class CalendarError(Exception):
    """Base class for calendar adapter failures."""


class SlotTakenError(CalendarError):
    """The slot was occupied at write time (read-before-write refusal).

    Typical cause: the practitioner booked or blocked the slot from
    another device while the caller was on the line. The agent should
    re-rank and re-offer.
    """


class EventNotFoundError(CalendarError):
    """No event with the given UID exists in the calendar."""


class NotAgentEventError(CalendarError):
    """The event exists but was not created by this agent.

    The agent must never modify or delete events the practitioner
    created by hand.
    """
