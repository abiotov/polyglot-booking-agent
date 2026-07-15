"""Telegram bot glue: python-telegram-bot wiring around TelegramChannel.

    uv run python -m channels.telegram_bot [--provider openai|gemini]

Requires scripts/run_radicale.py running and, in .env:
TELEGRAM_BOT_TOKEN, DEEPGRAM_API_KEY, CARTESIA_API_KEY plus the LLM key.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable
from typing import TypeVar

from dotenv import load_dotenv
from telegram import Chat, Update
from telegram.constants import ChatAction
from telegram.error import Conflict as TelegramConflict
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent import BookingAgent, BookingToolbox, build_system_prompt
from agent.providers import get_provider
from calendar_adapter import CalDAVCalendar
from observability import flush
from scheduling_engine import load_config
from speech import CartesiaTTS, DeepgramSTT

from .telegram_channel import TelegramChannel

T = TypeVar("T")

# One voice for every language: the receptionist keeps her identity
# when the caller switches language (sonic-3 handles cross-language).
_AMELIE = "faa75703-00e3-4a57-9955-0703001e3231"
DEFAULT_VOICES = {"fr": _AMELIE, "en": _AMELIE}

GREETING = (
    "Bonjour ! Je suis la réceptionniste. Écrivez-moi ou envoyez une note "
    "vocale, en français ou en anglais, pour prendre, déplacer ou annuler "
    "un rendez-vous.\n"
    "Hello! I am the receptionist. Type or send a voice note, in French "
    "or English, to book, move or cancel an appointment."
)


def build_channel(
    provider_name: str, config_path: str, url: str, calendar_name: str
) -> TelegramChannel:
    config = load_config(config_path)
    calendar = CalDAVCalendar(
        url=url,
        username="agent",
        password="agent",
        calendar_name=calendar_name,
        timezone=config.practice.timezone,
    )
    provider = get_provider(provider_name)
    system_prompt = build_system_prompt(config)

    def agent_factory() -> BookingAgent:
        return BookingAgent(
            provider=provider,
            toolbox=BookingToolbox(calendar, config),
            system_prompt=system_prompt,
        )

    voices = {
        "fr": os.environ.get("CARTESIA_VOICE_FR", DEFAULT_VOICES["fr"]),
        "en": os.environ.get("CARTESIA_VOICE_EN", DEFAULT_VOICES["en"]),
    }
    return TelegramChannel(
        agent_factory=agent_factory,
        stt=DeepgramSTT(
            api_key=_require("DEEPGRAM_API_KEY"),
            languages=config.practice.languages,
        ),
        tts=CartesiaTTS(api_key=_require("CARTESIA_API_KEY"), voices=voices),
    )


async def _with_chat_action(chat: Chat, action: ChatAction, work: Awaitable[T]) -> T:
    """Show 'typing' / 'recording voice' for as long as `work` runs.

    A Telegram chat action expires after ~5 seconds, so it is re-sent
    on a timer until the work completes.
    """

    async def keep_alive() -> None:
        while True:
            await chat.send_chat_action(action)
            await asyncio.sleep(4.0)

    task = asyncio.create_task(keep_alive())
    try:
        return await work
    finally:
        task.cancel()


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Keep per-request HTTP noise out of the operational log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai", choices=["openai", "gemini"])
    parser.add_argument("--config", default="config/practice.example.yaml")
    parser.add_argument("--url", default="http://127.0.0.1:5232")
    parser.add_argument("--calendar", default="appointments")
    args = parser.parse_args()

    channel = build_channel(args.provider, args.config, args.url, args.calendar)

    async def on_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await update.message.reply_text(GREETING)

    async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.text is None or message.chat is None:
            return
        # Blocking work (LLM, calendar) runs off the event loop; the
        # caller sees "typing..." for the whole duration.
        reply = await _with_chat_action(
            message.chat,
            ChatAction.TYPING,
            asyncio.to_thread(channel.handle_text, message.chat.id, message.text),
        )
        await message.reply_text(reply.text)

    async def on_voice(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.voice is None or message.chat is None:
            return
        telegram_file = await message.voice.get_file()
        audio = bytes(await telegram_file.download_as_bytearray())
        mime_type = message.voice.mime_type or "audio/ogg"
        reply = await _with_chat_action(
            message.chat,
            ChatAction.RECORD_VOICE,
            asyncio.to_thread(channel.handle_voice, message.chat.id, audio, mime_type),
        )
        if reply.voice is not None:
            await message.reply_voice(voice=reply.voice.data, caption=reply.text[:1024])
        else:
            await message.reply_text(reply.text)

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        error = context.error
        if isinstance(error, TelegramConflict):
            # 33 stack traces for one root cause helps nobody.
            logging.getLogger("channels.telegram").error(
                "another instance of this bot is polling with the same token; "
                "stop it (only one instance may run)"
            )
            return
        logging.getLogger("channels.telegram").exception(
            "unhandled error while processing an update", exc_info=error
        )
        # Never fail silently: a caller who gets no reply retries blind.
        if isinstance(update, Update) and update.effective_message is not None:
            with contextlib.suppress(Exception):  # best effort only
                await update.effective_message.reply_text(
                    "Petit souci technique, pouvez-vous renvoyer votre message ? / "
                    "Small technical hiccup, could you resend your message?"
                )

    application = (
        Application.builder()
        .token(_require("TELEGRAM_BOT_TOKEN"))
        # Defaults (5s) time out on slow uplinks when moving voice notes.
        .connect_timeout(20)
        .read_timeout(30)
        .write_timeout(30)
        .media_write_timeout(120)
        .build()
    )
    application.add_handler(CommandHandler("start", on_start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(MessageHandler(filters.VOICE, on_voice))
    application.add_error_handler(on_error)

    print("Telegram bot running (Ctrl+C to stop)")
    try:
        application.run_polling()
    finally:
        flush()


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"{key} is not set; add it to .env")
    return value


if __name__ == "__main__":
    main()
