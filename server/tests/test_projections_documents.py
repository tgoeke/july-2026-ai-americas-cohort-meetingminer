"""Extraction documents in the projection: the gate exception and its two limits.

Story 12.4 makes every extraction document searchable the moment it is stored,
approved or not — the first deliberate exception to the publish gate in this
build (owner ruling 2026-08-31, AD-4). An exception that is only prose is one a
later change erodes without noticing, so this file is where the two constraints
that ride with it are falsifiable:

* **The exception is to reach, never to legibility.** A document carries its
  unreviewed, machine-written status *in the indexed record itself* (AD-18).
  The tests below pin that in the record — not in the UI — which is what the
  story asks for, and ``test_projections_search.py`` pins it again in the store
  the record actually lands in.
* **A document is never a citation target** (AD-6). Pinned three ways here: the
  record builder refuses a citation field, the query lane's hit type has
  nowhere to put one, and the config loader refuses an index that would make
  one filterable. ``test_chat_citations.py`` pins the fourth and last way — the
  gate itself cannot resolve one.

Store-free by construction, like ``test_chat_citations.py``: everything the
exception has to be careful about lives in a pure module, so it can be proved
without Postgres, Meilisearch or a model.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
import yaml

from meetingminer.api.search import DocumentHitModel, SearchResponse
from meetingminer.config import AppConfig, ConfigError, load_config
from meetingminer.projections import documents as document_module
from meetingminer.projections import search as search_projection
from meetingminer.projections.documents import (
    AUTHORSHIP,
    DOCUMENTS_INDEX,
    FORBIDDEN_CITATION_KEYS,
    REVIEW_LABEL,
    REVIEW_STATE,
    DocumentRecordRefused,
    assert_carries_review_label,
    assert_not_citable,
    document_id,
    document_record,
)
from meetingminer.projections.evidence import ExtractionDocumentRow
from meetingminer.projections.publish_gate import (
    UNGATED_INDEXED_ROW_TYPES,
    PublishGateRefused,
    require_ungated,
)
from meetingminer.projections.query import (
    DOCUMENT_SEARCHABLE_INDEXES,
    DocumentHit,
    build_document_search_parameters,
)
from meetingminer.projections.review import (
    MACHINE,
    NO_LIFECYCLE,
    REVIEW_KEYS,
    ReviewMarkingRefused,
    apply_marking,
    assert_carries_marking,
    marking,
)

from repo_paths import REPO_ROOT

MEETING = UUID("018f3f2a-0000-7000-8000-0000000000f0")
ROW = UUID("018f3f2a-0000-7000-8000-0000000000d1")

SUMMARY = "# Architecture summary\n\nWe moved the feed to SFTP.\n"


def row(**overrides: object) -> ExtractionDocumentRow:
    fields: dict[str, object] = {
        "id": ROW,
        "kind": "arch-summary",
        "origin": "generated",
        "layout": "table",
        "item_count": 3,
        "artifact_count": 3,
        "byte_size": len(SUMMARY.encode("utf-8")),
        "sha256": "0" * 64,
        "text": SUMMARY,
        "model": "claude-sonnet-4",
        "prompt_version": 3,
        "prompt_hash": "abcdef0123456789",
    }
    fields.update(overrides)
    return ExtractionDocumentRow(**fields)  # type: ignore[arg-type]


def record(**overrides: object) -> dict[str, object]:
    return document_record(
        row(**overrides),
        meeting_id=MEETING,
        corpus="real",
        meeting_title="Weekly sync",
        source_id="drop-1",
    )


# --- the indexed identity: a build decision, stated and pinned -------------


def test_the_indexed_identity_is_the_extraction_source_row_id() -> None:
    """The build decision the story asks to be chosen, stated and pinned.

    ``chunking.py`` keys a chunk on its first transcript segment's UUID (AD-6)
    and a document has no transcript segment, so nothing forces this choice —
    a document is not citable, which is exactly why the identity is a build
    decision rather than an invariant. The decision is: **one indexed record
    per ``extraction_source`` row, keyed on that row's own UUID, unchunked.**

    Pinned here so a later reader does not have to infer it from the builder,
    and so a change to it is a deliberate edit of a test rather than a silent
    re-keying of the index.
    """
    assert document_id(row()) == str(ROW)
    assert record()["id"] == str(ROW)


def test_one_row_yields_exactly_one_record_however_long_the_document_is() -> None:
    """Unchunked, by the same decision.

    A long document is one record, not N. `extraction_source` carries
    `UNIQUE (meeting_id, kind)` and a rerun upserts that row rather than
    inserting a second, so a re-extraction *replaces* its record instead of
    accumulating one per run — which is what makes `rebuild` converge on
    exactly the rows Postgres holds.
    """
    long_document = "\n".join(f"- decision {n}" for n in range(5_000))
    built = record(text=long_document, byte_size=len(long_document.encode("utf-8")))
    assert built["text"] == long_document
    assert built["id"] == str(ROW)


def test_the_record_takes_no_identity_from_a_transcript_segment() -> None:
    """The story's own words: it takes *no* chunk identity from a segment.

    Stated as an absence over the whole record rather than as a check on `id`
    alone, because the failure this guards against is a later change adding a
    segment key beside the row id and quietly re-introducing a citation path.
    """
    built = record()
    assert "segmentIds" not in built
    assert "turnCount" not in built
    assert not any("segment" in key.lower() for key in built)


# --- AD-18: the label is in the record, not only in the UI -----------------


def test_every_record_carries_its_unreviewed_machine_written_label() -> None:
    """The exception is to reach, never to legibility (AD-18).

    Pinned *in the indexed record*, which is what the story requires — a UI
    that remembers to add a label is a UI one refactor away from forgetting.
    """
    built = record()
    assert built["reviewState"] == REVIEW_STATE == "unreviewed"
    assert built["authorship"] == AUTHORSHIP == "machine"
    assert built["reviewLabel"] == REVIEW_LABEL
    assert "unreviewed" in str(built["reviewLabel"]).lower()
    assert built["citable"] is False


@pytest.mark.parametrize(
    "key", ["reviewState", "authorship", "reviewLabel", "citable"]
)
def test_a_record_that_lost_a_review_field_is_refused(key: str) -> None:
    """Indexing an unlabelled document is an AD-18 violation, not a gap.

    So it is a named refusal before a store sees it, rather than a document
    that lands and reads exactly like reviewed output.
    """
    built = record()
    del built[key]
    with pytest.raises(DocumentRecordRefused) as exc:
        assert_carries_review_label(built)
    assert key in str(exc.value)


def test_a_record_claiming_to_be_reviewed_is_refused() -> None:
    """Nothing approves an extraction document, so no record may say one did."""
    built = record()
    built["reviewState"] = "approved"
    with pytest.raises(DocumentRecordRefused, match="unreviewed"):
        assert_carries_review_label(built)


def test_a_record_with_a_blank_label_is_refused() -> None:
    """The sentence a surface renders lives in the record, so it may not be blank."""
    built = record()
    built["reviewLabel"] = "   "
    with pytest.raises(DocumentRecordRefused, match="reviewLabel"):
        assert_carries_review_label(built)


def test_a_record_claiming_to_be_citable_is_refused() -> None:
    built = record()
    built["citable"] = True
    with pytest.raises(DocumentRecordRefused, match="citable"):
        assert_carries_review_label(built)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda built: built.pop("reviewLabel"),
        lambda built: built.__setitem__("momentId", str(MEETING)),
    ],
    ids=("missing-review-label", "citation-field"),
)
def test_the_public_projection_writer_refuses_unguarded_records(
    mutation: object,
) -> None:
    """The last public boundary before Meilisearch repeats both guards.

    A caller must not be able to bypass ``document_record`` by supplying a raw
    mapping directly to ``project_documents``. Refusal happens before the
    client is touched, so even a batch whose later record is malformed cannot
    be partially written.
    """
    built = record()
    mutation(built)  # type: ignore[operator]
    client = MagicMock()

    with pytest.raises(DocumentRecordRefused):
        search_projection.project_documents(client, [built])

    client.assert_not_called()


# --- AD-6: never a citation target -----------------------------------------


@pytest.mark.parametrize("key", sorted(FORBIDDEN_CITATION_KEYS))
def test_a_record_carrying_any_citation_field_is_refused(key: str) -> None:
    """A document is a claim *about* evidence, so its record names no evidence.

    Citing one would establish that the model said something, not that the
    meeting did — the circularity the publish gate exists to prevent. The
    mechanism is the absence: there is nothing on the record to build a
    citation from, and putting something there is refused by name.
    """
    built = record()
    built[key] = "018f3f2a-0000-7000-8000-0000000000aa"
    with pytest.raises(DocumentRecordRefused, match=key):
        assert_not_citable(built)


def test_the_built_record_carries_no_citation_field_at_all() -> None:
    assert FORBIDDEN_CITATION_KEYS.isdisjoint(record())


def test_the_query_lanes_hit_type_has_nowhere_to_put_a_citation() -> None:
    """No caller can build a citation out of a ranked document.

    Asserted over the dataclass rather than over one instance: the property is
    that the *type* carries no moment, so a later field addition fails here
    rather than at whatever consumer first tries to cite one.
    """
    names = {field.name for field in dataclass_fields(DocumentHit)}
    assert not {"moment_id", "moment_ids", "artifact_id", "start_ms", "end_ms"} & names


def test_the_wire_model_has_nowhere_to_put_a_citation() -> None:
    """Same property, at the api boundary (story 12.4).

    `SearchHit` is the citation shape and its `momentId` is required. Documents
    come back in their own array precisely so that shape is never widened with
    a null where a consumer expects a replayable citation.
    """
    names = set(DocumentHitModel.model_fields)
    assert not {
        "moment_id",
        "moment_ids",
        "artifact_id",
        "start_ms",
        "end_ms",
        "screenshot_id",
        "source_deep_link",
    } & names
    assert "documents" in SearchResponse.model_fields
    assert DocumentHitModel.model_fields["citable"].default is False


def test_the_document_lane_reads_the_documents_index_alone() -> None:
    assert DOCUMENT_SEARCHABLE_INDEXES == (DOCUMENTS_INDEX,)


def test_the_document_query_retrieves_no_moment_id_and_pins_the_review_state(
    app_config: AppConfig,
) -> None:
    """What the lane may ask the store for, and what it refuses to accept back.

    `reviewState` is pinned in the filter not to withhold anything — every
    document is reachable, which is the whole exception — but because
    ``unreviewed`` is the only state a document may carry, so anything else in
    that index was not written by this system.
    """
    parameters = build_document_search_parameters(app_config, limit=10)
    assert f'reviewState = "{REVIEW_STATE}"' in parameters["filter"]
    retrieved = set(parameters["attributesToRetrieve"])
    assert not FORBIDDEN_CITATION_KEYS & retrieved
    assert {"reviewState", "authorship", "reviewLabel"} <= retrieved


# --- the case the exception exists for -------------------------------------


def test_a_document_that_parsed_to_nothing_is_still_indexed() -> None:
    """The whole reason the gate is bypassed, made a test.

    Story 12.1's motivation turned around: the run whose text somebody needs to
    read is exactly the run that yielded nothing worth approving. A zero-yield
    document is indexed like any other, and its zero count travels with it
    rather than being smoothed away.
    """
    built = record(item_count=0, artifact_count=0, layout="none")
    assert built["text"] == SUMMARY
    assert built["itemCount"] == 0
    assert built["artifactCount"] == 0
    assert built["layout"] == "none"


def test_an_adopted_document_is_indexed_exactly_as_a_generated_one_is() -> None:
    """Both origins, one path (story 12.1's AC, story 12.4's consequence).

    The provenance differs — an adopted document names no model and no prompt,
    because this side never observed the summariser that wrote it — and the
    record says so rather than inventing values.
    """
    built = record(origin="adopted", model=None, prompt_hash=None, prompt_version=None)
    assert built["origin"] == "adopted"
    assert built["model"] is None
    assert built["promptHash"] is None
    assert built["text"] == SUMMARY
    assert built["reviewState"] == REVIEW_STATE


def test_an_empty_document_is_indexed_and_a_never_retained_one_is_refused() -> None:
    """Two different absences, kept apart (AD-18, migration 0019's distinction).

    ``""`` is a document that was written and said nothing. ``None`` is a run
    from before story 12.1 retained documents — nothing was *kept*, and the
    repair is a re-extraction rather than a reading. Indexing the second as if
    it were the first would make "nothing was kept" read as "nothing was
    written", which is exactly the silent degradation AD-18 forbids.
    """
    empty = record(text="", byte_size=0)
    assert empty["text"] == ""
    assert empty["byteSize"] == 0

    with pytest.raises(DocumentRecordRefused, match="no retained text"):
        record(text=None)


# --- configuration ---------------------------------------------------------


def _config_with_documents(tmp_path: Path, **document_overrides: object) -> None:
    """Load a config whose documents index carries the given index settings."""
    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    raw["projections"]["search"]["documents"].update(document_overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    load_config(path)


def test_the_shipped_config_declares_the_documents_index(
    app_config: AppConfig,
) -> None:
    declared = app_config.settings.projections.search.documents
    assert "text" in declared.searchable_attributes
    assert "reviewState" in declared.filterable_attributes
    assert not {"momentId", "momentIds", "artifactId"} & set(
        declared.filterable_attributes
    )


def test_the_loader_refuses_a_documents_index_that_could_surface_a_moment_id(
    tmp_path: Path,
) -> None:
    """AD-6 enforced at load, not at query time.

    A filterable ``momentId`` on this index is a citation path opening up, and
    it must be refused where a config edit is made rather than discovered when
    somebody cites a document.
    """
    with pytest.raises(ConfigError, match="never a citation target"):
        _config_with_documents(
            tmp_path,
            filterable_attributes=[
                "meetingId",
                "corpus",
                "kind",
                "reviewState",
                "momentId",
            ],
        )


def test_the_loader_refuses_a_documents_index_that_cannot_state_its_review_state(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError, match="reviewState"):
        _config_with_documents(
            tmp_path, filterable_attributes=["meetingId", "corpus", "kind"]
        )


# --- the gate's account of itself ------------------------------------------


def test_the_publish_gate_docstring_names_this_exception_and_points_at_ad_4() -> None:
    """The gate must not describe a rule that now holds only in part.

    A docstring is the first thing a reader of `publish_gate.py` believes, and
    "nothing outside `published` state is ever projected" stopped being true
    the moment this story landed. Asserted rather than trusted, because a
    docstring is exactly the kind of thing a later change leaves behind.
    """
    from meetingminer.projections import publish_gate

    docstring = publish_gate.__doc__ or ""
    assert "AD-4" in docstring
    assert "exception" in docstring.lower()
    assert "extraction document" in docstring.lower()
    # And it must still say what the gate does do, or naming the exception
    # would have replaced one wrong account with another.
    assert "artifact" in docstring.lower()


def test_the_documents_module_is_store_free() -> None:
    """The record builder is pure, so these tests need no store to be true.

    The same property `publish_gate.py` has and for the same reason: everything
    the exception has to be careful about is decidable without Meilisearch, so
    it is decided here rather than only in the slow suite.
    """
    source = Path(document_module.__file__).read_text(encoding="utf-8")
    assert "import meilisearch" not in source
    assert "import neo4j" not in source
    assert "import psycopg" not in source


# --- the mechanism, generic (so story 12.5 reuses it rather than copying) ---
#
# The owner ruled 2026-08-31 that artifacts must also be indexed before they
# are published — the same principle as this story, applied to a row type that
# *is* genuinely citable and *does* have a lifecycle. These tests pin the parts
# both stories share, so the second is a declaration plus a marking rather than
# a parallel path. They belong here because this story built them; story 12.5
# will add its own rules on top.


def test_the_gate_exception_is_a_declaration_rather_than_a_bypass() -> None:
    """A row type indexed ungated is an entry in one mapping, not an `if`.

    The difference is enumerability. A declaration can be listed, reviewed and
    refused; a second branch inside the projection module cannot be found by
    anybody who does not already know it is there.
    """
    assert require_ungated("extraction-document") in UNGATED_INDEXED_ROW_TYPES.values()
    assert "AD-4" in UNGATED_INDEXED_ROW_TYPES["extraction-document"]


def test_an_undeclared_row_type_has_no_exception() -> None:
    """Asking for a permission nobody granted is a named refusal.

    This is what keeps the mapping load-bearing: a future row type cannot skip
    the gate by omission, only by a decision somebody wrote down.
    """
    with pytest.raises(PublishGateRefused, match="not declared"):
        require_ungated("some-future-row-type")


def test_this_module_reads_its_permission_from_the_gate() -> None:
    """Deleting the declaration breaks this path by name, at import.

    A bypass that keeps working after its justification is removed is the
    failure a declaration exists to prevent.
    """
    assert document_module.ROW_TYPE == "extraction-document"
    assert document_module.GATE_EXCEPTION_REASON == require_ungated(
        document_module.ROW_TYPE
    )


def test_the_marking_reports_which_state_a_row_is_in_not_merely_unreviewed() -> None:
    """The field a second row type needs, pinned by the first that used it.

    An extraction document has no lifecycle and reports `NO_LIFECYCLE`. An
    artifact indexed before publish has a real one and reports whichever state
    it is actually in — so the marking carries a *state*, and the mechanism
    does not have to change for the second case.
    """
    for state in ("extracted", "approved", "published"):
        built = marking(
            review_state=state, authorship=MACHINE, citable=True, subject="action item"
        )
        assert built.review_state == state
        assert built.review_label
    assert not marking(
        review_state="extracted", authorship=MACHINE, citable=True, subject="x"
    ).reviewed
    assert marking(
        review_state="published", authorship=MACHINE, citable=True, subject="x"
    ).reviewed


def test_citability_is_carried_rather_than_derived_from_the_state() -> None:
    """The two facts are independent, and conflating them would be the bug.

    A published artifact is citable because it anchors to a moment; an
    extraction document is not citable in any state, because it is a claim
    about evidence. Deriving one from the other would make story 12.5's
    artifacts uncitable or this story's documents citable.
    """
    citable = marking(
        review_state=NO_LIFECYCLE, authorship=MACHINE, citable=True, subject="x"
    )
    uncitable = marking(
        review_state=NO_LIFECYCLE, authorship=MACHINE, citable=False, subject="x"
    )
    assert citable.citable is True and uncitable.citable is False
    assert "not citable evidence" in uncitable.review_label
    assert "not citable evidence" not in citable.review_label


def test_a_state_the_system_cannot_explain_is_refused() -> None:
    """No row reaches a reader wearing a status nothing can put into words."""
    with pytest.raises(ReviewMarkingRefused, match="no review sentence"):
        marking(
            review_state="probably-fine",
            authorship=MACHINE,
            citable=False,
            subject="x",
        )


def test_the_generic_guard_accepts_any_explicable_state() -> None:
    """The split the two rules need.

    `review.assert_carries_marking` asks "can this row say something explicable
    about its review status"; `documents.assert_carries_review_label` asks "does
    this document say the only thing a document may say". An artifact record
    passes the first and rightly fails the second, which is why they are two
    functions.
    """
    artifact_record = apply_marking(
        {"id": "x"},
        marking(
            review_state="approved",
            authorship=MACHINE,
            citable=True,
            subject="action item",
        ),
    )
    assert_carries_marking(artifact_record)
    with pytest.raises(DocumentRecordRefused):
        assert_carries_review_label(artifact_record)


def test_the_documents_module_reuses_the_generic_review_keys() -> None:
    """One list of keys, so two row types cannot write two shapes."""
    assert REVIEW_KEYS == ("reviewState", "authorship", "reviewLabel", "citable")
    assert set(REVIEW_KEYS) <= set(record())


def test_the_documents_label_is_composed_rather_than_hand_written() -> None:
    """The constant consumers import is the generic composer's output.

    Kept as a constant because that is what the api and the tests read; derived
    because a hand-written sentence beside a composed one is two sentences that
    drift.
    """
    assert REVIEW_LABEL == document_module.MARKING.review_label
    assert document_module.MARKING.review_state == NO_LIFECYCLE
    assert document_module.MARKING.authorship == MACHINE
    assert document_module.MARKING.citable is False
