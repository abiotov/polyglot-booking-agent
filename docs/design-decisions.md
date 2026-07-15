# Design decisions

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

## 7. Frozen models, strict typing, property-based tests

**Decision.** All domain models are immutable pydantic models; mypy runs
strict; invariants are tested with Hypothesis, not only examples.

**Why.** The engine is the trust anchor of the whole system. Immutability
removes a class of aliasing bugs, strict typing catches interface drift
when the agent and adapters land, and property-based tests state the
actual guarantees ("offered slots are always free", "no avoidable
fragmentation") instead of sampling them.
