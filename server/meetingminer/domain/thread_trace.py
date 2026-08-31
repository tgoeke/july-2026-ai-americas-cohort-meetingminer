"""The rules behind tracing one subject across meetings (story 10.7, FR42/FR43).

Story 10.3's timeline serves one *derived thread* at four levels of detail.
This module owns the decisions behind the other way in — the reader names a
subject and gets every meeting where it surfaced — and it owns them here,
database-free and model-free, so each is a unit test rather than a property of
a SQL string.

Three rules live here because each one is a judgement the acceptance criteria
make explicitly, and each is wrong in a way that is invisible from the outside
if it drifts:

**Suggestions rank by calendar span over a middling meeting count, never by
mention frequency.** The most-mentioned subjects are the generic ones: they
appear in nearly every meeting, so their "thread" is the whole corpus and no
story at all. A subject worth tracing is specific enough to be one concern and
recurrent enough to have a history, which is a band on the meeting count and a
sort on the days it spans.

**Near-duplicates are dropped.** "Scorecard" and "Scorecards" are one concern,
and offering both spends two of six slots on the same trace. So is a name that
merely extends one already chosen — "Division Lead" after "Lead".

**Completeness is stated in words, always.** A top-k sample presented as a full
history is the same unverified-absence failure as claiming no recording exists
(AD-18), and it is worse here than anywhere else in the product: this is the
one view whose entire claim is that it shows the corpus's true shape over time.
So the wording is a function of the counts rather than prose written at the
call site, and the note can never say "every mention" for a capped or sampled
result.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Sequence

#: Moments quoted at each stop. The cap is **per meeting, never overall**: an
#: overall limit cuts the tail off a long-running subject and shows the first
#: months as though they were the whole history. Every meeting that mentions
#: the subject stays a stop; only the quoting is limited, and both figures are
#: reported. A shorter timeline is comprehensible; one with holes in it is not.
PER_MEETING_DEFAULT = 6

#: How many subjects the empty state offers.
SUGGESTION_LIMIT_DEFAULT = 6

#: The band a suggestion's meeting count must fall in.
#:
#: The floor is 2 rather than something more comfortably "middling" because of
#: what the derivation actually produces: on the corpus of 2026-08-31, 976 of
#: 1,090 threads involve exactly one meeting. A one-meeting row is not a thread
#: by ``domain/threads.py``'s own definition — it is a durable identity kept as
#: a reuse target — so 2 is the first count that is a thread at all, and the
#: span sort below does the work of picking the ones worth tracing.
SUGGESTION_MIN_MEETINGS = 2

#: The ceiling that excludes the generic subjects. A concern in more meetings
#: than this is a property of the corpus rather than a story inside it.
SUGGESTION_MAX_MEETINGS = 45

#: A subject that came and went inside a fortnight has no history to fly along.
SUGGESTION_MIN_SPAN_DAYS = 14

#: How many adjacent candidates a wording is offered, when it matches several.
CANDIDATE_LIMIT = 8

#: Non-alphanumerics, for the duplicate key below.
_NOISE = re.compile(r"[^a-z0-9]+")


def span_days(first: datetime, last: datetime) -> int:
    """Whole days from the first mention to the last, never negative."""
    return max(0, round((last - first).total_seconds() / 86400.0))


def duplicate_key(name: str) -> str:
    """The form two spellings of one concern share.

    Case, punctuation, spacing and a single trailing plural are all noise for
    this purpose. The key is deliberately lossy: it exists to decide whether
    two suggestions would send the reader to the same place, not to decide
    whether two subjects are the same subject — that judgement belongs to
    ``domain/threads.py``, which has embeddings and made it already.
    """
    return _NOISE.sub("", name.lower()).removesuffix("s")


def drop_near_duplicates(names: Sequence[str], *, limit: int) -> list[int]:
    """Indices of the names worth keeping, in the order given, at most `limit`.

    Returns indices rather than names so a caller can carry whatever row the
    name came from without this module knowing anything about it.

    Two tests are applied, and the second is the one that is easy to forget: a
    name is dropped when it shares a duplicate key with something already
    kept, **and** when it merely contains, or is contained by, a name already
    kept. Containment is what catches "Division Lead" after "Lead", which the
    key test alone lets through because the two normalize differently.
    """
    kept: list[int] = []
    kept_lower: list[str] = []
    seen: set[str] = set()
    for index, name in enumerate(names):
        if len(kept) >= limit:
            break
        key = duplicate_key(name)
        if not key or key in seen:
            continue
        lower = name.lower()
        if any(lower in other or other in lower for other in kept_lower):
            continue
        seen.add(key)
        kept_lower.append(lower)
        kept.append(index)
    return kept


def completeness_note(
    *,
    mode: Literal["exhaustive", "sample"],
    stops: int,
    moments_quoted: int,
    mention_total: int,
    meetings_mentioning: int,
    per_meeting: int,
    ranking: str | None = None,
) -> str:
    """What is on screen, and whether it is all of it.

    Derived from the counts rather than written at the call site, so the two
    legs cannot drift into describing themselves the same way — which is the
    whole failure this sentence exists to prevent.
    """
    if mode == "sample":
        if stops == 0:
            return (
                "Nothing in the corpus matches this wording. Nothing is shown"
                " rather than a nearest guess."
            )
        how = f" by {ranking} ranking" if ranking else ""
        return (
            f"The {moments_quoted} best-matching moments for this wording{how},"
            f" re-sorted by date across {stops}"
            f" meeting{'' if stops == 1 else 's'}. This is a sample, not every"
            " mention — name a subject exactly for an exhaustive trace."
        )
    if stops == 0:
        return "This subject has no mentions the corpus can place on a timeline."
    if moments_quoted >= mention_total:
        return (
            f"Every mention this corpus holds: {mention_total}"
            f" moment{'' if mention_total == 1 else 's'} across all"
            f" {meetings_mentioning} meeting"
            f"{'' if meetings_mentioning == 1 else 's'} that mention it."
        )
    return (
        f"{moments_quoted} of {mention_total} moments, quoting at most"
        f" {per_meeting} per meeting so that all {meetings_mentioning} meetings"
        " that mention it stay on the timeline. The span is the true span; only"
        " the quoting is capped."
    )
