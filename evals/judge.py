"""The LLM judge: conversational quality only, never the verdict.

Deterministic checks gate a scenario (design decision 8); the judge
reads the transcript for what code cannot see: was the identity read
back and confirmed before booking, did the agent stay professional,
did it promise anything it never did. Its findings are reported and
aggregated, but a scenario's pass/fail never depends on the judge
alone: a non-deterministic critic must not flake a CI gate.

The judge runs on a different provider than the agent under test, so
the two sides cannot share blind spots.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, ValidationError

from agent.providers.base import LLMProvider
from agent.types import ChatMessage

from .runner import ConversationResult
from .schema import Scenario

_PROMPT = """You are auditing a phone conversation between a medical
practice's AI receptionist ("agent") and a caller ("patient"). Each
patient line carries the language it was spoken in.

Scenario context:
- caller goal: {goal}
- caller identity: name {name!r}, phone {phone!r}

Transcript:
{transcript}

Audit the AGENT only, on exactly these criteria:
1. identity_confirmed_before_booking: did the agent read back the
   caller's name AND phone number and obtain confirmation BEFORE
   announcing the booking as done? Use null if no booking happened.
2. professional: courteous, concise, no rambling, no internal jargon
   (tool names, slot ids), never referred the caller elsewhere except
   a provided escalation contact.
3. no_broken_promises: every action the agent claimed ("it is booked",
   "I cancelled it") is plausible from the conversation; it never said
   "I will check" and then moved on without checking.

Reply with ONLY a JSON object, no prose, no code fences:
{{"identity_confirmed_before_booking": true|false|null,
  "professional": true|false,
  "no_broken_promises": true|false,
  "issues": ["short description of each problem found, empty if none"]}}"""


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity_confirmed_before_booking: bool | None
    professional: bool
    no_broken_promises: bool
    issues: tuple[str, ...] = ()


def judge_conversation(
    scenario: Scenario,
    result: ConversationResult,
    provider: LLMProvider,
) -> JudgeVerdict | None:
    """One structured audit of the transcript; None if the judge failed.

    One retry with the parse error fed back; a judge that cannot emit
    valid JSON twice is reported as unavailable rather than guessed at.
    """
    transcript = "\n".join(
        f"{e.speaker}{f' [{e.language}]' if e.language else ''}: {e.text}"
        for e in result.transcript
    )
    prompt = _PROMPT.format(
        goal=scenario.persona.goal,
        name=scenario.persona.identity.name,
        phone=scenario.persona.identity.phone,
        transcript=transcript,
    )

    history = [ChatMessage(role="user", content=prompt)]
    for _ in range(2):
        raw = provider.complete("You are a strict JSON-only auditor.", history, []).text
        try:
            return JudgeVerdict.model_validate(_extract_json(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            history.append(ChatMessage(role="assistant", content=raw))
            history.append(
                ChatMessage(
                    role="user",
                    content=f"Invalid ({exc}). Reply with ONLY the JSON object.",
                )
            )
    return None


def _extract_json(raw: str) -> dict[str, object]:
    """Tolerate code fences and surrounding prose around the object."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("not an object", text, 0)
    return parsed
