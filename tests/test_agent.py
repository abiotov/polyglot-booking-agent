"""Agent loop and toolbox tests, no API key required.

A ScriptedProvider plays the LLM's role while everything else is real:
the toolbox, the scheduling engine and a live Radicale calendar. What
is under test is precisely what we claim in the README: the guardrails
live in code, not in the prompt.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import date, datetime

import pytest

from agent import BookingAgent, BookingToolbox, build_system_prompt
from agent.providers import ScriptedProvider
from agent.types import ProviderReply, ToolCall
from calendar_adapter import CalDAVCalendar
from calendar_adapter.devserver import make_dev_server
from scheduling_engine import load_config
from scheduling_engine.models import PracticeConfig

MONDAY = date(2026, 7, 20)


@pytest.fixture(scope="module")
def radicale_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    server = make_dev_server(tmp_path_factory.mktemp("radicale-agent"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def config() -> PracticeConfig:
    return load_config("config/practice.example.yaml")


@pytest.fixture()
def calendar(
    radicale_url: str, config: PracticeConfig, request: pytest.FixtureRequest
) -> CalDAVCalendar:
    return CalDAVCalendar(
        url=radicale_url,
        username="agent",
        password="agent",
        calendar_name=f"agent-{request.node.name}",
        timezone=config.practice.timezone,
    )


def _call(name: str, call_id: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def test_full_booking_flow_writes_to_the_calendar(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    """qualify -> rank -> book, driven through the loop, lands in CalDAV."""
    toolbox = BookingToolbox(calendar, config)
    provider = ScriptedProvider(
        [
            ProviderReply(
                tool_calls=(
                    _call("qualify", "c1", client_type="premium", visit_type="first_visit"),
                    _call("get_ranked_slots", "c2", day="2026-07-20"),
                )
            ),
            ProviderReply(text="Je peux vous proposer lundi 08:00. Votre nom et numero ?"),
            ProviderReply(
                tool_calls=(
                    _call(
                        "book",
                        "c3",
                        slot_id="2026-07-20T08:00",
                        patient_name="Jean Kokou",
                        patient_phone="+22997000000",
                    ),
                )
            ),
            ProviderReply(text="C'est confirme pour lundi 08:00, M. Kokou."),
        ]
    )
    agent = BookingAgent(provider, toolbox, build_system_prompt(config))

    first = agent.run_turn("Bonjour, un rendez-vous lundi ?", today=MONDAY)
    assert "08:00" in first

    second = agent.run_turn("Jean Kokou, +22997000000", today=MONDAY)
    assert "confirme" in second

    intervals = calendar.busy_intervals(MONDAY)
    assert len(intervals) == 1
    assert intervals[0].start == datetime(2026, 7, 20, 8, 0)


def test_tool_results_are_fed_back_to_the_model(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    toolbox = BookingToolbox(calendar, config)
    provider = ScriptedProvider(
        [
            ProviderReply(
                tool_calls=(
                    _call("qualify", "c1", client_type="premium", visit_type="follow_up"),
                )
            ),
            ProviderReply(text="ok"),
        ]
    )
    agent = BookingAgent(provider, toolbox, build_system_prompt(config))
    agent.run_turn("hello", today=MONDAY)

    # The second provider call must have seen the tool result in history.
    final_history = provider.seen_histories[-1]
    tool_messages = [m for m in final_history if m.role == "tool"]
    assert len(tool_messages) == 1
    assert json.loads(tool_messages[0].content) == {
        "ok": True,
        "client_type": "premium",
        "visit_type": "follow_up",
    }


def test_availability_requires_qualification(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    toolbox = BookingToolbox(calendar, config)
    result = json.loads(toolbox.dispatch("get_ranked_slots", {"day": "2026-07-20"}))
    assert "error" in result and "qualify" in result["error"]


def test_booking_an_unoffered_slot_is_refused(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    """The LLM cannot book a time it invented: no offer, no booking."""
    toolbox = BookingToolbox(calendar, config)
    toolbox.dispatch("qualify", {"client_type": "premium", "visit_type": "first_visit"})
    result = json.loads(
        toolbox.dispatch(
            "book",
            {
                "slot_id": "2026-07-20T09:00",  # never returned by get_ranked_slots
                "patient_name": "X",
                "patient_phone": "+22990000000",
            },
        )
    )
    assert "error" in result
    assert calendar.busy_intervals(MONDAY) == []


def test_taken_slot_error_tells_the_model_to_rerank(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    """The mid-call race: the practitioner takes the slot between offer and book."""
    toolbox = BookingToolbox(calendar, config)
    toolbox.dispatch("qualify", {"client_type": "premium", "visit_type": "first_visit"})
    offered = json.loads(toolbox.dispatch("get_ranked_slots", {"day": "2026-07-20"}))
    slot_id = offered["slots"][0]["slot_id"]

    # Another actor books that exact span behind the agent's back.
    calendar.book(
        start=datetime(2026, 7, 20, 8, 0),
        end=datetime(2026, 7, 20, 8, 15),
        patient_name="Practitioner Manual",
        patient_phone="+22990000009",
    )

    result = json.loads(
        toolbox.dispatch(
            "book",
            {"slot_id": slot_id, "patient_name": "Y", "patient_phone": "+22990000001"},
        )
    )
    assert "error" in result and "get_ranked_slots" in result["error"]


def test_unknown_qualification_values_are_rejected(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    toolbox = BookingToolbox(calendar, config)
    result = json.loads(
        toolbox.dispatch("qualify", {"client_type": "vip", "visit_type": "first_visit"})
    )
    assert "error" in result


def test_blank_identity_is_refused(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    """A booking with an empty name or junk phone must never reach the calendar."""
    toolbox = BookingToolbox(calendar, config)
    toolbox.dispatch("qualify", {"client_type": "premium", "visit_type": "first_visit"})
    offered = json.loads(toolbox.dispatch("get_ranked_slots", {"day": "2026-07-20"}))
    slot_id = offered["slots"][0]["slot_id"]

    for name, phone in [("", "+22997000001"), ("  ", "+22997000001"), ("Jean", "abc")]:
        result = json.loads(
            toolbox.dispatch(
                "book", {"slot_id": slot_id, "patient_name": name, "patient_phone": phone}
            )
        )
        assert "error" in result
    assert calendar.busy_intervals(MONDAY) == []


def test_find_bookings_by_phone_closes_the_loop(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    """Check -> cancel without the caller ever knowing a uid upfront."""
    toolbox = BookingToolbox(calendar, config)
    toolbox.dispatch("qualify", {"client_type": "premium", "visit_type": "first_visit"})
    offered = json.loads(toolbox.dispatch("get_ranked_slots", {"day": "2026-07-20"}))
    toolbox.dispatch(
        "book",
        {
            "slot_id": offered["slots"][0]["slot_id"],
            "patient_name": "Jean Kokou",
            "patient_phone": "+229 97 00 00 01",
        },
    )

    # Different formatting of the same number still matches.
    found = json.loads(toolbox.dispatch("find_bookings", {"patient_phone": "22997000001"}))
    assert len(found["bookings"]) == 1
    assert found["bookings"][0]["patient_name"] == "Jean Kokou"

    # A stranger's number finds nothing.
    other = json.loads(toolbox.dispatch("find_bookings", {"patient_phone": "+22990009999"}))
    assert other["bookings"] == []

    # The found uid is enough to cancel.
    uid = found["bookings"][0]["booking_uid"]
    cancelled = json.loads(toolbox.dispatch("cancel", {"booking_uid": uid}))
    assert cancelled == {"cancelled": True}
    assert calendar.busy_intervals(MONDAY) == []


def test_language_tag_from_the_channel_is_prepended(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    """Voice channels tag each utterance with its detected language."""
    toolbox = BookingToolbox(calendar, config)
    provider = ScriptedProvider([ProviderReply(text="ok")])
    agent = BookingAgent(provider, toolbox, build_system_prompt(config))
    agent.run_turn("The first one works.", today=MONDAY, language="en")
    assert agent.history[0].content == "[lang=en] The first one works."


def test_runaway_tool_loop_fails_safe(
    calendar: CalDAVCalendar, config: PracticeConfig
) -> None:
    """A model that never answers with text gets cut off politely."""
    toolbox = BookingToolbox(calendar, config)
    endless = ProviderReply(
        tool_calls=(
            _call("qualify", "cx", client_type="premium", visit_type="first_visit"),
        )
    )
    provider = ScriptedProvider([endless] * 10)
    agent = BookingAgent(provider, toolbox, build_system_prompt(config), max_tool_rounds=3)
    reply = agent.run_turn("hi", today=MONDAY)
    assert "sorry" in reply.lower()
    assert len(provider.seen_histories) == 3
