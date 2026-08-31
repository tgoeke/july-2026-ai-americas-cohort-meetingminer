"""`extract` — propose ADRs and action items from the whole transcript (AD-5, AD-11, AD-17).

The stage never names a model. It asks
:func:`~meetingminer.adapters.llm.build_llm` for whatever ``config.yaml`` binds
to ``llm.roles.extraction`` (AD-8, AD-10), reads the meeting's evidence bundle
through :func:`meetingminer.projections.evidence.read_meeting` — the one
assembly of "what the meeting says" (AD-4) — and works over the **whole
meeting**, once per document kind, rather than once per moment.

**Adopt when present, generate when absent.** Extraction's two documents are
the architecture summary and the owner-grouped action items. The puller's
summariser already produces both for every meeting it pulls, so when the drop
carries a document this stage parses those bytes and makes **zero model calls**;
only a document the drop lacks is generated through the `Llm` port. The decision
is per document, so a drop carrying only the action items adopts that one and
generates the other. Derivative documents are created only when necessary,
never regenerated.

**Anchoring.** Every parsed item carries an `[m:ss]` timestamp, and that anchor
is resolved to the moment containing it — greatest ``start_ms <= t``, the same
half-open tiling `plan_moments` assigns segments with. An anchor the timeline
does not contain fails the stage by name rather than dropping the artifact:
dropping would be a silent zero, and snapping to the nearest moment would
manufacture a citation. That is what keeps extraction inside *no citation, no
answer*.

Ownership is split by column (AD-5): this stage inserts rows and owns the
extraction-content columns; the lifecycle column ``state`` is written only as
the insert default — no code path here ever updates it.

Idempotence (AD-11) is delete-and-re-propose scoped to *drafts*: a rerun deletes
only this meeting's ``state = 'extracted'`` rows on moments no human has acted
on, and never proposes onto a moment already carrying an ``approved`` or
``published`` artifact — such a moment's whole artifact set, sibling drafts
included, stays exactly as the human last saw it.

The whole stage runs inside the runner's open transaction (stage.py), so a
mid-meeting failure rolls back every draft and a retry never sees half a
meeting's proposals. NFR5: only `artifact` and `extraction_source` rows are
written — no evidence table, no file, and nothing is projected here (NFR7:
artifacts reach the stores only through the publish gate, in Story 4.4).

AD-17 is why `extraction_source` exists at all: an adopted document is *arrived*
material, so it gets a row naming its drops-root-relative path, ``sha256`` and
``byte_size`` like every other evidence file the pipeline reads.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from psycopg.types.json import Jsonb

from meetingminer.adapters.llm import Llm, LlmError, LlmOptions, LlmReply, build_llm
from meetingminer.domain.drops import (
    EXTRACTION_ACTIONS_FILENAME,
    EXTRACTION_SUMMARY_FILENAME,
    sha256_and_size,
)
from meetingminer.pipeline import extraction as core
from meetingminer.domain import model_selection
from meetingminer.pipeline.stage import StageContext, StageError
from meetingminer.projections import evidence

# Superseded moments keep their id so citations resolve (AD-6), but they are
# ghosts a reader is not shown. They stay in the anchor lookup — removing them
# would punch holes in a tiling that has none, and an anchor inside the hole
# would fail a meeting for a reason that is not the model's fault — but an
# artifact that lands on one is not inserted, and the summary says how many.
_SELECT_SUPERSEDED = """
SELECT id FROM moment
WHERE meeting_id = %s AND provenance @> '{"superseded": true}'
"""

# Moments whose artifact set a human has already acted on. Their drafts were
# deleted or promoted by the API; proposing onto them would sit machine output
# beside approved judgment as if the approval had not happened.
_SELECT_APPROVED_MOMENTS = """
SELECT DISTINCT moment_id FROM artifact
WHERE meeting_id = %s AND state IN ('approved', 'published')
"""

# The one artifact deletion this stage may perform (AD-11): its own drafts,
# never an approved or published row, never another meeting's — and never a
# draft on a moment a human has already acted on. Such a moment is skipped
# below and so would not be re-proposed; deleting its sibling draft here would
# destroy it permanently. The whole artifact set of an approved moment —
# drafts included — is left exactly as the human last saw it.
_DELETE_DRAFTS = """
DELETE FROM artifact
WHERE meeting_id = %s AND state = 'extracted'
  AND moment_id NOT IN (
    SELECT moment_id FROM artifact
    WHERE meeting_id = %s AND state IN ('approved', 'published')
  )
"""

# Story 10.1: rerun replaces — topics are machine-derived navigation
# metadata with no lifecycle, so every pass deletes the meeting's topic
# rows outright (mentions cascade) before re-deriving, including on the
# no-transcript/no-moments early exit.
_DELETE_TOPICS = "DELETE FROM topic WHERE meeting_id = %s"

_INSERT_TOPIC = """
INSERT INTO topic (meeting_id, name, gist, provenance)
VALUES (%(meeting_id)s, %(name)s, %(gist)s, %(provenance)s)
RETURNING id
"""

# One row per (topic, containing moment) — the table's primary key
# enforces the collapse the stage computes.
_INSERT_TOPIC_MENTION = """
INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)
VALUES (%(topic_id)s, %(moment_id)s, %(meeting_id)s, %(anchor_ms)s)
"""

# Story 10.4: rerun replaces, exactly as it does for topics. Ranking signals
# are machine-derived rows with no lifecycle — no human ever approved one, so
# a rerun cannot destroy anything somebody chose — and the feed must never
# rank a meeting on a risk that a re-extraction no longer finds. Run before
# the early exit for the reason `_DELETE_TOPICS` is: a meeting that lost its
# transcript must not keep last run's signals.
_DELETE_RANKING_SIGNALS = "DELETE FROM ranking_signal WHERE meeting_id = %s"

# No `state` column exists to write (migration 0018): a ranking signal never
# enters the artifact approval lifecycle, so unlike `_INSERT_ARTIFACT` below
# there is not even a default for this stage to lean on.
_INSERT_RANKING_SIGNAL = """
INSERT INTO ranking_signal (
    meeting_id, moment_id, kind, label, detail, anchor_ms, item_id, provenance
) VALUES (
    %(meeting_id)s, %(moment_id)s, %(kind)s, %(label)s, %(detail)s,
    %(anchor_ms)s, %(item_id)s, %(provenance)s
)
"""

# `state` is deliberately absent: it lands as the column default 'extracted',
# which is the whole of this stage's contact with the lifecycle column (AD-5).
_INSERT_ARTIFACT = """
INSERT INTO artifact (moment_id, meeting_id, kind, title, body, provenance)
VALUES (%(moment_id)s, %(meeting_id)s, %(kind)s, %(title)s, %(body)s, %(provenance)s)
"""

# Upserted rather than replaced, so the row describing a document keeps its id
# across reruns — the same reason `align` upserts `transcript_source`.
_UPSERT_EXTRACTION_SOURCE = """
INSERT INTO extraction_source (
    meeting_id, kind, origin, drop_relative_path, sha256, byte_size,
    layout, item_count, artifact_count, model, prompt_version, prompt_hash
) VALUES (
    %(meeting_id)s, %(kind)s, %(origin)s, %(drop_relative_path)s, %(sha256)s,
    %(byte_size)s, %(layout)s, %(item_count)s, %(artifact_count)s, %(model)s,
    %(prompt_version)s, %(prompt_hash)s
)
ON CONFLICT (meeting_id, kind) DO UPDATE SET
    origin = EXCLUDED.origin,
    drop_relative_path = EXCLUDED.drop_relative_path,
    sha256 = EXCLUDED.sha256,
    byte_size = EXCLUDED.byte_size,
    layout = EXCLUDED.layout,
    item_count = EXCLUDED.item_count,
    artifact_count = EXCLUDED.artifact_count,
    model = EXCLUDED.model,
    prompt_version = EXCLUDED.prompt_version,
    prompt_hash = EXCLUDED.prompt_hash
"""

# A meeting that used to have extraction documents and now has nothing to read
# must not keep the rows describing them — the same rule `align` applies to a
# shed transcript form. Only the all-or-nothing case is reachable: every run
# that reads a transcript writes all three kinds — the two artifact
# documents and the topics document (story 10.1; migration 0014 widened
# 0010's CHECK) — so a "delete the kinds this run did not write" statement
# would be a statement that can never match a row.
_DELETE_ALL_SOURCES = "DELETE FROM extraction_source WHERE meeting_id = %s"

ORIGIN_ADOPTED = "adopted"
ORIGIN_GENERATED = "generated"


# Which `metadata.extractions` key declares each document kind, and which
# canonical filename it names. The drop schema pins the key's value to that
# filename, so the two can only disagree about presence.
_DECLARATION = {
    core.DOC_ARCH_SUMMARY: ("archSummary", EXTRACTION_SUMMARY_FILENAME),
    core.DOC_ACTION_ITEMS: ("actionItems", EXTRACTION_ACTIONS_FILENAME),
}

# Which `ExtractionRoleBinding` field carries each document's config-owned
# prompt text (story 4.2). Copied straight onto `core.build_prompt`'s
# `template=` — the stage never hard-codes prompt text of its own.
_PROMPT_FIELD = {
    core.DOC_ARCH_SUMMARY: "arch_summary_prompt",
    core.DOC_ACTION_ITEMS: "action_items_prompt",
    core.DOC_TOPICS: "topics_prompt",
}


def _drop_document(ctx: StageContext, document_kind: str) -> Path | None:
    """The drop file carrying this document, when the drop carries one.

    The drop's own `metadata.extractions` declaration is cross-checked against
    what is on disk. Deciding adoption on file presence alone made the schema's
    fail-closed `schemaVersion: 3` gate buy nothing: a drop that *declares* a
    document whose file is missing would quietly take the generate path and
    spend a model pass re-deriving work the drop said it had already done —
    while looking, in every log line, exactly like a drop that never had one.
    A drop that carries a document without declaring it is the ordinary
    pre-declaration shape and is adopted as before.
    """
    key, filename = _DECLARATION[document_kind]
    path = (
        ctx.drop.extraction_summary_path
        if document_kind == core.DOC_ARCH_SUMMARY
        else ctx.drop.extraction_actions_path
    )
    if path is None and key in ctx.drop.declared_extractions:
        raise StageError(
            f"the drop declares metadata.extractions.{key} but carries no"
            f" {filename}: {ctx.drop.path} — a drop is write-once, so its"
            " declaration and its contents cannot be reconciled here"
        )
    return path


def _read_drop_document(path: Path) -> tuple[str, str, int]:
    """Text, sha256 of the raw bytes, and byte size. The drop is only read.

    The digest is of the bytes, not the decoded text: the hash answers "did
    this input change", which is a question about the file rather than about
    our decoder. :func:`~meetingminer.domain.drops.sha256_and_size` is the one
    hashing implementation, so this reads the file twice rather than growing a
    second answer to "did these bytes change".

    A file that is not UTF-8 is a named refusal, not a lossy decode. Replacing
    undecodable bytes would put U+FFFD into artifact titles and bodies while
    the checksum — correctly taken over the raw bytes — recorded a file nobody
    could tell had been corrupt. Every other unusable input in this stage is
    refused by name; so is this one.
    """
    try:
        digest, byte_size = sha256_and_size(path)
        raw = path.read_bytes()
    except OSError as exc:
        raise StageError(
            f"extraction document {path.name} could not be read: {exc}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StageError(
            f"extraction document {path.name} is not valid UTF-8 ({exc}) — the"
            " drop is write-once evidence, so this file is replaced by a new"
            " drop rather than read lossily"
        ) from exc
    return text, digest, byte_size


def _generate(
    llm: Llm, prompt: str, options: LlmOptions, document_kind: str
) -> tuple[core.ParsedDocument, LlmReply]:
    """Complete one document, parse strictly, one retry on a parse failure.

    A model that answers unusably often answers well when asked again, so a
    parse failure earns exactly one retry against the same completer. A second
    unusable reply is a stage failure naming the document — never a silent
    zero. An `LlmError` (both models down, or no fallback configured) surfaces
    as a :class:`StageError` naming the document it happened on.
    """
    try:
        reply = llm.complete(prompt, options)
    except LlmError as exc:
        raise StageError(
            f"extract could not complete the {document_kind} document: {exc}"
        ) from exc
    try:
        return core.parse_extraction_document(reply.text, document_kind), reply
    except core.ArtifactParseError as first_error:
        try:
            reply = llm.complete(prompt, options)
        except LlmError as exc:
            raise StageError(
                f"extract could not complete the {document_kind} document on"
                f" retry: {exc}"
            ) from exc
        try:
            return core.parse_extraction_document(reply.text, document_kind), reply
        except core.ArtifactParseError as exc:
            raise StageError(
                f"the generated {document_kind} document was unusable after a"
                f" retry: {exc} (first failure: {first_error})"
            ) from exc


def _adopt(path: Path, document_kind: str) -> tuple[core.ParsedDocument, str, int, str]:
    """Parse a document the drop carried. No retry: the bytes cannot change.

    Re-reading the same file cannot parse differently, so the one-retry
    discipline the generate path uses would be a second read of identical bytes
    and a second identical failure.
    """
    text, digest, byte_size = _read_drop_document(path)
    try:
        parsed = core.parse_extraction_document(text, document_kind)
    except core.ArtifactParseError as exc:
        raise StageError(
            f"the {document_kind} document the drop carried ({path.name}) could"
            f" not be parsed: {exc}"
        ) from exc
    return parsed, digest, byte_size, text


def _meeting_date(bundle: evidence.MeetingEvidence) -> str:
    """The meeting's date, the way the puller states it to the model.

    Grounding the model in the real date is what stops it inventing calendar
    due dates for vague commitments like "next week".
    """
    return bundle.started_at.strftime("%m/%d/%Y").lstrip("0").replace("/0", "/")


def run(ctx: StageContext) -> None:
    # Resolved **per job** (story 8.2, FR38), inside this job's own
    # transaction: a selection made while this job sat queued is the selection
    # this job runs on, and a long-lived worker never has to be restarted for a
    # choice to take effect. `ctx.conn` is the runner's connection, and this is
    # a read — `app_setting` is api-owned and the worker never writes it (AD-5).
    binding, effective = model_selection.resolve_role(
        ctx.conn, "extraction", ctx.config.settings.llm.roles.extraction, log=ctx.log
    )
    ctx.log(
        "extract.binding_resolved",
        binding=effective.binding,
        provider=effective.provider,
        source=effective.source,
        file_default=effective.default_binding,
    )
    llm = build_llm(binding, ctx.config.settings.providers, log=ctx.log)
    options = LlmOptions(
        num_ctx=binding.num_ctx, timeout_seconds=binding.timeout_seconds
    )
    bundle = evidence.read_meeting(ctx.conn, ctx.meeting_id)

    superseded = {
        row[0]
        for row in ctx.conn.execute(_SELECT_SUPERSEDED, (ctx.meeting_id,)).fetchall()
    }
    approved_moments = {
        row[0]
        for row in ctx.conn.execute(
            _SELECT_APPROVED_MOMENTS, (ctx.meeting_id,)
        ).fetchall()
    }
    deleted_drafts = ctx.conn.execute(
        _DELETE_DRAFTS, (ctx.meeting_id, ctx.meeting_id)
    ).rowcount
    # Before the early exit, deliberately: a meeting that lost its
    # transcript must not keep last run's topics any more than its sources.
    deleted_topics = ctx.conn.execute(_DELETE_TOPICS, (ctx.meeting_id,)).rowcount
    # Same rule, same reason, one story later (10.4).
    deleted_signals = ctx.conn.execute(
        _DELETE_RANKING_SIGNALS, (ctx.meeting_id,)
    ).rowcount

    artifact_counts: dict[str, int] = {kind: 0 for kind in sorted(core.KNOWN_KINDS)}
    documents: dict[str, dict[str, object]] = {}
    models_used: set[str] = set()
    fallback_engaged = False
    skipped_approved = 0
    skipped_superseded = 0
    zero_signals: list[tuple[str, tuple[str, ...]]] = []

    transcript = core.render_transcript(bundle.turns)
    if not transcript.strip() or not bundle.moments:
        # Nothing to read and nowhere to anchor: no calls, no rows. The reason
        # is counted in the summary rather than passed off as a quiet success.
        ctx.conn.execute(_DELETE_ALL_SOURCES, (ctx.meeting_id,))
        ctx.log(
            "stage.extract.summary",
            meeting_id=ctx.meeting_id,
            skipped_reason=(
                "no transcript text" if not transcript.strip() else "no moments"
            ),
            moments=len(bundle.moments),
            turns=len(bundle.turns),
            documents={},
            artifacts=artifact_counts,
            drafts_replaced=deleted_drafts,
            topics=0,
            topic_mentions=0,
            topics_replaced=deleted_topics,
            ranking_signals={"risk": 0, "question": 0},
            ranking_signals_replaced=deleted_signals,
            models=[],
            fallback_engaged=False,
            prompt_version=core.PROMPT_VERSION,
        )
        return

    for document_kind in core.DOCUMENT_KINDS:
        drop_path = _drop_document(ctx, document_kind)
        model: str | None = None
        prompt_version: int | None = None
        # The hash of the resolved template text that produced this
        # document's artifacts — set only on the generate branch, `None` for
        # an adopted document (story 4.2), exactly like `model`/`prompt_version`.
        prompt_hash: str | None = None
        # Per document, not per meeting: the fallback engages at call time and
        # stays engaged, so a summary answered by the primary and actions
        # answered by the substitute must not both claim the substitute.
        document_fallback = False
        if drop_path is not None:
            parsed, digest, byte_size, _text = _adopt(drop_path, document_kind)
            origin = ORIGIN_ADOPTED
            relative_path: str | None = ctx.drop_relative_path(drop_path)
        else:
            template = getattr(binding, _PROMPT_FIELD[document_kind])
            prompt = core.build_prompt(
                document_kind,
                transcript,
                template=template,
                meeting_title=bundle.title,
                meeting_date=_meeting_date(bundle),
            )
            parsed, reply = _generate(llm, prompt, options, document_kind)
            origin = ORIGIN_GENERATED
            relative_path = None
            model = reply.model
            prompt_version = core.PROMPT_VERSION
            # The template's own hash, not a hash of the whole rendered
            # prompt (which would also fold in the meeting header and
            # transcript) — it answers "which prompt config produced this",
            # unrelated to which meeting it ran against.
            prompt_hash = hashlib.sha256(template.encode()).hexdigest()[:16]
            models_used.add(reply.model)
            document_fallback = reply.fallback_engaged
            fallback_engaged = fallback_engaged or reply.fallback_engaged
            digest, byte_size = _digest_of(reply.text)

        inserted = 0
        for proposal in parsed.artifacts:
            try:
                moment_id = core.resolve_anchor(proposal.anchor_ms, bundle.moments)
            except core.AnchorResolutionError as exc:
                raise StageError(
                    f"artifact {proposal.item_id} ({proposal.title!r}) from the"
                    f" {document_kind} document cannot be anchored: {exc}"
                ) from exc
            # A discarded proposal is named, not merely counted. Under
            # whole-transcript extraction this is a genuinely new proposal
            # being thrown away because its timestamp landed in a settled span
            # — an operator deciding whether to re-open a moment needs to know
            # which item, not just how many.
            if moment_id in approved_moments:
                # A human has acted on this moment's artifact set; re-proposing
                # onto it would sit machine output beside approved judgment.
                skipped_approved += 1
                _log_discard(ctx, document_kind, proposal, moment_id, "approved-moment")
                continue
            if moment_id in superseded:
                # A superseded moment is a ghost no right rail shows, so an
                # artifact anchored to one would never surface.
                skipped_superseded += 1
                _log_discard(
                    ctx, document_kind, proposal, moment_id, "superseded-moment"
                )
                continue
            ctx.conn.execute(
                _INSERT_ARTIFACT,
                {
                    "moment_id": moment_id,
                    "meeting_id": ctx.meeting_id,
                    "kind": proposal.kind,
                    "title": proposal.title,
                    "body": proposal.body,
                    "provenance": Jsonb(
                        {
                            "role": "extraction",
                            "source": origin,
                            "model": model,
                            "fallback_engaged": document_fallback,
                            "prompt_version": prompt_version,
                            "prompt_hash": prompt_hash,
                            "anchor_ms": proposal.anchor_ms,
                            "document_kind": document_kind,
                            "layout": proposal.layout,
                            "item_id": proposal.item_id,
                        }
                    ),
                },
            )
            artifact_counts[proposal.kind] += 1
            inserted += 1

        ctx.conn.execute(
            _UPSERT_EXTRACTION_SOURCE,
            {
                "meeting_id": ctx.meeting_id,
                "kind": document_kind,
                "origin": origin,
                "drop_relative_path": relative_path,
                "sha256": digest,
                "byte_size": byte_size,
                "layout": parsed.layout,
                "item_count": len(parsed.artifacts),
                "artifact_count": inserted,
                "model": model,
                "prompt_version": prompt_version,
                "prompt_hash": prompt_hash,
            },
        )
        documents[document_kind] = {
            "origin": origin,
            "layout": parsed.layout,
            "items": len(parsed.artifacts),
            "artifacts": inserted,
        }
        if not parsed.artifacts and parsed.populated_target_sections:
            zero_signals.append((document_kind, parsed.populated_target_sections))

    # --- the topics pass (story 10.1) ---------------------------------------
    # Always generated, never adopted: no drop declares a topics document, and
    # topics never become artifacts — the rows land in the worker-owned
    # `topic`/`topic_mention` tables, outside the publish lifecycle, through
    # the same port, parser, and one-retry discipline as the two documents
    # above.
    topics_template = binding.topics_prompt
    parsed_topics, topics_reply = _generate(
        llm,
        core.build_prompt(
            core.DOC_TOPICS,
            transcript,
            template=topics_template,
            meeting_title=bundle.title,
            meeting_date=_meeting_date(bundle),
        ),
        options,
        core.DOC_TOPICS,
    )
    models_used.add(topics_reply.model)
    fallback_engaged = fallback_engaged or topics_reply.fallback_engaged
    topics_prompt_hash = hashlib.sha256(topics_template.encode()).hexdigest()[:16]
    topics_digest, topics_byte_size = _digest_of(topics_reply.text)

    topics_inserted = 0
    mentions_inserted = 0
    for proposal in parsed_topics.artifacts:
        # Every stamp resolves through `resolve_anchor` — an anchor outside
        # the timeline fails the stage naming the topic, exactly like an
        # artifact's. Then one mention per containing moment, earliest stamp
        # winning: the moment is the citation unit, and two stamps inside one
        # moment are one discussion.
        resolved: dict[UUID, int] = {}
        for anchor_ms in proposal.anchors_ms:
            try:
                moment_id = core.resolve_anchor(anchor_ms, bundle.moments)
            except core.AnchorResolutionError as exc:
                raise StageError(
                    f"topic {proposal.item_id} ({proposal.title!r}) from the"
                    f" topics document cannot be anchored: {exc}"
                ) from exc
            if moment_id not in resolved or anchor_ms < resolved[moment_id]:
                resolved[moment_id] = anchor_ms
        surviving: dict[UUID, int] = {}
        for moment_id, anchor_ms in resolved.items():
            # Approved moments are NOT skipped here — topics are outside the
            # artifact lifecycle, so a mention attaches regardless of what a
            # human did to the moment's artifact set. A superseded moment is
            # still a ghost no reader is shown, and the skip is named.
            if moment_id in superseded:
                ctx.log(
                    "stage.extract.topic_mention_discarded",
                    meeting_id=ctx.meeting_id,
                    item_id=proposal.item_id,
                    name=proposal.title,
                    moment_id=moment_id,
                    anchor_ms=anchor_ms,
                    reason="superseded-moment",
                )
                continue
            surviving[moment_id] = anchor_ms
        if not surviving:
            # A topic with no surviving mention would be navigation to
            # nowhere; skipped, and named rather than merely counted.
            ctx.log(
                "stage.extract.topic_discarded",
                meeting_id=ctx.meeting_id,
                item_id=proposal.item_id,
                name=proposal.title,
                reason="no-surviving-mention",
            )
            continue
        topic_id = ctx.conn.execute(
            _INSERT_TOPIC,
            {
                "meeting_id": ctx.meeting_id,
                "name": proposal.title,
                "gist": core.topic_gist(proposal),
                "provenance": Jsonb(
                    {
                        "role": "extraction",
                        "source": ORIGIN_GENERATED,
                        "model": topics_reply.model,
                        "fallback_engaged": topics_reply.fallback_engaged,
                        "prompt_version": core.PROMPT_VERSION,
                        "prompt_hash": topics_prompt_hash,
                        "document_kind": core.DOC_TOPICS,
                        "layout": proposal.layout,
                        "item_id": proposal.item_id,
                    }
                ),
            },
        ).fetchone()[0]
        for moment_id, anchor_ms in sorted(surviving.items(), key=lambda kv: kv[1]):
            ctx.conn.execute(
                _INSERT_TOPIC_MENTION,
                {
                    "topic_id": topic_id,
                    "moment_id": moment_id,
                    "meeting_id": ctx.meeting_id,
                    "anchor_ms": anchor_ms,
                },
            )
            mentions_inserted += 1
        topics_inserted += 1

    ctx.conn.execute(
        _UPSERT_EXTRACTION_SOURCE,
        {
            "meeting_id": ctx.meeting_id,
            "kind": core.DOC_TOPICS,
            "origin": ORIGIN_GENERATED,
            "drop_relative_path": None,
            "sha256": topics_digest,
            "byte_size": topics_byte_size,
            "layout": parsed_topics.layout,
            "item_count": len(parsed_topics.artifacts),
            "artifact_count": topics_inserted,
            "model": topics_reply.model,
            "prompt_version": core.PROMPT_VERSION,
            "prompt_hash": topics_prompt_hash,
        },
    )
    documents[core.DOC_TOPICS] = {
        "origin": ORIGIN_GENERATED,
        "layout": parsed_topics.layout,
        "items": len(parsed_topics.artifacts),
        "artifacts": topics_inserted,
    }

    # --- the ranking-signals pass (story 10.4) -------------------------------
    # Risks and open questions, through the same `Llm(extraction)` port, the
    # same strict parser and the same one-retry discipline as everything
    # above. Always generated, never adopted: no drop declares one.
    #
    # What makes these rows different from the artifacts fifty lines up is
    # the whole point of the story, so it is written here rather than left to
    # be inferred: they are ranking signals, not artifacts. There is no
    # `state` to set, no approve route that can reach them, no export to
    # `MM_PUBLISH_ROOT`, and a rerun replaced them outright before the early
    # exit above. They exist so `GET /moments/feed` can rank without calling
    # a model at request time.
    #
    # The prompt is `ranking.signals_prompt` rather than a field on the
    # extraction role binding; `config.yaml` records why (B-46).
    signals_template = ctx.config.settings.ranking.signals_prompt
    parsed_signals, signals_reply = _generate(
        llm,
        core.build_prompt(
            core.DOC_RANKING_SIGNALS,
            transcript,
            template=signals_template,
            meeting_title=bundle.title,
            meeting_date=_meeting_date(bundle),
        ),
        options,
        core.DOC_RANKING_SIGNALS,
    )
    models_used.add(signals_reply.model)
    fallback_engaged = fallback_engaged or signals_reply.fallback_engaged
    signals_prompt_hash = hashlib.sha256(signals_template.encode()).hexdigest()[:16]
    signals_digest, signals_byte_size = _digest_of(signals_reply.text)

    signal_counts: dict[str, int] = {
        kind: 0 for kind in sorted(core.RANKING_SIGNAL_KINDS)
    }
    for proposal in parsed_signals.artifacts:
        try:
            moment_id = core.resolve_anchor(proposal.anchor_ms, bundle.moments)
        except core.AnchorResolutionError as exc:
            raise StageError(
                f"ranking signal {proposal.item_id} ({proposal.title!r}) from the"
                f" {core.DOC_RANKING_SIGNALS} document cannot be anchored: {exc}"
            ) from exc
        # Approved moments are NOT skipped, for the reason topics are not:
        # these rows are outside the artifact lifecycle, so what a human did
        # to a moment's artifact set says nothing about whether the meeting
        # raised a risk there. A superseded moment is still a ghost no reader
        # is shown, and the skip is named rather than merely counted.
        if moment_id in superseded:
            ctx.log(
                "stage.extract.ranking_signal_discarded",
                meeting_id=ctx.meeting_id,
                item_id=proposal.item_id,
                kind=proposal.kind,
                label=proposal.title,
                moment_id=moment_id,
                anchor_ms=proposal.anchor_ms,
                reason="superseded-moment",
            )
            continue
        ctx.conn.execute(
            _INSERT_RANKING_SIGNAL,
            {
                "meeting_id": ctx.meeting_id,
                "moment_id": moment_id,
                "kind": proposal.kind,
                "label": proposal.title,
                "detail": core.signal_detail(proposal),
                "anchor_ms": proposal.anchor_ms,
                "item_id": proposal.item_id,
                "provenance": Jsonb(
                    {
                        "role": "extraction",
                        "source": ORIGIN_GENERATED,
                        "model": signals_reply.model,
                        "fallback_engaged": signals_reply.fallback_engaged,
                        "prompt_version": core.PROMPT_VERSION,
                        "prompt_hash": signals_prompt_hash,
                        "document_kind": core.DOC_RANKING_SIGNALS,
                        "layout": proposal.layout,
                        "item_id": proposal.item_id,
                    }
                ),
            },
        )
        signal_counts[proposal.kind] += 1

    signals_inserted = sum(signal_counts.values())
    ctx.conn.execute(
        _UPSERT_EXTRACTION_SOURCE,
        {
            "meeting_id": ctx.meeting_id,
            "kind": core.DOC_RANKING_SIGNALS,
            "origin": ORIGIN_GENERATED,
            "drop_relative_path": None,
            "sha256": signals_digest,
            "byte_size": signals_byte_size,
            "layout": parsed_signals.layout,
            "item_count": len(parsed_signals.artifacts),
            "artifact_count": signals_inserted,
            "model": signals_reply.model,
            "prompt_version": core.PROMPT_VERSION,
            "prompt_hash": signals_prompt_hash,
        },
    )
    documents[core.DOC_RANKING_SIGNALS] = {
        "origin": ORIGIN_GENERATED,
        "layout": parsed_signals.layout,
        "items": len(parsed_signals.artifacts),
        "artifacts": signals_inserted,
    }
    if not parsed_signals.artifacts and parsed_signals.populated_target_sections:
        # The same §8 check the two artifact documents get. Deliberately keyed
        # on *populated sections* rather than on meeting content, unlike the
        # zero-topics signal below: a meeting genuinely may raise no risks and
        # no open questions, and logging every such meeting as a signal would
        # train an operator to ignore the line. A populated Risks table that
        # parsed to nothing is a different thing entirely.
        zero_signals.append(
            (core.DOC_RANKING_SIGNALS, parsed_signals.populated_target_sections)
        )

    ctx.log(
        "stage.extract.summary",
        meeting_id=ctx.meeting_id,
        moments=len(bundle.moments),
        turns=len(bundle.turns),
        documents=documents,
        adopted=sum(1 for d in documents.values() if d["origin"] == ORIGIN_ADOPTED),
        generated=sum(
            1 for d in documents.values() if d["origin"] == ORIGIN_GENERATED
        ),
        artifacts=artifact_counts,
        anchors_resolved=sum(artifact_counts.values())
        + skipped_approved
        + skipped_superseded,
        skipped_approved=skipped_approved,
        skipped_superseded=skipped_superseded,
        drafts_replaced=deleted_drafts,
        topics=topics_inserted,
        topic_mentions=mentions_inserted,
        topics_replaced=deleted_topics,
        ranking_signals=signal_counts,
        ranking_signals_replaced=deleted_signals,
        models=sorted(models_used),
        fallback_engaged=fallback_engaged,
        prompt_version=core.PROMPT_VERSION,
    )
    for document_kind, sections in zero_signals:
        # The no-silent-zero constraint: a document whose target sections
        # plainly carry content but which parsed to nothing is the
        # `retrieval-prior-art.md` §8 shape. It is not an error and it is not
        # unremarkable success either — it is a signal, and it names both the
        # document and the sections that produced nothing.
        ctx.log(
            "stage.extract.zero_artifacts",
            meeting_id=ctx.meeting_id,
            document=document_kind,
            origin=documents[document_kind]["origin"],
            populated_sections=list(sections),
        )
    if not topics_inserted:
        # Zero topics on a meeting that HAS transcript text and moments —
        # this code is past the early exit — is a signal keyed on meeting
        # content, never on parser section names: an empty topics table
        # from the model must not read as quiet success (story 10.1).
        ctx.log(
            "stage.extract.zero_topics",
            meeting_id=ctx.meeting_id,
            items_parsed=len(parsed_topics.artifacts),
        )


def _log_discard(
    ctx: StageContext,
    document_kind: str,
    proposal: core.ProposedArtifact,
    moment_id: UUID,
    reason: str,
) -> None:
    """Name a proposal the stage parsed but deliberately did not insert."""
    ctx.log(
        "stage.extract.artifact_discarded",
        meeting_id=ctx.meeting_id,
        document=document_kind,
        item_id=proposal.item_id,
        title=proposal.title,
        moment_id=moment_id,
        anchor_ms=proposal.anchor_ms,
        reason=reason,
    )


def _digest_of(text: str) -> tuple[str, int]:
    """sha256 and byte size of a generated document's UTF-8 bytes.

    A generated document has no file, so there is nothing for
    :func:`~meetingminer.domain.drops.sha256_and_size` to read — but the
    `extraction_source` row still has to identify the exact bytes that were
    parsed, so a rerun can prove whether the input changed.
    """
    raw = text.encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), len(raw)
