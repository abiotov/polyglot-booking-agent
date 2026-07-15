"""Campaign aggregation: one JSON artifact, one markdown table.

The JSON is the machine-readable record of a campaign (kept out of git,
uploaded as a CI artifact); the markdown is what humans and the README
consume. Numbers are computed from the same CheckResult/JudgeVerdict
objects that gated the run, never recomputed differently.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .checks import CheckResult
from .judge import JudgeVerdict


class ScenarioRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    passed: bool
    turns: int
    ended_reason: str
    languages: tuple[str, ...]
    checks: tuple[CheckResult, ...]
    judge: JudgeVerdict | None = None


class Campaign(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_provider: str
    persona_provider: str
    started_at: str
    records: tuple[ScenarioRecord, ...]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.records if r.passed)


def new_campaign_id() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def check_rates(campaign: Campaign) -> dict[str, tuple[int, int]]:
    """check name -> (passed, total) across the campaign."""
    rates: dict[str, list[int]] = {}
    for record in campaign.records:
        for check in record.checks:
            passed, total = rates.setdefault(check.name, [0, 0])
            rates[check.name] = [passed + (1 if check.passed else 0), total + 1]
    return {name: (p, t) for name, (p, t) in sorted(rates.items())}


def judge_rates(campaign: Campaign) -> dict[str, tuple[int, int]]:
    rates: dict[str, list[int]] = {}
    for record in campaign.records:
        if record.judge is None:
            continue
        for name, value in (
            ("identity-confirmed", record.judge.identity_confirmed_before_booking),
            ("professional", record.judge.professional),
            ("no-broken-promises", record.judge.no_broken_promises),
        ):
            if value is None:
                continue
            passed, total = rates.setdefault(name, [0, 0])
            rates[name] = [passed + (1 if value else 0), total + 1]
    return {name: (p, t) for name, (p, t) in sorted(rates.items())}


def to_markdown(campaign: Campaign) -> str:
    lines = [
        f"## Eval campaign {campaign.started_at}",
        "",
        f"- agent: `{campaign.agent_provider}` | personas/judge: "
        f"`{campaign.persona_provider}`",
        f"- **scenarios: {campaign.passed}/{len(campaign.records)} passed**",
        "",
        "| scenario | verdict | turns | failed checks |",
        "| --- | --- | --- | --- |",
    ]
    for record in campaign.records:
        failed = ", ".join(c.name for c in record.checks if not c.passed) or "-"
        verdict = "PASS" if record.passed else "FAIL"
        lines.append(
            f"| {record.scenario_id} | {verdict} | {record.turns} | {failed} |"
        )
    lines += ["", "| deterministic check | pass rate |", "| --- | --- |"]
    for name, (passed, total) in check_rates(campaign).items():
        lines.append(f"| {name} | {passed}/{total} |")
    judge = judge_rates(campaign)
    if judge:
        lines += ["", "| judge criterion | pass rate |", "| --- | --- |"]
        for name, (passed, total) in judge.items():
            lines.append(f"| {name} | {passed}/{total} |")
    return "\n".join(lines) + "\n"


def save(campaign: Campaign, results_dir: str | Path = "evals/results") -> Path:
    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{campaign.started_at}-{campaign.agent_provider}"
    json_path = directory / f"{stem}.json"
    json_path.write_text(
        json.dumps(campaign.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (directory / f"{stem}.md").write_text(to_markdown(campaign), encoding="utf-8")
    return json_path
