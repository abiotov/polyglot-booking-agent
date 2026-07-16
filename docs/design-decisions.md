# Design decisions

🇫🇷 [Version française](design-decisions.fr.md)

> The reasoning behind the choices that shape this project. Each entry
> states the decision, the alternatives considered, and why.

## 1. The LLM never picks a slot

**Decision.** Availability and ranking are computed by a deterministic
engine. The LLM interacts with it only through strictly validated tools
and books only `slot_id`s the engine returned.

**Alternative considered.** Give the LLM the day's calendar as text and
let it reason about availability.

**Why.** LLMs are excellent at understanding "somewhere at the end of the
week, but not Friday" and unreliable at interval arithmetic under
pressure. A hallucinated double-booking is a catastrophic failure for a
practice. With the tool boundary, the worst the LLM can do is converse
poorly; it cannot corrupt the calendar. It also makes every booking
auditable: replay the tool-call trace and you can prove why a slot was
offered.

## 2. Compaction scoring instead of "first free slot"

**Decision.** Free slots are ranked by adjacency to existing
appointments; isolated slots come last.

**Why.** Offering the first free slot shreds a practitioner's day into
unusable 15-minute holes. An experienced receptionist books against the
edges of existing appointments to keep the day compact. Encoding that
as a scoring function (rather than prompt instructions) makes the
behavior testable: a Hypothesis property asserts that no random calendar
state ever produces avoidable fragmentation.

## 3. CalDAV as the single source of truth, no shadow database

**Decision.** The practice calendar (Radicale in development, iCloud or
Google in production) holds all booking state. The engine receives busy
intervals read live from it.

**Alternative considered.** Mirror the calendar into a local database and
sync periodically.

**Why.** A mirror invites drift, and drift means double-bookings. More
importantly, practitioners already manage their calendar by hand and must
keep that power: block a slot, move an appointment, close an afternoon,
from their own phone, with no new tool to learn. CalDAV is an open
standard, so the adapter written against Radicale works against any
production server, and local development costs nothing.

## 4. Read-before-write on every booking

**Decision.** Immediately before writing an event, the adapter re-reads
the target slot. If it is no longer free, the booking is refused and the
agent re-offers.

**Why.** The practitioner can take or block a slot from their phone while
a caller is on the line. This race is real and unavoidable; the only
correct behavior is to detect it at write time and recover
conversationally ("that slot was just taken, I can offer 9:30 instead").

## 5. Provider adapters everywhere

**Decision.** LLM, STT, TTS, telephony and calendar are each behind a
small interface with at least two implementations planned (one hosted,
one local or free).

**Why.** Three reasons. No vendor lock-in for anyone deploying the
project. A zero-cost development path (Radicale, Piper, free tiers) that
keeps the project demoable by anyone. And honest benchmarking: swapping a
provider is an environment variable, so comparisons are cheap.

## 6. Naive local time inside the engine

**Decision.** The engine works in naive datetimes interpreted in the
practice timezone; the calendar adapter owns all timezone conversion.

**Why.** A practice schedule is inherently local ("we open at 08:00").
Pushing timezone handling to the I/O boundary keeps the pure core simple
and keeps DST bugs in one auditable place.

## 7. Language switching is tagged by the channel, not guessed by the model

**Decision.** Each caller utterance carries a `[lang=xx]` tag injected
by the harness (from the STT's per-utterance language detection in
voice channels). The system prompt declares the tag authoritative for
the reply language.

**Alternative considered.** Instruct the model to detect and follow the
caller's language by itself.

**Why.** Live tests were unambiguous: with prompt instructions alone,
both gpt-4o-mini and gemini-2.5-flash kept answering in French after
the caller switched to English, because the conversation history
outweighed the instruction. A deterministic tag from the transcription
layer fixed it immediately. Same philosophy as the scheduling boundary:
whenever a behavior must be reliable, move it from the prompt into the
harness. The TTS voice will be selected from the same tag.

## 8. Real sessions are the test suite the lab cannot write

**Decision.** Every live session on the Telegram channel is analyzed
from its operational logs and the raw calendar state; each failure
becomes a code-level guard, never just a prompt tweak.

**What the first real sessions taught, and what each lesson became:**

| Observed live | Shipped guard |
| --- | --- |
| Appointment saved with an empty patient name | book() validates identity content, not just schema presence |
| Duplicate bookings piling up, caller unable to see or cancel them | find_bookings(phone) tool closes the check/cancel/move loop |
| 11s STT latency per clip | Persistent HTTP clients (measured 3.0s to 0.4s) |
| Short clips lost or detected as German | Detection restricted to the practice's languages |
| "Ce serait le mardi" heard as "Se croire le mardi" | nova-3 multilingual mode, dominant word language |
| A French clip transcribed in Mandarin | Non-Latin transcripts rejected and retried with forced language |
| httpx.ReadTimeout silently ate a turn | Widened Telegram timeouts + always-reply error handler |

Realtime (console) sessions added their own rows:

| Observed live | Shipped guard |
| --- | --- |
| Turns transcribed but never answered | Session-level LLM placeholder (livekit skips generation when llm is None, even with llm_node overridden) |
| 12.7s transcript delay | Bluetooth headset mic identified; wired mic brought it to ~0.5s |
| 5-13s of dead air during tool rounds | Event-driven brain turns + spoken filler ("un instant, je consulte le planning") |
| A French turn transcribed in Japanese reached the brain | mostly_latin guard shared across channels; realtime asks to repeat |
| Garbled identity ("Bon nom complique ben jao") booked | Spell-out names, digit-by-digit phones, mandatory read-back; the digit correction loop worked in the very next session |

Then the eval harness (phase 5) industrialized the loop and added:

| Caught by a campaign | Shipped guard |
| --- | --- |
| Caller gave a local-format number ('94 22 11 00'); strict-equality lookup missed the booking and a duplicate was created | Suffix-based phones_match shared adapter-wide, regression-tested |
| No day given by the caller: the agent silently booked TODAY | Prompt: ask for the day, never assume |
| Agent advised a caller to "contact the practice" (it IS the practice) | Prompt: you are the reception, offer what you can do |
| Checks stricter than the architecture (guard-refused ranking flagged; caller-echoed times flagged) | Checks calibrated: refusals are the guard working; echoing the caller is conversation |

**Why it matters.** Synthetic audio (TTS-generated test clips) passes
where real phone microphones fail. The lab round trip validated the
pipeline; only production sessions surfaced these seven failures. The
eval harness (phase 5) will automate part of this, but the principle
stands: judge the system on its logs and its persisted state, not on
its replies.

## 9. The realtime channel borrows LiveKit's body, never its brain

**Decision.** The LiveKit channel overrides `Agent.llm_node` so the
project's BookingAgent produces every reply; LiveKit supplies mic, VAD,
streaming STT, barge-in and TTS playback only.

**Alternative considered.** Use LiveKit's own agent loop with its LLM
plugin and re-register the booking tools as LiveKit function tools.

**Why.** That would mean two brains: two tool registries, two prompt
sets, two behaviors to test and to drift apart. With the override there
is one brain shared by CLI, Telegram and realtime, and everything the
test suite proves about it holds on every channel. The accepted cost is
that the reply reaches TTS as one chunk instead of streaming token by
token (about a second of latency), compensated by the spoken filler
during tool rounds.

## 10. Frozen models, strict typing, property-based tests

**Decision.** All domain models are immutable pydantic models; mypy runs
strict; invariants are tested with Hypothesis, not only examples.

**Why.** The engine is the trust anchor of the whole system. Immutability
removes a class of aliasing bugs, strict typing catches interface drift
when the agent and adapters land, and property-based tests state the
actual guarantees ("offered slots are always free", "no avoidable
fragmentation") instead of sampling them.
