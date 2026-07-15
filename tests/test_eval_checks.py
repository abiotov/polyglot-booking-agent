"""Deterministic eval checks, exercised on fabricated conversations."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from evals.checks import run_checks
from evals.runner import ConversationResult, Exchange, ToolCallRecord
from evals.schema import Scenario

from calendar_adapter import Booking
from scheduling_engine.models import PracticeConfig

MONDAY = date(2026, 7, 20)

BASE_SCENARIO: dict = {
    "id": "fabricated",
    "persona": {
        "goal": "book",
        "script_hint": "n/a",
        "identity": {"name": "Awa Dossou", "phone": "+229 97 11 22 33"},
        "client_type": "premium",
    },
    "expected": {"outcome": "booked", "window": "premium"},
}

RANKING_RESULT = (
    '{"slots": [{"slot_id": "2026-07-20T08:15", "start": "Monday 08:15", "rank": 1},'
    ' {"slot_id": "2026-07-20T11:45", "start": "Monday 11:45", "rank": 2}]}'
)


def _booking(
    start: datetime, name: str = "Awa Dossou", phone: str = "00229 97 11 22 33"
) -> Booking:
    return Booking(
        uid="u1", start=start, end=start.replace(minute=start.minute + 15),
        patient_name=name, patient_phone=phone,
    )


def _result(
    bookings: tuple[Booking, ...] = (),
    trace: tuple[ToolCallRecord, ...] = (),
    transcript: tuple[Exchange, ...] = (),
    ended: str = "goal",
) -> ConversationResult:
    return ConversationResult(
        scenario_id="fabricated", transcript=transcript, tool_trace=trace,
        final_bookings=bookings, final_busy=(), target_day=MONDAY, turns=5,
        ended_reason=ended,
    )


def _by_name(checks: list, name: str):
    return next(c for c in checks if c.name == name)


def test_happy_booking_passes_all_checks(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(BASE_SCENARIO)
    trace = (
        ToolCallRecord(name="qualify", arguments={}, result='{"ok": true}'),
        ToolCallRecord(name="get_ranked_slots", arguments={}, result=RANKING_RESULT),
        ToolCallRecord(
            name="book", arguments={"slot_id": "2026-07-20T08:15"}, result='{"booked": true}'
        ),
    )
    transcript = (
        Exchange(speaker="patient", text="Un rendez-vous lundi ?", language="fr"),
        Exchange(speaker="agent", text="Je peux vous proposer 08:15 ou 11h45."),
    )
    checks = run_checks(
        scenario, _result((_booking(datetime(2026, 7, 20, 8, 15)),), trace, transcript), config
    )
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_phone_normalization_accepts_00_prefix(config: PracticeConfig) -> None:
    # The calendar stores "00229...", the scenario says "+229...": same number.
    scenario = Scenario.model_validate(BASE_SCENARIO)
    booking = _booking(datetime(2026, 7, 20, 8, 15), phone="00229 97 11 22 33")
    checks = run_checks(scenario, _result((booking,)), config)
    assert _by_name(checks, "outcome").passed


def test_wrong_identity_fails_outcome(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(BASE_SCENARIO)
    booking = _booking(datetime(2026, 7, 20, 8, 15), name="Aetanose", phone="000000019499")
    check = _by_name(run_checks(scenario, _result((booking,)), config), "outcome")
    assert not check.passed and "identity mismatch" in check.detail


def test_out_of_window_slot_fails(config: PracticeConfig) -> None:
    # Standard clients may only book from 10:00 in the test config;
    # a standard booking at 08:15 violates the contract.
    scenario = Scenario.model_validate(
        {
            **BASE_SCENARIO,
            "persona": {**BASE_SCENARIO["persona"], "client_type": "standard"},
            "expected": {"outcome": "booked", "window": "standard"},
        }
    )
    booking = _booking(datetime(2026, 7, 20, 8, 15))
    check = _by_name(run_checks(scenario, _result((booking,)), config), "outcome")
    assert not check.passed and "outside" in check.detail


def test_booking_a_never_offered_slot_fails(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(BASE_SCENARIO)
    trace = (
        ToolCallRecord(name="qualify", arguments={}, result='{"ok": true}'),
        ToolCallRecord(name="get_ranked_slots", arguments={}, result=RANKING_RESULT),
        ToolCallRecord(
            name="book", arguments={"slot_id": "2026-07-20T09:00"}, result='{"booked": true}'
        ),
    )
    check = _by_name(run_checks(scenario, _result(trace=trace), config), "book-only-offered")
    assert not check.passed


def test_ranking_before_qualification_fails(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(BASE_SCENARIO)
    trace = (
        ToolCallRecord(name="get_ranked_slots", arguments={}, result=RANKING_RESULT),
        ToolCallRecord(name="qualify", arguments={}, result='{"ok": true}'),
    )
    check = _by_name(run_checks(scenario, _result(trace=trace), config), "qualify-before-ranking")
    assert not check.passed


def test_hallucinated_time_is_caught(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(BASE_SCENARIO)
    trace = (ToolCallRecord(name="get_ranked_slots", arguments={}, result=RANKING_RESULT),)
    transcript = (
        Exchange(speaker="patient", text="Des créneaux ?", language="fr"),
        Exchange(speaker="agent", text="Je vous propose 09h30."),  # never offered
    )
    check = _by_name(
        run_checks(scenario, _result(trace=trace, transcript=transcript), config),
        "no-hallucinated-times",
    )
    assert not check.passed and "9:30" in check.detail


def test_times_from_tool_results_are_allowed_in_any_format(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(BASE_SCENARIO)
    trace = (ToolCallRecord(name="get_ranked_slots", arguments={}, result=RANKING_RESULT),)
    transcript = (
        Exchange(speaker="patient", text="Des créneaux ?", language="fr"),
        Exchange(speaker="agent", text="Il reste 8h15 ou 11:45, au choix."),
    )
    check = _by_name(
        run_checks(scenario, _result(trace=trace, transcript=transcript), config),
        "no-hallucinated-times",
    )
    assert check.passed


def test_language_mismatch_is_caught(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(BASE_SCENARIO)
    transcript = (
        Exchange(speaker="patient", text="Yes, please book it now.", language="en"),
        Exchange(
            speaker="agent",
            text="Très bien, votre rendez-vous est confirmé pour lundi, merci beaucoup.",
        ),
    )
    check = _by_name(
        run_checks(scenario, _result(transcript=transcript), config), "language-follow"
    )
    assert not check.passed


def test_cancel_outcome_requires_seed_gone(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(
        {
            **BASE_SCENARIO,
            "persona": {**BASE_SCENARIO["persona"], "goal": "cancel"},
            "calendar_seed": [
                {"day_offset": 0, "start": "08:30", "owner": "agent"},
            ],
            "expected": {"outcome": "cancelled"},
        }
    )
    # Seed still present -> fail.
    still_there = _booking(datetime(2026, 7, 20, 8, 30))
    assert not _by_name(run_checks(scenario, _result((still_there,)), config), "outcome").passed
    # Seed gone -> pass.
    assert _by_name(run_checks(scenario, _result(()), config), "outcome").passed


def test_runtime_error_fails(config: PracticeConfig) -> None:
    scenario = Scenario.model_validate(BASE_SCENARIO)
    booking = _booking(datetime(2026, 7, 20, 8, 15))
    checks = run_checks(
        scenario, _result((booking,), ended="error:RuntimeError: boom"), config
    )
    assert not _by_name(checks, "no-runtime-error").passed


@pytest.fixture()
def config() -> PracticeConfig:
    from tests.conftest import REFERENCE_CONFIG

    return PracticeConfig.model_validate(REFERENCE_CONFIG)
