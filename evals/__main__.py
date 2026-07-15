"""Run the eval campaign.

    uv run python -m evals [--provider openai|gemini] [--only <scenario-id>]

Spawns its own Radicale dev server; needs the agent provider's API key
and GEMINI_API_KEY (personas + judge) in .env. With Opik configured,
each scenario is one trace (turns, LLM rounds and tool calls nested
under it) carrying its verdicts as feedback scores, so campaigns can
be filtered and compared in the dashboard.
"""

from __future__ import annotations

import argparse
import tempfile
import threading

from dotenv import load_dotenv

import observability
from agent.providers import get_provider
from agent.providers.base import LLMProvider
from calendar_adapter.devserver import make_dev_server
from observability import flush, traced
from scheduling_engine import load_config
from scheduling_engine.models import PracticeConfig

from .checks import run_checks
from .judge import judge_conversation
from .report import Campaign, ScenarioRecord, new_campaign_id, save, to_markdown
from .runner import run_scenario
from .schema import Scenario, load_scenarios


@traced("eval-scenario")
def _run_one(
    scenario: Scenario,
    agent_provider: LLMProvider,
    persona_provider: LLMProvider,
    url: str,
    config: PracticeConfig,
    with_judge: bool,
) -> ScenarioRecord:
    result = run_scenario(scenario, agent_provider, persona_provider, url, config)
    checks = run_checks(scenario, result, config)
    verdict = (
        judge_conversation(scenario, result, persona_provider) if with_judge else None
    )
    record = ScenarioRecord(
        scenario_id=scenario.id,
        passed=all(check.passed for check in checks),
        turns=result.turns,
        ended_reason=result.ended_reason,
        languages=scenario.persona.languages,
        checks=tuple(checks),
        judge=verdict,
    )
    _annotate_trace(scenario, agent_provider, record)

    for exchange in result.transcript:
        tag = f" [{exchange.language}]" if exchange.language else ""
        print(f"  {exchange.speaker:>7}{tag}: {exchange.text}")
    for check in checks:
        mark = "PASS" if check.passed else "FAIL"
        detail = f"  ({check.detail})" if check.detail else ""
        print(f"  [{mark}] {check.name}{detail}")
    if with_judge:
        if verdict is None:
            print("  [JUDGE] unavailable (invalid output twice)")
        else:
            print(
                f"  [JUDGE] identity_confirmed={verdict.identity_confirmed_before_booking} "
                f"professional={verdict.professional} "
                f"no_broken_promises={verdict.no_broken_promises}"
            )
            for issue in verdict.issues:
                print(f"  [JUDGE] issue: {issue}")
    print(f"  ==> {'PASS' if record.passed else 'FAIL'}")
    return record


def _annotate_trace(
    scenario: Scenario, agent_provider: LLMProvider, record: ScenarioRecord
) -> None:
    """Name the scenario trace and attach verdicts as feedback scores."""
    if not observability.enabled():
        return
    try:
        from opik import opik_context

        scores = [
            {"name": f"check.{check.name}", "value": 1.0 if check.passed else 0.0}
            for check in record.checks
        ]
        scores.append({"name": "scenario.passed", "value": 1.0 if record.passed else 0.0})
        if record.judge is not None:
            for name, value in (
                ("judge.identity_confirmed", record.judge.identity_confirmed_before_booking),
                ("judge.professional", record.judge.professional),
                ("judge.no_broken_promises", record.judge.no_broken_promises),
            ):
                if value is not None:
                    scores.append({"name": name, "value": 1.0 if value else 0.0})
        opik_context.update_current_trace(
            name=f"eval:{scenario.id}",
            feedback_scores=scores,
            metadata={
                "scenario": scenario.id,
                "agent_provider": agent_provider.name,
                "turns": record.turns,
                "ended_reason": record.ended_reason,
            },
            tags=["eval", scenario.id],
        )
    except Exception:  # noqa: BLE001 - observability must never break a campaign
        pass


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai", choices=["openai", "gemini"])
    parser.add_argument("--persona-provider", default="gemini", choices=["openai", "gemini"])
    parser.add_argument("--only", default=None, help="run a single scenario id")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
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

    server = make_dev_server(tempfile.mkdtemp(prefix="evals-radicale-"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    records: list[ScenarioRecord] = []
    started_at = new_campaign_id()
    try:
        for scenario in scenarios:
            print(f"\n=== {scenario.id} ({args.provider}) ===")
            records.append(
                _run_one(
                    scenario, agent_provider, persona_provider, url, config,
                    with_judge=not args.no_judge,
                )
            )
    finally:
        flush()
        server.shutdown()
        thread.join(timeout=5)

    campaign = Campaign(
        agent_provider=agent_provider.name,
        persona_provider=persona_provider.name,
        started_at=started_at,
        records=tuple(records),
    )
    if not args.only:
        path = save(campaign)
        print(f"\nreport: {path}")
    print()
    print(to_markdown(campaign))
    if campaign.passed != len(campaign.records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
