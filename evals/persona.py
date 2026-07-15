"""The simulated patient: an LLM playing one scenario's caller.

The persona runs on a different provider than the agent under test
(Gemini Flash by default, free tier) so campaigns cost nothing and the
two sides cannot share quirks. Each persona message is prefixed with
its language ('fr:' / 'en:') so the runner can feed the agent the same
[lang=xx] tag a voice channel would; '[END]' terminates the call.
"""

from __future__ import annotations

from datetime import date

from agent.providers.base import LLMProvider
from agent.types import ChatMessage
from speech.langdetect import detect_language

from .schema import PersonaSpec

END_MARKER = "[END]"

_GOAL_STATEMENTS = {
    "book": (
        "You want to BOOK A NEW appointment. You do NOT have any existing "
        "appointment, whatever your visit type is."
    ),
    "cancel": "You want to CANCEL an appointment you booked earlier by phone.",
    "reschedule": "You want to MOVE an appointment you booked earlier by phone.",
    "ask_hours": "You only want information; you never book anything.",
    "impossible": (
        "You insist on something the practice cannot do, then eventually give up."
    ),
}

_SYSTEM_TEMPLATE = """You are role-playing a patient calling a medical practice
to manage an appointment. Stay in character for the whole call; never
reveal you are an AI, never break character, never help the receptionist.

Your character:
- Name: {name}  |  Phone: {phone}
- You are a {client_type} client; this is a {visit_type}.
- YOUR OBJECTIVE: {goal_statement}
- Scenario: {script_hint}
- The day you care about is {target_day}.

Behavior rules:
1. Speak like a real caller on the phone: one or two short sentences
   per message, natural, sometimes imperfect. When you first ask for
   an appointment, say which day you want (the day above).
2. Only give information when it is asked for (name and phone only
   when the receptionist asks), unless your scenario says otherwise.
   Never repeat the same demand more than twice: if the receptionist
   cannot do something, adapt toward your objective or give up.
3. Prefix EVERY message with its language tag: 'fr:' or 'en:'. Follow
   your scenario for which language to use when.
4. When your goal is achieved and confirmed, or when you decide to
   give up, reply with exactly: {end}
5. Never output anything after {end}."""


class SimulatedPatient:
    def __init__(self, spec: PersonaSpec, provider: LLMProvider, target_day: date) -> None:
        self._provider = provider
        self._languages = spec.languages
        self._last_language = spec.languages[0]
        self._system = _SYSTEM_TEMPLATE.format(
            name=spec.identity.name,
            phone=spec.identity.phone,
            client_type=spec.client_type,
            visit_type=spec.visit_type,
            goal_statement=_GOAL_STATEMENTS[spec.goal],
            script_hint=spec.script_hint,
            target_day=target_day.strftime("%A %d %B %Y"),
            end=END_MARKER,
        )
        self._history: list[ChatMessage] = []

    def reply(self, agent_text: str | None) -> tuple[str, str]:
        """The persona's next message and its language.

        `agent_text` is None for the opening message (the caller speaks
        first, like on a real call after the greeting).
        """
        opening = "(the call starts; greet and state your need)"
        prompt = agent_text if agent_text is not None else opening
        self._history.append(ChatMessage(role="user", content=prompt))
        raw = self._provider.complete(self._system, self._history, []).text.strip()
        self._history.append(ChatMessage(role="assistant", content=raw))

        if END_MARKER in raw:
            return END_MARKER, self._last_language
        text, language = self._split_language(raw)
        self._last_language = language
        return text, language

    def _split_language(self, raw: str) -> tuple[str, str]:
        for lang in self._languages:
            prefix = f"{lang}:"
            if raw.lower().startswith(prefix):
                return raw[len(prefix):].strip(), lang
        # The persona forgot the protocol; recover from the text itself.
        return raw, detect_language(
            raw, languages=self._languages, fallback=self._last_language
        )
