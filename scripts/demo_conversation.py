"""Replay a canned booking conversation against a real LLM provider.

    uv run python scripts/demo_conversation.py [--provider openai|gemini]

Requires scripts/run_radicale.py running and the provider's API key in
.env. The caller starts in French and switches to English mid-call; the
last step verifies the appointment actually landed in the calendar.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import date, timedelta

from dotenv import load_dotenv

from agent import BookingAgent, BookingToolbox, build_system_prompt
from agent.providers import get_provider
from calendar_adapter import CalDAVCalendar
from scheduling_engine import load_config


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai", choices=["openai", "gemini"])
    parser.add_argument("--url", default="http://127.0.0.1:5232")
    parser.add_argument("--config", default="config/practice.example.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    calendar = CalDAVCalendar(
        url=args.url,
        username="agent",
        password="agent",
        calendar_name=f"demo-{uuid.uuid4().hex[:6]}",
        timezone=config.practice.timezone,
    )
    provider = get_provider(args.provider)
    agent = BookingAgent(
        provider=provider,
        toolbox=BookingToolbox(calendar, config),
        system_prompt=build_system_prompt(config),
    )

    today = date.today()
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    turns = [
        (f"Bonjour, je voudrais un rendez-vous le lundi {monday.strftime('%d/%m/%Y')} au matin.", "fr"),
        ("Je suis client premium et c'est une premiere visite.", "fr"),
        ("The first one works for me. My name is Jean Kokou, phone +229 97 00 00 01.", "en"),
        ("Yes, that's correct, please book it.", "en"),
    ]

    print(f"provider: {provider.name}   demo day: {monday.isoformat()}\n")
    for text, lang in turns:
        print(f"You ({lang}): {text}")
        print(f"Agent:    {agent.run_turn(text, language=lang)}\n")

    booked = calendar.busy_intervals(monday)
    print(f"calendar check: {len(booked)} appointment(s) on {monday.isoformat()}")
    for interval in booked:
        print(f"  {interval.start:%H:%M}-{interval.end:%H:%M} ({interval.kind})")


if __name__ == "__main__":
    main()
