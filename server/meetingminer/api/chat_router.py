"""Question classification for ``POST /chat``: the model classifies, code
dispatches (AD-7, story 3.3).

AD-7 gives the model exactly two jobs on the chat path — pick a traversal
template, and synthesize the cited answer. This module owns the first one, and
owns it as a *pure* function: :func:`parse_route` takes the model's raw text and
returns a :class:`RouteDecision`. It reaches no store, imports no FastAPI, and
**never raises**. Anything the registry does not recognize — an unregistered
template name, a missing anchor, fenced JSON, prose, junk — becomes
``template=None``, which the orchestrator reads as "search only".

That degradation is the point. The classifier is the one place a model's output
decides which code runs, so a malformed reply must narrow what happens rather
than break the request: a question that could have been answered from the
full-text index still is.

**Anchors are natural language, not ids.** The model is asked for "Clarence" and
"the vendor portal screen", never a UUID — story 3.2's ``_input_uuid`` recorded
that "name-to-id resolution is the router's job". :data:`TEMPLATE_ANCHORS` maps
each registered template's anchor keys onto the Cypher parameter names
``run_template`` takes, so the two vocabularies stay separable and a template
added to the registry without anchors fails a test rather than a request.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from meetingminer.projections.traversals import (
    PARTICIPANT_TOPIC_MOMENTS,
    SCREEN_HISTORY,
    THREAD_TIMELINE,
    TRAVERSAL_TEMPLATES,
)

__all__ = [
    "CLASSIFIER_VALUE_MAX_LENGTH",
    "CLASSIFIER_PROMPT",
    "DEFERRED_TEMPLATES",
    "FALLBACK_REASONS",
    "RouteDecision",
    "TEMPLATE_ANCHORS",
    "build_classifier_prompt",
    "parse_route",
]


# Model output crosses into the index, Postgres LIKE predicates, and structured
# logs. Keep it within the same envelope the public question boundary permits.
CLASSIFIER_VALUE_MAX_LENGTH = 1_000


@dataclass(frozen=True)
class TemplateAnchors:
    """How one registered template's natural-language anchors reach its Cypher.

    ``resolved`` names the anchors deterministic code must turn into a
    Postgres-minted id before ``run_template`` sees them; ``literal`` names the
    ones that travel as the model wrote them (a topic is a substring match over
    ``Moment.text``, so there is nothing to resolve).
    """

    # anchor key on the wire -> the `run_template` keyword it becomes
    resolved: Mapping[str, str] = field(default_factory=dict)
    literal: Mapping[str, str] = field(default_factory=dict)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self.resolved) + tuple(self.literal)


# One entry per *routable* registered traversal (`test_chat_router.py` asserts
# that these anchors and `DEFERRED_TEMPLATES` together cover the whole registry,
# so 3.2's registry cannot grow a template this router would silently never
# dispatch).
TEMPLATE_ANCHORS: Mapping[str, TemplateAnchors] = {
    SCREEN_HISTORY: TemplateAnchors(resolved={"screen": "screen_id"}),
    PARTICIPANT_TOPIC_MOMENTS: TemplateAnchors(
        resolved={"participant": "participant_id"}, literal={"topic": "topic"}
    ),
}

# Registered traversals this router deliberately does not classify onto yet,
# each naming the story that will make it routable. Declared rather than merely
# absent, so "the registry grew a template and nobody wired it" and "the
# registry grew a template we chose not to wire yet" stay different facts and
# the coverage test keeps catching the first.
#
# `thread-timeline` (story 10.2) returns a `ThreadTimelineResult` — meetings
# carrying per-level aggregates — where `_traversal_leg` in `chat.py` reads
# `result.rows` and `result.screen`/`result.participant`. Giving it anchors
# today would let the classifier route a question onto a shape the orchestrator
# cannot read, turning a chat request into an AttributeError. Story 10.2b
# ("Thread Questions in Chat") is the story that adapts the orchestrator and
# adds the anchors. Until it lands, a model that names this template falls
# through `parse_route`'s registry check onto the search-only route — the
# module's designed degradation, not a new failure mode.
DEFERRED_TEMPLATES: Mapping[str, str] = {
    THREAD_TIMELINE: "story 10.2b — Thread Questions in Chat",
}

# Why a reply produced no template. Logged on every classification, so "the
# router degraded to search" is always accompanied by which of these it was.
FALLBACK_REASONS: tuple[str, ...] = (
    "unparsable",  # no JSON object could be recovered from the reply
    "not-an-object",  # valid JSON, but not an object
    "no-template",  # the model itself declined to name one
    "unregistered-template",  # a name TRAVERSAL_TEMPLATES does not hold
    "missing-anchor",  # a registered name whose anchors were absent or blank
)

# A fenced block or a bare reply is first tried as-is. Prose-wrapped objects are
# recovered separately with ``JSONDecoder.raw_decode`` below, which stops at the
# first complete object rather than concatenating two model-written objects.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class RouteDecision:
    """What the classifier decided, after code checked every part of it.

    ``template`` is ``None`` whenever the reply could not be turned into a
    registered dispatch — the search-only route. ``anchors`` holds the
    natural-language values keyed by anchor name; the orchestrator resolves them
    against Postgres. ``search_terms`` is what the search leg queries with; it
    falls back to the question when the model offered nothing usable.
    """

    template: str | None
    anchors: Mapping[str, str]
    search_terms: str | None
    fallback_reason: str | None
    raw: str


CLASSIFIER_PROMPT = """\
You classify a question about a corpus of recorded meetings onto one of a fixed
set of retrieval templates. You do not answer the question.

Reply with a single JSON object and nothing else. No prose, no code fence.

The templates:

- "participant-topic-moments" — the question asks what a *named person* was
  present for on some subject ("did I already explain the SFTP migration to
  Clarence?", "which moments did Ellis witness the purchase-order flow in?").
  Anchors: "participant" (the person's name, exactly as the question writes it)
  and "topic" (a short subject phrase, two or three words, using wording likely
  to appear in the meeting transcript).
- "screen-history" — the question asks about a *screen or slide* over time
  ("every time the vendor portal came up", "when did we last look at the
  reconciliation queue?"). Anchor: "screen" (the screen's name as the question
  writes it).

If the question fits neither — a general question about what was said, decided,
or discussed — set "template" to null.

Always include "searchTerms": the words to run against a full-text index of the
meeting transcripts, drawn from the question. Keep it short and keep the
question's own vocabulary.

The exact shape:

{{"template": "participant-topic-moments" | "screen-history" | null,
 "participant": "...", "topic": "...", "screen": "...",
 "searchTerms": "..."}}

Include only the anchor keys the template you chose declares.

Question:
{question}
"""


def build_classifier_prompt(question: str) -> str:
    """The classification prompt for one question.

    ``str.format`` rather than an f-string so the literal braces of the example
    JSON stay in the template and are doubled once, in one place.
    """
    return CLASSIFIER_PROMPT.format(question=question.strip())


def _json_candidates(raw: str) -> list[str]:
    """Every substring of a model reply worth trying to parse, best first."""
    candidates: list[str] = []
    for fenced in _FENCE.findall(raw):
        candidates.append(fenced.strip())
    stripped = raw.strip()
    if stripped:
        candidates.append(stripped)
    return candidates


# Distinguishable from a decoded JSON `null`, which is a reply the model
# *made* (and lands under `not-an-object`) rather than one nothing could be
# recovered from.
_UNPARSED = object()


def _decoded(raw: str) -> Any:
    for candidate in _json_candidates(raw):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(raw, index)
            return value
        except json.JSONDecodeError:
            continue
    return _UNPARSED


def _text(value: Any) -> str | None:
    """A non-blank string, or None — the only anchor shape code will dispatch."""
    if isinstance(value, str):
        text = value.strip()
        if text and len(text) <= CLASSIFIER_VALUE_MAX_LENGTH:
            return text
    return None


def _search_only(raw: str, reason: str, search_terms: str | None = None) -> RouteDecision:
    return RouteDecision(
        template=None,
        anchors={},
        search_terms=search_terms,
        fallback_reason=reason,
        raw=raw,
    )


def parse_route(raw: str) -> RouteDecision:
    """Turn one classifier reply into a decision code is willing to dispatch.

    Never raises. Every path that cannot produce a registered template with
    every declared anchor present returns the search-only decision carrying the
    :data:`FALLBACK_REASONS` entry that says which path it was.
    """
    decoded = _decoded(raw)
    if decoded is _UNPARSED:
        return _search_only(raw, "unparsable")
    if not isinstance(decoded, dict):
        return _search_only(raw, "not-an-object")

    # `searchTerms` is salvaged even when the template half of the reply is
    # unusable: a reply naming a nonexistent template still told us what the
    # question is about, and throwing that away would make the fallback worse
    # than it has to be.
    search_terms = _text(decoded.get("searchTerms")) or _text(decoded.get("search_terms"))

    name = _text(decoded.get("template"))
    if name is None:
        return _search_only(raw, "no-template", search_terms)
    if name not in TRAVERSAL_TEMPLATES or name not in TEMPLATE_ANCHORS:
        return _search_only(raw, "unregistered-template", search_terms)

    declared = TEMPLATE_ANCHORS[name]
    anchors: dict[str, str] = {}
    for key in declared.keys:
        value = _text(decoded.get(key))
        if value is None:
            # A template dispatched without every anchor would either raise
            # ProjectionError inside `run_template` or — worse for
            # participant-topic — anchor on a blank topic that matches the
            # whole corpus. Neither is a routing decision; both are refusals.
            return _search_only(raw, "missing-anchor", search_terms)
        anchors[key] = value

    return RouteDecision(
        template=name,
        anchors=anchors,
        search_terms=search_terms,
        fallback_reason=None,
        raw=raw,
    )
