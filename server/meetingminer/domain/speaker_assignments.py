"""The namespace a speaker assignment is recorded in (story 7.3, AD-5).

A curator naming a voice writes an api-owned ``participant_alias`` row whose
``alias_key`` is ``speaker:<meetingId>:<tag>``. ``align`` reads that key back
before it writes a segment, which is what makes an assignment survive every
later rerun and re-ingest — the same mechanism an Epic-2 merge already uses,
in a third key space beside ``mail:`` and ``name:``
(``pipeline/speakers.MAIL_NAMESPACE`` / ``NAME_NAMESPACE``).

It lives in ``domain`` because both sides need it and neither may reach the
other: the api writes the key and never imports ``pipeline``
(``api/ingests.py``), while ``pipeline/stages/align.py`` reads it and may not
import ``api``. One definition, per AGENTS.md's shared-addition rule — two
spellings of this key would be silent, because a mismatched key simply never
matches and the assignment would look accepted and do nothing.

The key space is disjoint from the other two by construction: a roster
identity key is ``mail:…`` or ``name:…``, so no speaker assignment can ever
collide with a merge record, and ``align`` can tell the two lookups apart by
which key it asked for rather than by inspecting the row.
"""

from __future__ import annotations

from uuid import UUID

# The third alias-key space. Named here rather than inferred from punctuation,
# for the reason migration 0005 gives about `mail:` and `name:`.
SPEAKER_NAMESPACE = "speaker:"

# The identity space a curator's *typed* name is minted into — a fourth key
# space, and deliberately not `SPEAKER_NAMESPACE`.
#
# The two must differ. A merge records `alias_key = <absorbed>.identity_key`,
# and `api/participants.py` reads "this participant was merged away" as "its
# identity key appears as some row's alias key". If a minted participant's
# identity key were also the key its own speaker assignment is stored under,
# that assignment would read as a merge record of the person it names: the row
# could never be merged (`already-merged`, from its own assignment) and the
# recovery path for a split would be closed. Keeping them apart leaves
# `POST /participants/{id}/merge` working on exactly these rows, which is the
# documented cure for the same human being typed into two meetings.
CURATED_NAMESPACE = "curated:"


def speaker_alias_key(meeting_id: UUID | str, tag: str) -> str:
    """The alias key one meeting's speaker tag is assigned under.

    ``tag`` is the label **verbatim** — exactly the string
    ``transcript_segment.speaker_label`` holds and ``GET
    /meetings/{id}/speakers`` returns as ``speakerLabel``. It is deliberately
    not normalized: the label is evidence, the reader recognizes it in the
    transcript beside the row, and normalizing here would make two visibly
    different tags share one assignment.

    Scoped to the meeting because a diarizer's ``SPEAKER_00`` is
    recording-local — the same tag names a different person in the next
    meeting, so a cross-meeting key would be exactly the wrong attribution
    AD-13 exists to prevent.
    """
    return f"{SPEAKER_NAMESPACE}{meeting_id}:{tag}"


def curated_identity_key(meeting_id: UUID | str, tag: str) -> str:
    """``participant.identity_key`` for a person a curator typed by hand.

    Scoped to the meeting and tag for the same reason the assignment is, and
    kept out of ``pipeline/speakers.py``'s ``name:<normalized>`` space on
    purpose: the api cannot compute that space's key without a second copy of
    ``normalize_display_name``, and two spellings of an identity key produce
    silent wrong merges. A key that cannot collide with a roster match key
    can only ever *split* one person across two rows, which is the recoverable
    direction, and `POST /participants/{id}/merge` recovers it.
    """
    return f"{CURATED_NAMESPACE}{meeting_id}:{tag}"
