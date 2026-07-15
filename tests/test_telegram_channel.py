"""Telegram channel tests: fakes for speech, real toolbox and calendar.

No bot token, no network to Telegram, Deepgram or Cartesia: the channel
logic is what's under test (modality mirroring, language tagging,
per-chat isolation), on top of a live Radicale calendar.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import date

import pytest

from agent import BookingAgent, BookingToolbox, build_system_prompt
from agent.providers import ScriptedProvider
from agent.types import ProviderReply
from calendar_adapter import CalDAVCalendar
from calendar_adapter.devserver import make_dev_server
from channels import TelegramChannel
from channels.telegram_channel import UNHEARD_REPLY
from scheduling_engine import load_config
from scheduling_engine.models import PracticeConfig
from speech.types import AudioClip, Utterance

MONDAY = date(2026, 7, 20)


class FakeSTT:
    """Returns a fixed transcription, records what it was given."""

    def __init__(self, text: str, language: str) -> None:
        self._utterance = Utterance(text=text, language=language)
        self.received: list[str] = []

    def transcribe(self, audio: bytes, mime_type: str) -> Utterance:
        self.received.append(mime_type)
        return self._utterance


class FakeTTS:
    """Returns dummy audio, records the language it was asked for."""

    def __init__(self) -> None:
        self.languages: list[str] = []

    def synthesize(self, text: str, language: str) -> AudioClip:
        self.languages.append(language)
        return AudioClip(data=b"fake-mp3", mime_type="audio/mpeg")


@pytest.fixture(scope="module")
def radicale_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    server = make_dev_server(tmp_path_factory.mktemp("radicale-telegram"))
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


def _channel(
    radicale_url: str,
    config: PracticeConfig,
    calendar_name: str,
    replies_per_agent: list[ProviderReply],
    stt: FakeSTT,
    tts: FakeTTS,
) -> tuple[TelegramChannel, list[BookingAgent]]:
    calendar = CalDAVCalendar(
        url=radicale_url,
        username="agent",
        password="agent",
        calendar_name=calendar_name,
        timezone=config.practice.timezone,
    )
    created: list[BookingAgent] = []

    def factory() -> BookingAgent:
        agent = BookingAgent(
            provider=ScriptedProvider(list(replies_per_agent)),
            toolbox=BookingToolbox(calendar, config),
            system_prompt=build_system_prompt(config),
        )
        created.append(agent)
        return agent

    return TelegramChannel(agent_factory=factory, stt=stt, tts=tts), created


def test_text_in_text_out_no_voice(radicale_url: str, config: PracticeConfig) -> None:
    channel, _ = _channel(
        radicale_url, config, "tg-text",
        [ProviderReply(text="Bonjour !")], FakeSTT("unused", "fr"), FakeTTS(),
    )
    reply = channel.handle_text(chat_id=1, text="Bonjour")
    assert reply.text == "Bonjour !"
    assert reply.voice is None


def test_voice_in_voice_out_with_language_tag(
    radicale_url: str, config: PracticeConfig
) -> None:
    stt = FakeSTT("The first one works for me.", "en")
    tts = FakeTTS()
    channel, created = _channel(
        radicale_url, config, "tg-voice",
        [ProviderReply(text="Great, may I have your name?")], stt, tts,
    )
    reply = channel.handle_voice(chat_id=1, audio=b"opus-bytes", mime_type="audio/ogg")

    assert reply.voice is not None and reply.voice.mime_type == "audio/mpeg"
    assert reply.text == "Great, may I have your name?"
    assert stt.received == ["audio/ogg"]
    # The detected language reached both the agent tag and the TTS voice.
    assert created[0].history[0].content.startswith("[lang=en] ")
    assert tts.languages == ["en"]


def test_empty_transcription_asks_to_repeat(
    radicale_url: str, config: PracticeConfig
) -> None:
    channel, created = _channel(
        radicale_url, config, "tg-empty",
        [ProviderReply(text="never used")], FakeSTT("   ", "fr"), FakeTTS(),
    )
    reply = channel.handle_voice(chat_id=1, audio=b"x", mime_type="audio/ogg")
    assert reply.text == UNHEARD_REPLY
    assert reply.voice is None
    assert created == []  # the agent was never invoked


def test_chats_have_isolated_sessions(radicale_url: str, config: PracticeConfig) -> None:
    channel, created = _channel(
        radicale_url, config, "tg-sessions",
        [ProviderReply(text="hi"), ProviderReply(text="again")],
        FakeSTT("unused", "fr"), FakeTTS(),
    )
    channel.handle_text(chat_id=1, text="hello")
    channel.handle_text(chat_id=2, text="hello")
    channel.handle_text(chat_id=1, text="more")

    assert len(created) == 2  # one agent per chat, reused across turns
    assert len(created[0].history) == 4  # two turns in chat 1
    assert len(created[1].history) == 2  # one turn in chat 2
