"""Run the eval campaign.

    uv run python -m evals [--provider openai|gemini] [--only <scenario-id>]

Spawns its own Radicale dev server; needs the agent provider's API key
and GEMINI_API_KEY (persona) in .env.
"""

from __future__ import annotations

import argparse
import threading

from dotenv import load_dotenv

from agent.providers import get_provider
from calendar_adapter.devserver import make_dev_server
from observability import flush
from scheduling_engine import load_config

from .runner import run_scenario
from .schema import load_scenarios


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai", choices=["openai", "gemini"])
    parser.add_argument("--persona-provider", default="gemini", choices=["openai", "gemini"])
    parser.add_argument("--only", default=None, help="run a single scenario id")
    parser.add_argument("--config", default="config/practice.example.yaml")
    parser.add_argument("--scenarios", default="evals/scenarios")
    args = parser.parse_args()

    scenarios = load_scenarios(args.scenarios)
    if args.only:
        scenarios = [s for s in scenarios if s.id == args.only]
        if not scenarios:
            raise SystemExit(f"no scenario with id {args.only!r}")

    config = load_config(args.config)
    agent_provider = get_provider(args.provider)
    persona_provider = get_provider(args.persona_provider)

    import tempfile

    server = make_dev_server(tempfile.mkdtemp(prefix="evals-radicale-"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    try:
        for scenario in scenarios:
            print(f"\n=== {scenario.id} ({args.provider}) ===")
            result = run_scenario(scenario, agent_provider, persona_provider, url, config)
            for exchange in result.transcript:
                tag = f" [{exchange.language}]" if exchange.language else ""
                print(f"  {exchange.speaker:>7}{tag}: {exchange.text}")
            print(f"  -- ended: {result.ended_reason} after {result.turns} turns")
            print(f"  -- tools: {[record.name for record in result.tool_trace]}")
            bookings = [
                (b.start.isoformat(timespec="minutes"), b.patient_name, b.patient_phone)
                for b in result.final_bookings
            ]
            print(f"  -- bookings: {bookings}")
    finally:
        flush()
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
