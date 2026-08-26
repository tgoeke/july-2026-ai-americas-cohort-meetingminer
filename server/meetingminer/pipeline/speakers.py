"""Turning a speaker label into an identity, or honestly refusing to.

Pure functions over strings and a roster: no database, no drop, no model call.
Every rule here was forced by observed transcript data, and every one of them
is unit-testable on its own.

The never-guess constraint is the whole point. One legacy file mixes
``Whitmore, Ellis`` with bare ``Ellis``, two different Kendalls, and an
unresolvable ``Speaker 8``. Corpus-wide, ``Ellis`` identifies nobody; inside one
meeting's roster it usually identifies exactly one person. So resolution is
**scoped to that meeting's roster** — and a label matching two roster entries
stays ``ambiguous`` rather than picking the first, because a wrong attribution
is worse than an absent one.

Two keys come out of this module and they are not the same thing. The *match
key* is a normalized display name, and it is what a transcript label is matched
against inside one meeting's roster. The *identity key* is what a person is
upserted by across meetings: their mail when the participant graph supplies one
(nearly every person-row carries it, from the SharePoint user-profile service — no
Microsoft Graph call, so the SPEC non-goal is untouched), and the normalized
name for the rows that do not. The worker resolves the identity key through the
API-owned alias table before any insert, which is what makes an Epic-2 human
merge survive re-ingest.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

# Resolution outcomes, as recorded on `transcript_segment.speaker_resolution`.
RESOLVED = "resolved"
UNRESOLVED = "unresolved"
AMBIGUOUS = "ambiguous"
PLACEHOLDER = "placeholder"
RESOLUTIONS = (RESOLVED, UNRESOLVED, AMBIGUOUS, PLACEHOLDER)

# `(CNTR)`, `(Fenwick, Peyton)`, `[External]` — qualifiers Teams and the org
# chart wrap around a name. Stripped before comparison (AD-5).
_QUALIFIER = re.compile(r"[(\[][^)\]]*[)\]]")
_WHITESPACE = re.compile(r"\s+")
# Everything that separates name tokens: whitespace plus the punctuation that
# shows up inside initials and hyphenated names.
_TOKEN_SPLIT = re.compile(r"[^\w]+", re.UNICODE)

# `Speaker 2`, `SPEAKER_00`, `spk_1`, `Guest 1`, `Unknown`, `Unidentified
# speaker` — a label that names a slot rather than a person. Never becomes a
# participant.
#
# The separator class is not decoration. `normalize_display_name` splits tokens
# on non-word characters, and `_` is a word character, so `SPEAKER_00` survives
# normalization as one token. pyannote — the diarizer `diarize/port.py`
# documents — emits exactly that shape, so a pattern that only allowed a space
# would let a diarizer tag become a `participant` row and a *resolved*
# attribution, which is the wrong attribution never-guess exists to prevent.
_PLACEHOLDER_LABEL = re.compile(
    r"^(?:"
    r"(?:speaker|spk|guest|attendee|participant|unidentified)(?:[\s_-]*\w{1,3})?"
    r"|unknown(?:[\s_-]+speaker)?"
    r"|unidentified(?:[\s_-]+speaker)?"
    r")$"
)


@dataclass(frozen=True)
class LabelResolution:
    """What one label resolved to, and against which candidates.

    ``match_key`` is set only for :data:`RESOLVED`, and it is the roster's
    *match* key — a normalized display name — not the person's cross-meeting
    identity key, which a transcript label never carries. ``candidates`` is the
    roster keys the label matched — empty for unresolved and placeholder, two
    or more for ambiguous — so a reviewer can see *why* an attribution was
    refused rather than only that it was.
    """

    status: str
    match_key: str | None = None
    candidates: tuple[str, ...] = ()


def normalize_display_name(label: str) -> str:
    """Fold a display name to the form identity is compared on (AD-5).

    Unicode-normalized, parenthetical qualifiers stripped, ``Last, First``
    reordered to ``First Last``, whitespace collapsed, case-folded. Nothing
    else: this is a comparison key, not a prettifier, and the original label is
    stored verbatim beside it.
    """
    # U+0000 first: Postgres refuses it in text and jsonb alike, and this
    # value becomes `participant.identity_key` and `normalized_name`. NFKC
    # leaves it alone and `\s` does not match it, so without this a single NUL
    # in a speaker label fails the whole stage on the participant insert — the
    # meeting loses every transcript row to one bad byte.
    text = unicodedata.normalize("NFKC", (label or "").replace("\x00", ""))
    stripped = _WHITESPACE.sub(" ", _QUALIFIER.sub(" ", text)).strip()
    if not stripped:
        # The whole label was the qualifier — the corpus carries a real
        # `(Fenwick, Peyton)` speaker. Stripping it to nothing would lose a
        # person, so the wrapper comes off instead of the name.
        text = _WHITESPACE.sub(" ", text).strip().strip("()[]").strip()
    else:
        text = stripped
    text = text.strip().strip(",").strip()
    if "," in text:
        last, _, first = text.partition(",")
        last, first = last.strip(), first.strip()
        # Only a two-part `Last, First` reorders. Three commas is not a name
        # shape we know, so it is left alone rather than reassembled wrongly.
        if last and first and "," not in first:
            text = f"{first} {last}"
    return _WHITESPACE.sub(" ", text).strip().casefold()


def name_tokens(normalized: str) -> tuple[str, ...]:
    """The comparison tokens of an already-normalized name.

    Splitting on non-word characters is what makes ``T.G.`` and ``T G`` the
    same two tokens, so an initials label compares the same either way.
    """
    return tuple(token for token in _TOKEN_SPLIT.split(normalized) if token)


def is_placeholder_label(label: str) -> bool:
    """Whether this label names a slot rather than a person."""
    return bool(_PLACEHOLDER_LABEL.match(normalize_display_name(label)))


# Namespaces for `participant.identity_key` and the alias keys the API writes
# against it (AD-5). Two spaces, stated rather than inferred.
MAIL_NAMESPACE = "mail:"
NAME_NAMESPACE = "name:"


def identity_key_for(label: str, mail: str | None = None) -> str:
    """The cross-meeting identity key for one person.

    ``mail`` wins when the source supplies one; the normalized display name is
    the documented fallback for the rows that lack it.

    Mail is a real directory identifier and it does not require Microsoft
    Graph: the participant graph carries it on nearly every person-row,
    sourced from the SharePoint user-profile service. It is *not* the tenant
    login, which is an employee number — those two are different values and
    joining them misses.

    Keying on the name alone holds only while no two people share one. That is
    true of a single meeting's roster and false of the larger store upstream
    of it, and the failure is silent: two humans collapse onto one participant
    row, which is precisely the wrong attribution the never-guess constraint
    exists to prevent. A split is recoverable through the alias table; a silent
    merge is not, because nothing records that it happened.

    The two key spaces are namespaced rather than merely disjoint. ``@`` alone
    would separate them today, but the key is a UNIQUE column that the API
    writes alias rows against (AD-5), so which space a key belongs to is stated
    rather than inferred from its punctuation.
    """
    address = (mail or "").strip()
    if "@" in address:
        return f"{MAIL_NAMESPACE}{address.casefold()}"
    normalized = normalize_display_name(label)
    return f"{NAME_NAMESPACE}{normalized}" if normalized else ""


def _initials(normalized: str) -> tuple[str, ...]:
    return tuple(token[0] for token in name_tokens(normalized))


def resolve_label(label: str | None, roster: Iterable[str]) -> LabelResolution:
    """Resolve one speaker label against one meeting's roster of match keys.

    In order: a placeholder is a placeholder; an exact normalized match wins;
    then a bare single token (a first name, a last name) matches roster entries
    containing it; then an all-initials label matches by initials; then a
    multi-token label matches a roster entry that contains all its tokens.

    Exactly one match resolves. More than one is :data:`AMBIGUOUS` — never the
    first of them. None is :data:`UNRESOLVED`. Neither ever yields a
    participant id.
    """
    keys = _unique(roster)
    if label is None or not label.strip():
        return LabelResolution(status=PLACEHOLDER)
    if is_placeholder_label(label):
        return LabelResolution(status=PLACEHOLDER)

    key = normalize_display_name(label)
    if not key:  # pragma: no cover - a non-blank label always normalizes to something
        return LabelResolution(status=PLACEHOLDER)
    if key in keys:
        return LabelResolution(status=RESOLVED, match_key=key, candidates=(key,))

    tokens = name_tokens(key)
    if not tokens:  # pragma: no cover - guarded by the empty-key check above
        return LabelResolution(status=UNRESOLVED)

    if len(tokens) == 1:
        token = tokens[0]
        candidates = tuple(k for k in keys if token in name_tokens(k))
    elif all(len(token) == 1 for token in tokens):
        # `T.G.` / `T G`: initials only resolve inside a roster, and only when
        # the whole label is initials — a single bare letter is too weak to
        # identify anyone and falls through to the single-token path above.
        candidates = tuple(k for k in keys if _initials(k) == tokens)
    else:
        wanted = set(tokens)
        candidates = tuple(k for k in keys if wanted <= set(name_tokens(k)))

    if len(candidates) == 1:
        return LabelResolution(status=RESOLVED, match_key=candidates[0], candidates=candidates)
    if len(candidates) > 1:
        return LabelResolution(status=AMBIGUOUS, candidates=candidates)
    return LabelResolution(status=UNRESOLVED)


def _unique(roster: Iterable[str]) -> tuple[str, ...]:
    """The roster's keys, de-duplicated, in first-seen order."""
    seen: dict[str, None] = {}
    for key in roster:
        if key:
            seen.setdefault(key, None)
    return tuple(seen)


def roster_from_labels(labels: Sequence[str | None]) -> tuple[str, ...]:
    """The *match* keys a transcript's own speaker labels imply.

    Used when the drop carries no participant graph — the majority case in this
    corpus, because the puller does not yet bridge the graph into the drop.
    Placeholder labels are excluded: ``Speaker 8`` must never become a person.

    These are match keys, not identity keys: a transcript label never carries a
    mail address, so this is the space :func:`resolve_label` compares against.
    """
    keys: dict[str, None] = {}
    for label in labels:
        if label is None or not label.strip() or is_placeholder_label(label):
            continue
        key = normalize_display_name(label)
        if key:
            keys.setdefault(key, None)
    return tuple(keys)
