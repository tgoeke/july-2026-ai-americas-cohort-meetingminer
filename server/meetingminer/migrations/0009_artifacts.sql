-- Story 4.1: artifacts — the proposals the `extract` stage mints and humans
-- approve (AD-5, AD-6, AD-11; ERD `MOMENT ||--o{ ARTIFACT`).

-- The composite-FK target for `artifact` below: `(id, meeting_id)` is unique
-- because `id` alone already is, so this adds no new restriction on `moment`
-- — it only lets `artifact` reference the pair as one edge, which is what
-- makes an artifact's `meeting_id` provably the meeting of its own moment.
ALTER TABLE moment ADD CONSTRAINT moment_id_meeting_id_key UNIQUE (id, meeting_id);

-- One proposed ADR or action item, FK-linked to the moment whose evidence
-- yielded it. Ownership is split by column (AD-5): the worker inserts rows and
-- owns the extraction-content columns (`kind`, `title`, `body`, `provenance`);
-- the API owns the lifecycle column `state`, which the worker touches only as
-- the insert default — no worker code path ever updates it.
CREATE TABLE artifact (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    moment_id    uuid NOT NULL,
    meeting_id   uuid NOT NULL REFERENCES meeting (id),
    -- The two kinds Story 4.1 extracts. Later artifact types (decisions,
    -- stories, requirements, ...) widen this CHECK when a story builds them.
    kind         text NOT NULL CHECK (kind IN ('adr', 'action-item')),
    -- The one-way lifecycle from AD-4/AD-5 (`projections/publish_gate.py`):
    -- `extracted` (unpublished draft) -> `approved` -> `published`.
    -- Transitions are API-only and there is no unpublish path.
    state        text NOT NULL DEFAULT 'extracted'
                 CHECK (state IN ('extracted', 'approved', 'published')),
    title        text NOT NULL,
    body         text NOT NULL,
    -- Which prompt/model configuration produced this proposal: role, model,
    -- fallback_engaged, prompt_version — the provenance the Epic 5 eval
    -- harness snapshots per run.
    provenance   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    -- One composite edge instead of a bare `moment_id` FK: it also pins
    -- `meeting_id` to the moment's own meeting, so a row can never name a
    -- moment from a different meeting — which would silently corrupt the
    -- meeting-keyed draft delete and the approved-moment skip in the stage.
    -- Deliberately NO cascade: a moment that yielded artifacts is cited
    -- evidence, and deleting it must fail loudly rather than silently take
    -- approved or published artifacts with it — "published artifacts stay
    -- valid across augmentation" is enforced here, not assumed.
    FOREIGN KEY (moment_id, meeting_id) REFERENCES moment (id, meeting_id)
);

-- The moment view's right rail reads by moment; the extract stage's
-- idempotence rule (delete-and-re-propose only `extracted` rows) and the
-- publish paths read by meeting and state.
CREATE INDEX artifact_moment_id_idx ON artifact (moment_id);
CREATE INDEX artifact_meeting_state_idx ON artifact (meeting_id, state);

CREATE TRIGGER artifact_set_updated_at
    BEFORE UPDATE ON artifact
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
