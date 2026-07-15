"""The booking toolbox: the only bridge between the LLM and the world.

Every tool validates its arguments against the practice configuration
and returns a JSON string (results and errors alike), so the model
always has something well-formed to reason about. Two invariants are
enforced here, not in the prompt:

- No availability without qualification: get_ranked_slots refuses until
  qualify() has been called with values from the configuration.
- No booking outside the offer: book/reschedule only accept a slot_id
  returned by the latest get_ranked_slots call. The LLM cannot invent
  or negotiate a slot; the passage does not exist.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from calendar_adapter import CalDAVCalendar, SlotTakenError
from calendar_adapter.errors import CalendarError
from scheduling_engine import rank_slots
from scheduling_engine.models import PracticeConfig, ScoredSlot

from .types import ToolSpec

MAX_OFFERED_SLOTS = 5


class BookingToolbox:
    """Per-conversation tool state and dispatch."""

    def __init__(self, calendar: CalDAVCalendar, config: PracticeConfig) -> None:
        self._calendar = calendar
        self._config = config
        self._client_type: str | None = None
        self._visit_type: str | None = None
        self._offered: dict[str, ScoredSlot] = {}

    # ---------------------------------------------------------------- specs

    def specs(self) -> list[ToolSpec]:
        client_types = sorted(self._config.client_types)
        visit_types = sorted(self._config.visit_types)
        return [
            ToolSpec(
                name="qualify",
                description=(
                    "Record the caller's category. Must be called before any "
                    "availability can be checked."
                ),
                parameters=_strict_object(
                    client_type={"type": "string", "enum": client_types},
                    visit_type={"type": "string", "enum": visit_types},
                ),
            ),
            ToolSpec(
                name="get_ranked_slots",
                description=(
                    "List bookable slots for one day, best first. The ranking "
                    "already applies every practice rule; offer slots in the "
                    "returned order and never mention a slot not in the list."
                ),
                parameters=_strict_object(
                    day={"type": "string", "description": "ISO date, e.g. 2026-07-20"},
                ),
            ),
            ToolSpec(
                name="book",
                description=(
                    "Book one slot returned by get_ranked_slots, after the "
                    "caller confirmed their name and phone number."
                ),
                parameters=_strict_object(
                    slot_id={"type": "string"},
                    patient_name={"type": "string"},
                    patient_phone={"type": "string"},
                ),
            ),
            ToolSpec(
                name="reschedule",
                description=(
                    "Move an existing agent-created booking to a new slot "
                    "returned by get_ranked_slots."
                ),
                parameters=_strict_object(
                    booking_uid={"type": "string"},
                    new_slot_id={"type": "string"},
                ),
            ),
            ToolSpec(
                name="cancel",
                description="Cancel an agent-created booking by its uid.",
                parameters=_strict_object(
                    booking_uid={"type": "string"},
                ),
            ),
        ]

    # -------------------------------------------------------------- dispatch

    def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        handlers = {
            "qualify": self._qualify,
            "get_ranked_slots": self._get_ranked_slots,
            "book": self._book,
            "reschedule": self._reschedule,
            "cancel": self._cancel,
        }
        handler = handlers.get(name)
        if handler is None:
            return _error(f"unknown tool {name!r}")
        try:
            return handler(arguments)
        except CalendarError as exc:
            return _error(str(exc))
        except (KeyError, ValueError, TypeError) as exc:
            return _error(f"invalid arguments for {name}: {exc}")

    # -------------------------------------------------------------- handlers

    def _qualify(self, args: dict[str, Any]) -> str:
        client_type = str(args["client_type"])
        visit_type = str(args["visit_type"])
        if client_type not in self._config.client_types:
            return _error(f"unknown client_type {client_type!r}")
        if visit_type not in self._config.visit_types:
            return _error(f"unknown visit_type {visit_type!r}")
        self._client_type = client_type
        self._visit_type = visit_type
        return json.dumps({"ok": True, "client_type": client_type, "visit_type": visit_type})

    def _get_ranked_slots(self, args: dict[str, Any]) -> str:
        if self._client_type is None:
            return _error("caller is not qualified yet; call qualify first")
        day = date.fromisoformat(str(args["day"]))
        busy = self._calendar.busy_intervals(day)
        ranked = rank_slots(day, busy, self._client_type, self._config)[:MAX_OFFERED_SLOTS]
        self._offered = {slot.slot_id: slot for slot in ranked}
        if not ranked:
            escalation = self._config.client_types[self._client_type].escalation_contact
            payload: dict[str, Any] = {"slots": [], "message": "no slot available that day"}
            if escalation:
                payload["escalation_contact"] = escalation
            return json.dumps(payload)
        return json.dumps(
            {
                "slots": [
                    {
                        "slot_id": slot.slot_id,
                        "start": slot.start.strftime("%A %H:%M"),
                        "rank": rank + 1,
                    }
                    for rank, slot in enumerate(ranked)
                ]
            }
        )

    def _book(self, args: dict[str, Any]) -> str:
        slot = self._offered.get(str(args["slot_id"]))
        if slot is None:
            return _error(
                "slot_id was not part of the last get_ranked_slots result; "
                "call get_ranked_slots again and offer only returned slots"
            )
        try:
            booking = self._calendar.book(
                start=slot.start,
                end=slot.end,
                patient_name=str(args["patient_name"]),
                patient_phone=str(args["patient_phone"]),
            )
        except SlotTakenError:
            self._offered.pop(slot.slot_id, None)
            return _error(
                "that slot was just taken (calendar changed); "
                "call get_ranked_slots again and offer a new slot"
            )
        return json.dumps(
            {
                "booked": True,
                "booking_uid": booking.uid,
                "start": booking.start.isoformat(timespec="minutes"),
                "patient_name": booking.patient_name,
            }
        )

    def _reschedule(self, args: dict[str, Any]) -> str:
        slot = self._offered.get(str(args["new_slot_id"]))
        if slot is None:
            return _error(
                "new_slot_id was not part of the last get_ranked_slots result; "
                "call get_ranked_slots again first"
            )
        booking = self._calendar.reschedule(
            str(args["booking_uid"]), new_start=slot.start, new_end=slot.end
        )
        return json.dumps(
            {
                "rescheduled": True,
                "booking_uid": booking.uid,
                "start": booking.start.isoformat(timespec="minutes"),
            }
        )

    def _cancel(self, args: dict[str, Any]) -> str:
        self._calendar.cancel(str(args["booking_uid"]))
        return json.dumps({"cancelled": True})


def _strict_object(**properties: dict[str, Any]) -> dict[str, Any]:
    """A strict JSON Schema object: every property required, nothing extra."""
    return {
        "type": "object",
        "properties": dict(properties),
        "required": sorted(properties),
        "additionalProperties": False,
    }


def _error(message: str) -> str:
    return json.dumps({"error": message})
