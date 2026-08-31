-- Story 10.4: ranking signals — moment-anchored risks and open questions that
-- the Moments feed ranks on (FR40; ERD `MOMENT ||--o{ RANKING_SIGNAL`).
--
-- These rows are WORKER-OWNED and MACHINE-DERIVED, and every reader must
-- label them as such. They are the same class of thing as 0014's `topic` and
-- 0015's `thread`: navigation metadata, NOT artifacts. Concretely, and this
-- is the whole reason the table is separate from `artifact`:
--
--   * there is no `state` column, because there is no lifecycle. A ranking
--     signal never becomes `extracted -> approved -> published`; no api route
--     transitions it, and the publish gate never sees it.
--   * a rerun REPLACES a meeting's rows wholesale (`DELETE FROM
--     ranking_signal WHERE meeting_id = ...`), the way `topic` is replaced —
--     unlike `artifact`, whose delete-and-re-propose is scoped to drafts a
--     human has not acted on, because a human never acts on one of these.
--   * nothing here is ever exported to `MM_PUBLISH_ROOT` or committed to the
--     ADR repository.
--
-- The api reads them and writes none of them (AD-5): `GET /moments/feed`
-- scores stored rows and makes no model call at request time.

CREATE TABLE ranking_signal (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    -- Denormalized beside `moment_id` for the same reason `artifact` and
    -- `topic_mention` carry it: it makes the composite edge below possible,
    -- which is what pins a signal to the meeting of its own moment.
    meeting_id   uuid NOT NULL,
    moment_id    uuid NOT NULL,
    -- The two ranking-signal kinds story 10.4 extracts. A later kind widens
    -- this CHECK in its own migration, exactly as 0014 widened 0010's.
    kind         text NOT NULL CHECK (kind IN ('risk', 'question')),
    -- The one line the feed renders as a `reasons[]` label. NOT NULL and
    -- CHECKed non-blank: a reason with no label is a reason a reader cannot
    -- act on, and the feed drops an item whose reasons are all invalid — so
    -- an empty label must be refused at the record rather than becoming a
    -- silently vanishing feed row.
    label        text NOT NULL CHECK (btrim(label) <> ''),
    -- The supporting sentence, as parsed. May legitimately be empty: a risk
    -- stated in five words carries no elaboration, and inventing one would be
    -- the model writing rather than reporting.
    detail       text NOT NULL DEFAULT '',
    -- The `[m:ss]` stamp the item carried, in milliseconds from recording
    -- start — the same anchor vocabulary `topic_mention.anchor_ms` uses. Kept
    -- beside `moment_id` because the moment is the citation unit but the
    -- stamp is what a reader is pointed at inside it.
    anchor_ms    bigint NOT NULL CHECK (anchor_ms >= 0),
    -- The source document's own short ID (`R1`, `Q2`), so a row traces back
    -- to the line that produced it. Not unique: a rerun mints new rows.
    item_id      text NOT NULL,
    -- Which prompt/model configuration produced this row — the same shape
    -- `artifact.provenance` and `topic.provenance` carry.
    provenance   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    -- The composite edge 0009 introduced and 0014 reused: the pair pins
    -- `meeting_id` to the moment's own meeting, so a signal can never name
    -- another meeting's moment. CASCADE, like `topic_mention` and unlike
    -- `artifact`: a ranking signal is navigation metadata, not cited
    -- evidence, so a deleted moment takes its signals with it rather than
    -- blocking on them.
    FOREIGN KEY (moment_id, meeting_id)
        REFERENCES moment (id, meeting_id) ON DELETE CASCADE
);

-- The rerun replacement reads by meeting; the feed's scorer reads by moment.
CREATE INDEX ranking_signal_meeting_id_idx ON ranking_signal (meeting_id);
CREATE INDEX ranking_signal_moment_id_idx ON ranking_signal (moment_id);

CREATE TRIGGER ranking_signal_set_updated_at
    BEFORE UPDATE ON ranking_signal
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 0010's comment says widening the document-kind CHECK is a story, and 0014
-- widened it for the topics document; this is the same edit for the
-- ranking-signals document. It is always generated and never adopted — no
-- drop declares one — but it still gets an `extraction_source` row, because
-- that row is how a rerun proves whether the parsed bytes changed.
ALTER TABLE extraction_source
    DROP CONSTRAINT extraction_source_kind_check;
ALTER TABLE extraction_source
    ADD CONSTRAINT extraction_source_kind_check
    CHECK (kind IN ('arch-summary', 'action-items', 'topics', 'ranking-signals'));
