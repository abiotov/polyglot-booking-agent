"""Judge plumbing tests: parsing and retry, with a scripted provider."""

from __future__ import annotations

from datetime import date

from evals.judge import judge_conversation
from evals.runner import ConversationResult, Exchange
from evals.schema import Scenario

from agent.providers import ScriptedProvider
from agent.types import ProviderReply

SCENARIO = Scenario.model_validate(
    {
        "id": "j",
        "persona": {
            "goal": "book",
            "script_hint": "n/a",
            "identity": {"name": "Awa Dossou", "phone": "+22997112233"},
        },
        "expected": {"outcome": "booked"},
    }
)

RESULT = ConversationResult(
    scenario_id="j",
    transcript=(
        Exchange(speaker="patient", text="Un rendez-vous ?", language="fr"),
        Exchange(speaker="agent", text="Bien sûr, première visite ?"),
    ),
    tool_trace=(),
    final_bookings=(),
    final_busy=(),
    target_day=date(2026, 7, 20),
    turns=1,
    ended_reason="goal",
)

GOOD_JSON = (
    '{"identity_confirmed_before_booking": null, "professional": true,'
    ' "no_broken_promises": true, "issues": []}'
)


def test_clean_json_is_parsed() -> None:
    provider = ScriptedProvider([ProviderReply(text=GOOD_JSON)])
    verdict = judge_conversation(SCENARIO, RESULT, provider)
    assert verdict is not None
    assert verdict.professional and verdict.identity_confirmed_before_booking is None


def test_fenced_json_with_prose_is_parsed() -> None:
    raw = f"Here is my audit:\n```json\n{GOOD_JSON}\n```\nThanks."
    provider = ScriptedProvider([ProviderReply(text=raw)])
    verdict = judge_conversation(SCENARIO, RESULT, provider)
    assert verdict is not None and verdict.no_broken_promises


def test_invalid_then_valid_uses_the_retry() -> None:
    provider = ScriptedProvider(
        [ProviderReply(text="I think it went fine!"), ProviderReply(text=GOOD_JSON)]
    )
    verdict = judge_conversation(SCENARIO, RESULT, provider)
    assert verdict is not None


def test_twice_invalid_returns_none() -> None:
    provider = ScriptedProvider(
        [ProviderReply(text="not json"), ProviderReply(text="{still: broken")]
    )
    assert judge_conversation(SCENARIO, RESULT, provider) is None
