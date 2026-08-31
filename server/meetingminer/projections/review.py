"""What a projected row says about its own review status (AD-18).

AD-18 forbids unreviewed output that reads the same as reviewed output. Once a
row can reach a store without passing the publish gate — which story 12.4 made
true for extraction documents — that rule stops being satisfiable by "only
approved things are in the index" and has to be satisfied by the record: a row
states its own status, and every surface that renders one renders what it was
given rather than remembering to add a caveat.

**Generic on purpose, and this is the reason.** Story 12.4 needed this for
extraction documents, which have no lifecycle at all. Story 12.5 needs the same
marking for artifacts indexed before publish, which have a real one
(``extracted → approved → published``) and, unlike a document, are genuinely
citable. Those are different rows with the same obligation, so what travels in
the record is **which state the row is in**, not the boolean fact that it is
unreviewed. A constant baked into a documents-only code path would have made the
second story a copy of the first, and two copies of a rule are two rules.

Three fields plus a sentence, and each does a job the others cannot:

* ``reviewState`` is a closed value a **filter** can pin. It is the row's actual
  lifecycle state where it has one, and :data:`NO_LIFECYCLE` where it has none.
* ``authorship`` says **who wrote it**, which is not the same question. A
  machine-written row that a human later approved is still machine-written, and
  a reader weighing it wants both facts.
* ``citable`` says whether the row may be a **citation target** (AD-6). It is
  not derivable from the state: a published artifact is citable because it
  anchors to a moment, and an extraction document is not citable in *any*
  state, because it is a claim about evidence rather than evidence.
* ``reviewLabel`` is the **words a person reads**, composed here so two surfaces
  cannot describe the same row differently.

Pure by construction, like :mod:`publish_gate`: no store client, no database,
no config. Everything a caller has to be careful about is decidable here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# The state of a row that has no lifecycle to be in. An extraction document is
# the case: nothing approves one, because there is no `extracted → approved →
# published` sequence behind it to move through. Distinct from `'extracted'`,
# which is a real state a real lifecycle starts in — an artifact sitting there
# is awaiting a human, while a document is not waiting for anything.
NO_LIFECYCLE = "unreviewed"

# Who wrote the row.
MACHINE = "machine"
HUMAN_APPROVED = "human-approved"
AUTHORSHIPS: frozenset[str] = frozenset({MACHINE, HUMAN_APPROVED})

# The states in which a human has actually accepted the content. Named as a set
# rather than tested against a single string so a caller reads "is this
# reviewed" instead of "is this equal to published", which is the question that
# would go stale if the lifecycle ever gained a state.
REVIEWED_STATES: frozenset[str] = frozenset({"approved", "published"})

# Every key a marking writes into a record. Named once so the guard, the
# consumers and the tests that pin them all read the same list.
REVIEW_KEYS: tuple[str, ...] = ("reviewState", "authorship", "reviewLabel", "citable")

# The sentence for each state, minus the citability clause. `NO_LIFECYCLE`
# leads with "unreviewed" and says so twice — once as a word a reader scans for
# and once as the fact — because it is the state whose row reached the index
# without any human in the path at all.
_STATE_SENTENCES: Mapping[str, str] = {
    NO_LIFECYCLE: "Unreviewed — machine-written {subject}. No human approved this text",
    "extracted": "Unreviewed — machine-written {subject}. No human has approved it yet",
    "approved": "Approved but not published — a human accepted this {subject},"
    " and it is not part of the published record",
    "published": "Published — a human approved this {subject} and published it",
}
_MACHINE_WRITTEN_STATES: frozenset[str] = frozenset({NO_LIFECYCLE, "extracted"})


class ReviewMarkingRefused(RuntimeError):
    """A record was built without a usable review marking.

    A named refusal, not a bug. Indexing a row that cannot say whether anybody
    reviewed it is an AD-18 violation — it would read exactly like a row
    somebody did review — so it is refused before a store sees it.
    """


@dataclass(frozen=True)
class ReviewMarking:
    """What one row says about its own review status, ready to write."""

    review_state: str
    authorship: str
    review_label: str
    citable: bool

    @property
    def reviewed(self) -> bool:
        """Whether a human actually accepted this row's content."""
        return self.review_state in REVIEWED_STATES

    def as_record_fields(self) -> dict[str, Any]:
        return {
            "reviewState": self.review_state,
            "authorship": self.authorship,
            "reviewLabel": self.review_label,
            "citable": self.citable,
        }


def marking(
    *,
    review_state: str,
    authorship: str,
    citable: bool,
    subject: str,
) -> ReviewMarking:
    """Compose the marking a row in ``review_state`` carries.

    ``subject`` is the noun the sentence is about ("extraction output", "action
    item"), so one composed sentence serves rows that are not the same kind of
    thing without either of them reading as the other.

    The citability clause is appended rather than implied. "Not citable
    evidence" is the single most consequential thing a reader can know about a
    row that reached the index ungated, and leaving it to be inferred from the
    absence of a moment id would leave it inferred by nobody.
    """
    template = _STATE_SENTENCES.get(review_state)
    if template is None:
        raise ReviewMarkingRefused(
            f"no review sentence is defined for state {review_state!r} — a row"
            f" may only report {', '.join(sorted(_STATE_SENTENCES))}, and"
            " indexing one that reports something else would put a status in"
            " front of a reader that this system cannot explain (AD-18)"
        )
    if authorship not in AUTHORSHIPS:
        raise ReviewMarkingRefused(
            f"no review sentence is defined for authorship {authorship!r} — a"
            f" row may only report {', '.join(sorted(AUTHORSHIPS))} (AD-18)"
        )
    if review_state in _MACHINE_WRITTEN_STATES and authorship != MACHINE:
        raise ReviewMarkingRefused(
            f"state {review_state!r} is described as machine-written, so it"
            f" cannot carry authorship {authorship!r} (AD-18)"
        )
    if not subject.strip():
        raise ReviewMarkingRefused(
            "a review marking needs a subject noun to describe; an empty one"
            " produces a sentence that names nothing"
        )
    clause = "" if citable else ", and it is not citable evidence"
    return ReviewMarking(
        review_state=review_state,
        authorship=authorship,
        review_label=f"{template.format(subject=subject.strip())}{clause}.",
        citable=citable,
    )


def apply_marking(record: dict[str, Any], value: ReviewMarking) -> dict[str, Any]:
    """Write a marking's four fields onto a record, in place, and return it."""
    record.update(value.as_record_fields())
    return record


def assert_carries_marking(record: Mapping[str, Any]) -> None:
    """Refuse a record that cannot say whether anybody reviewed it.

    The **generic** guard: it checks that the four fields are present, that the
    state is one this module can explain, that the label is not blank and that
    ``citable`` is a real boolean. It deliberately does **not** decide *which*
    state a given row type may report — that is the row type's own rule, and
    an extraction document's ("never anything but unreviewed") is not an
    artifact's ("whichever state its lifecycle is actually in").
    """
    missing = [key for key in REVIEW_KEYS if key not in record]
    if missing:
        raise ReviewMarkingRefused(
            "a projected record is missing "
            + ", ".join(repr(key) for key in missing)
            + " — a row that can reach a store without passing the publish gate"
            " must carry its review status in the record itself, or it reads"
            " exactly like a row somebody reviewed (AD-18)"
        )
    state = record["reviewState"]
    if state not in _STATE_SENTENCES:
        raise ReviewMarkingRefused(
            f"a projected record reports reviewState {state!r}, which is not a"
            f" state this system can explain to a reader — the known states are"
            f" {', '.join(sorted(_STATE_SENTENCES))} (AD-18)"
        )
    authorship = record["authorship"]
    if authorship not in AUTHORSHIPS:
        raise ReviewMarkingRefused(
            f"a projected record reports authorship {authorship!r}, which is"
            f" not one this system can explain — the known values are"
            f" {', '.join(sorted(AUTHORSHIPS))} (AD-18)"
        )
    if state in _MACHINE_WRITTEN_STATES and authorship != MACHINE:
        raise ReviewMarkingRefused(
            f"a projected record reports state {state!r}, whose label says"
            f" machine-written, with authorship {authorship!r} (AD-18)"
        )
    if not str(record["reviewLabel"]).strip():
        raise ReviewMarkingRefused(
            "a projected record carries an empty reviewLabel — the sentence a"
            " surface renders lives in the record, so a blank one lets the row"
            " render indistinguishably from reviewed output (AD-18)"
        )
    if not isinstance(record["citable"], bool):
        raise ReviewMarkingRefused(
            f"a projected record carries citable {record['citable']!r} — whether"
            " a row may be a citation target is a fact, not a hint, and a"
            " consumer reads it to decide whether to cite (AD-6)"
        )
