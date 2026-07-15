"""Deterministic verdicts: code, not vibes.

Two evidence sources, per design decision 8: the final calendar state
(did the world end up as the scenario's contract demands?) and the tool
trace (did the agent follow the protocol the architecture enforces?).
An LLM judge (judge.py) covers only what code cannot; these checks are
the pass/fail that gates a campaign.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from calendar_adapter import Booking, phones_match
from scheduling_engine.models import PracticeConfig
from speech.langdetect import detect_language

from .runner import ConversationResult
from .schema import Scenario


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    passed: bool
    detail: str = ""


def run_checks(
    scenario: Scenario,
    result: ConversationResult,
    config: PracticeConfig,
) -> list[CheckResult]:
    checks = [
        _check_no_error(result),
        _check_outcome(scenario, result, config),
        _check_qualify_before_ranking(result),
        _check_booked_only_offered_slots(result),
        _check_no_hallucinated_times(result),
    ]
    if scenario.expected.language_follow:
        checks.append(_check_language_follow(result))
    return checks


# ------------------------------------------------------------------ outcome


def _check_no_error(result: ConversationResult) -> CheckResult:
    passed = not result.ended_reason.startswith("error:")
    return CheckResult(name="no-runtime-error", passed=passed, detail=result.ended_reason)


def _check_outcome(
    scenario: Scenario, result: ConversationResult, config: PracticeConfig
) -> CheckResult:
    created, remaining_seeds = _split_bookings(scenario, result)
    expected = scenario.expected
    identity = scenario.persona.identity

    if expected.outcome == "booked":
        if len(created) != 1:
            return CheckResult(
                name="outcome",
                passed=False,
                detail=f"expected exactly 1 new booking, found {len(created)}",
            )
        booking = created[0]
        if booking.start.date() != result.target_day:
            return CheckResult(
                name="outcome",
                passed=False,
                detail=f"booked on {booking.start.date()}, expected {result.target_day}",
            )
        if expected.identity_exact and not _identity_matches(
            booking, identity.name, identity.phone
        ):
            return CheckResult(
                name="outcome",
                passed=False,
                detail=f"identity mismatch: got ({booking.patient_name!r}, "
                f"{booking.patient_phone!r}), expected ({identity.name!r}, {identity.phone!r})",
            )
        if expected.window and not _in_window(booking, expected.window, config):
            return CheckResult(
                name="outcome",
                passed=False,
                detail=f"slot {booking.start:%H:%M} outside the {expected.window} windows",
            )
        return CheckResult(name="outcome", passed=True, detail=f"booked {booking.start:%H:%M}")

    if expected.outcome == "cancelled":
        seeded_agent = [s for s in scenario.calendar_seed if s.owner == "agent"]
        passed = not remaining_seeds and not created and bool(seeded_agent)
        return CheckResult(
            name="outcome",
            passed=passed,
            detail="seed still present or new booking created" if not passed else "cancelled",
        )

    if expected.outcome == "rescheduled":
        passed = len(created) == 1 and not remaining_seeds
        detail = "" if passed else (
            f"created={len(created)}, original seed still present={bool(remaining_seeds)}"
        )
        if passed and expected.identity_exact:
            booking = created[0]
            if not _identity_matches(booking, identity.name, identity.phone):
                return CheckResult(name="outcome", passed=False, detail="identity mismatch")
        return CheckResult(name="outcome", passed=passed, detail=detail)

    if expected.outcome == "escalated":
        if created:
            return CheckResult(
                name="outcome",
                passed=False,
                detail=f"{len(created)} booking(s) created despite full day",
            )
        contact = config.client_types[scenario.persona.client_type].escalation_contact
        if contact and not _contact_mentioned(contact, result):
            return CheckResult(
                name="outcome",
                passed=False,
                detail=f"escalation contact {contact} never given to the caller",
            )
        return CheckResult(name="outcome", passed=True, detail="escalated")

    # "none": the calendar must be untouched.
    passed = not created
    return CheckResult(
        name="outcome",
        passed=passed,
        detail="" if passed else f"{len(created)} unexpected booking(s) created",
    )


def _contact_mentioned(contact: str, result: ConversationResult) -> bool:
    wanted = _normalize_phone(contact)
    for exchange in result.transcript:
        if exchange.speaker != "agent":
            continue
        digits = "".join(ch for ch in exchange.text if ch.isdigit())
        if wanted and wanted in digits:
            return True
    return False


def _split_bookings(
    scenario: Scenario, result: ConversationResult
) -> tuple[list[Booking], list[Booking]]:
    """New bookings vs still-present agent-owned seeds."""
    seed_phones = {
        _normalize_phone((seed.identity or scenario.persona.identity).phone)
        for seed in scenario.calendar_seed
        if seed.owner == "agent"
    }
    seed_starts = {
        seed.start for seed in scenario.calendar_seed if seed.owner == "agent"
    }
    created: list[Booking] = []
    remaining_seeds: list[Booking] = []
    for booking in result.final_bookings:
        if (
            booking.start.strftime("%H:%M") in seed_starts
            and _normalize_phone(booking.patient_phone) in seed_phones
        ):
            remaining_seeds.append(booking)
        else:
            created.append(booking)
    return created, remaining_seeds


def _identity_matches(booking: Booking, name: str, phone: str) -> bool:
    same_name = " ".join(booking.patient_name.split()).casefold() == " ".join(
        name.split()
    ).casefold()
    return same_name and phones_match(booking.patient_phone, phone)


def _normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    # "00229..." and "+229..." are the same number.
    return digits[2:] if digits.startswith("00") else digits


def _in_window(booking: Booking, client_type: str, config: PracticeConfig) -> bool:
    windows = config.client_types[client_type].windows
    return any(w.contains(booking.start.time(), booking.end.time()) for w in windows)


# ------------------------------------------------------------- tool protocol


def _check_qualify_before_ranking(result: ConversationResult) -> CheckResult:
    """No SUCCESSFUL ranking before qualification.

    A ranking attempt the toolbox refused ("not qualified yet") is the
    guard doing its job, not a violation: what must never happen is
    slots actually reaching the model without qualification.
    """
    qualified_seen = False
    for record in result.tool_trace:
        if record.name == "qualify" and '"ok": true' in record.result:
            qualified_seen = True
        elif (
            record.name == "get_ranked_slots"
            and "error" not in record.result
            and not qualified_seen
        ):
            return CheckResult(
                name="qualify-before-ranking",
                passed=False,
                detail="slots served before any successful qualify",
            )
    return CheckResult(name="qualify-before-ranking", passed=True)


def _check_booked_only_offered_slots(result: ConversationResult) -> CheckResult:
    offered: set[str] = set()
    for record in result.tool_trace:
        if record.name == "get_ranked_slots":
            offered = {s["slot_id"] for s in _slots_of(record.result)}
        elif record.name == "book":
            slot_id = str(record.arguments.get("slot_id", ""))
            if slot_id not in offered and "error" not in record.result:
                return CheckResult(
                    name="book-only-offered",
                    passed=False,
                    detail=f"booked {slot_id!r} which was never offered",
                )
    return CheckResult(name="book-only-offered", passed=True)


def _slots_of(result_json: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(result_json)
    except json.JSONDecodeError:
        return []
    slots = payload.get("slots", [])
    return slots if isinstance(slots, list) else []


_TIME_PATTERN = re.compile(r"\b(\d{1,2})\s*[:hH]\s*(\d{2})\b")


def _check_no_hallucinated_times(result: ConversationResult) -> CheckResult:
    """Every time the agent utters must come from a tool result.

    The allowed set is every HH:MM-looking value found in any tool
    result (offered slots, found bookings, confirmations): the agent
    may repeat what its tools said, nothing else.
    """
    allowed = {
        _canonical(h, m)
        for record in result.tool_trace
        for h, m in _TIME_PATTERN.findall(record.result)
    }
    # Echoing a time the caller just said ("10h? no, that one is not
    # available") is conversation, not invention.
    allowed.update(
        _canonical(h, m)
        for exchange in result.transcript
        if exchange.speaker == "patient"
        for h, m in _TIME_PATTERN.findall(exchange.text)
    )
    for exchange in result.transcript:
        if exchange.speaker != "agent":
            continue
        for h, m in _TIME_PATTERN.findall(exchange.text):
            if _canonical(h, m) not in allowed:
                return CheckResult(
                    name="no-hallucinated-times",
                    passed=False,
                    detail=f"agent mentioned {h}:{m}, absent from every tool result",
                )
    return CheckResult(name="no-hallucinated-times", passed=True)


def _canonical(hours: str, minutes: str) -> str:
    return f"{int(hours):02d}:{minutes}"


# ------------------------------------------------------------------ language


def _check_language_follow(result: ConversationResult) -> CheckResult:
    """Deterministic proxy: each agent reply scores as the language of
    the caller turn before it. Ambiguous replies pass (fallback is the
    expected language); only a clear opposite-language reply fails.
    The judge refines this with an actual reading."""
    expected_language: str | None = None
    for exchange in result.transcript:
        if exchange.speaker == "patient":
            expected_language = exchange.language
        elif expected_language is not None:
            detected = detect_language(exchange.text, fallback=expected_language)
            if detected != expected_language:
                return CheckResult(
                    name="language-follow",
                    passed=False,
                    detail=f"reply in {detected!r} to a {expected_language!r} turn: "
                    f"{exchange.text[:60]!r}",
                )
    return CheckResult(name="language-follow", passed=True)
