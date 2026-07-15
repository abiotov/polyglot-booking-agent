"""Interactive text-mode chat with the booking agent.

    uv run python -m agent.cli [--provider openai|gemini]

Requires a running CalDAV server (scripts/run_radicale.py) and the
matching API key in .env. Type 'quit' to leave.
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from calendar_adapter import CalDAVCalendar
from scheduling_engine import load_config

from .loop import BookingAgent
from .prompts import build_system_prompt
from .providers import get_provider
from .tools import BookingToolbox


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai", choices=["openai", "gemini"])
    parser.add_argument("--config", default="config/practice.example.yaml")
    parser.add_argument("--url", default="http://127.0.0.1:5232")
    parser.add_argument("--calendar", default="appointments")
    args = parser.parse_args()

    config = load_config(args.config)
    calendar = CalDAVCalendar(
        url=args.url,
        username="agent",
        password="agent",
        calendar_name=args.calendar,
        timezone=config.practice.timezone,
    )
    provider = get_provider(args.provider)
    agent = BookingAgent(
        provider=provider,
        toolbox=BookingToolbox(calendar, config),
        system_prompt=build_system_prompt(config),
    )

    print(f"[{provider.name}] {config.practice.name} reception. Type 'quit' to exit.")
    while True:
        try:
            user_text = input("You:   ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_text or user_text.lower() in {"quit", "exit"}:
            break
        print(f"Agent: {agent.run_turn(user_text)}")


if __name__ == "__main__":
    main()
