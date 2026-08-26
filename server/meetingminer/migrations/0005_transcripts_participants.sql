-- Story 1.5: the transcript verification lane, the derived speaker-attributed
-- transcript, and the participants it resolves to
-- (AD-5, AD-8, AD-11, AD-13; ERD `PARTICIPANT ||--o{ TRANSCRIPT_SEGMENT`).

-- One *raw* input to the transcript lane: a file the drop provided, or the STT
-- run over the recording's extracted audio. Raw sources are never merged into
-- each other (AD-13) — reconciliation produces the derived `transcript_segment`
-- rows below, and each of those names the sources it came from.
--
-- A provided source stores no segments here: the drop is read-only and stays
-- on disk, so its text is re-parsed from `drop_relative_path` on every run.
-- The STT lane has nowhere else to live — re-running the recognizer costs
-- minutes of compute and is not bit-reproducible — so its segments are kept in
-- `segments`. That is what lets `align` re-run any number of times and still
-- have a verification anchor to reconcile against.
CREATE TABLE transcript_source (
    id                 uuid PRIMARY KEY DEFAULT uuidv7(),
    meeting_id         uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    kind               text NOT NULL
                       CHECK (kind IN ('provided-text', 'provided-vtt', 'stt')),
    -- Which lineage the parser recognized: the Teams `[m:ss] Last, First: text`
    -- source of record, the legacy `<Name> | MM:SS` third-party export, a VTT
    -- subtitle track, or the STT lane's own output.
    format             text NOT NULL
                       CHECK (format IN ('teams', 'legacy', 'vtt', 'stt')),
    -- Path inside the source drop, relative to the drop directory. Recorded so
    -- a derived row can name the exact file it came from; the drop itself is
    -- never written (AD-13). NULL for the STT lane, which has no drop file.
    drop_relative_path text,
    -- Path relative to MM_CONTENT_ROOT (AD-3) for material this pipeline
    -- produced — the extracted 16 kHz mono WAV the STT lane read. NULL for a
    -- provided source, which lives in the drop.
    content_path       text,
    -- Identity of the exact bytes that were read, so a re-ingest can prove
    -- whether the input changed.
    sha256             text NOT NULL,
    byte_size          bigint NOT NULL CHECK (byte_size >= 0),
    segment_count      integer NOT NULL DEFAULT 0 CHECK (segment_count >= 0),
    -- Which engine/model produced this, so a corpus mixing mlx-whisper and
    -- parakeet-mlx output stays interpretable (AD-8). NULL for provided files.
    engine             text,
    model              text,
    language           text,
    -- The STT lane's raw segments: [{"start_ms":…, "end_ms":…, "text":…,
    -- "speaker": …|null}]. Empty for a provided source (see above).
    segments           jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    -- One source per kind per meeting: a drop carries at most one transcript
    -- of each form, and the STT lane is replaced by a rerun, never accumulated.
    UNIQUE (meeting_id, kind)
);

CREATE TRIGGER transcript_source_set_updated_at
    BEFORE UPDATE ON transcript_source
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- A person, across every meeting they appear in. Cross-meeting by design
-- (AD-5/AD-11): upserted by `identity_key` and never deleted by a stage rerun.
--
-- `identity_key` is the participant graph's `mail` when it carries one, and
-- the normalized display name for the rows that do not. Mail is a real
-- directory identifier that costs no Microsoft Graph call: it comes from the
-- SharePoint user-profile service and is present on 222 of 225 person-rows in
-- the corpus. It is not the tenant login, which is an employee number
-- (`58231@contoso.com`) — a different value that would miss if joined.
--
-- A name-only key holds only while no two people share a name. That is true of
-- the 50 distinct people here and false of the 150-person store upstream, and
-- the failure mode is silent: two humans collapse onto one row, which is the
-- wrong attribution the never-guess constraint exists to prevent.
--
-- The two spaces are namespaced: `mail:timothy.goeke@contoso.com` and
-- `name:tim goeke`. `@` alone would separate them, but this column is UNIQUE
-- and the API writes `participant_alias.alias_key` against it, so which space
-- a key belongs to is stated rather than inferred from punctuation.
CREATE TABLE participant (
    id              uuid PRIMARY KEY DEFAULT uuidv7(),
    identity_key    text NOT NULL UNIQUE,
    -- As first seen, for display. The API owns human edits to it (AD-5); the
    -- worker only fills it in when it creates the row.
    display_name    text NOT NULL,
    -- The normalized display name, always — the roster-matching key, kept
    -- alongside `identity_key` rather than duplicating it, so a name lookup
    -- still works on a row whose identity is a mail address.
    normalized_name text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER participant_set_updated_at
    BEFORE UPDATE ON participant
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- API-owned merge records (AD-5). A human merge writes `alias_key → surviving
-- participant`; the worker *reads* this table and resolves an identity key
-- through it before every insert, so a merge survives re-ingests and stage
-- reruns. The worker never writes here.
CREATE TABLE participant_alias (
    alias_key      text PRIMARY KEY,
    participant_id uuid NOT NULL REFERENCES participant (id) ON DELETE CASCADE,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX participant_alias_participant_id_idx
    ON participant_alias (participant_id);

CREATE TRIGGER participant_alias_set_updated_at
    BEFORE UPDATE ON participant_alias
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- One person's attendance of one meeting: the per-meeting facts that do not
-- belong on the cross-meeting `participant` row. Meeting-scoped evidence, so
-- an `align` rerun replaces these rows while the `participant` rows they point
-- at survive (AD-11).
CREATE TABLE meeting_participant (
    meeting_id       uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    participant_id   uuid NOT NULL REFERENCES participant (id) ON DELETE CASCADE,
    -- Straight from the drop's participant graph when it carries one.
    -- `department` is the readable org name and `dept_code` the cost-centre
    -- code; they are different fields upstream and are not reconciled here.
    mail             text,
    title            text,
    department       text,
    dept_code        text,
    line_of_business text,
    office           text,
    org              text,
    is_guest         boolean NOT NULL DEFAULT false,
    -- The participant graph's `unresolved: true`: an external attendee who is
    -- not in the tenant directory. A real, kept person — deliberately NOT the
    -- same thing as `transcript_segment.speaker_resolution = 'unresolved'`,
    -- which marks a speaker label that matched nobody. The two must never be
    -- collapsed: one is an attendee, the other is an absent attribution.
    is_external      boolean NOT NULL DEFAULT false,
    -- Share-of-talk as the source recorded it, when it did.
    spoke_turns      integer,
    spoke_words      integer,
    -- Provenance the source already carries (invite / permissions / transcript).
    found_in         text[] NOT NULL DEFAULT '{}',
    derived_from     text NOT NULL
                     CHECK (derived_from IN ('drop-graph', 'transcript', 'both')),
    -- The graph entry verbatim, so a field this schema does not model is not
    -- lost. Empty for a participant derived from speaker attribution alone.
    source           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (meeting_id, participant_id)
);

CREATE INDEX meeting_participant_participant_id_idx
    ON meeting_participant (participant_id);

CREATE TRIGGER meeting_participant_set_updated_at
    BEFORE UPDATE ON meeting_participant
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The derived, speaker-attributed transcript: `align`'s whole output, and the
-- only transcript rows anything downstream reads. Every row is *new* and names
-- its inputs (AD-13) — the provided transcript is parsed in place and never
-- rewritten, copied over, or deleted.
CREATE TABLE transcript_segment (
    id                 uuid PRIMARY KEY DEFAULT uuidv7(),
    meeting_id         uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    ordinal            integer NOT NULL CHECK (ordinal >= 1),
    -- Integer milliseconds from recording start, the project-wide convention.
    start_ms           bigint NOT NULL CHECK (start_ms >= 0),
    end_ms             bigint NOT NULL CHECK (end_ms >= 0),
    text               text NOT NULL,
    -- The label exactly as the transcript wrote it (`Whitmore, Ellis`,
    -- `Ellis`, `oakleylangmere`, `Speaker 8`), never a normalized or guessed
    -- form. `Unknown` when no source offered one.
    speaker_label      text NOT NULL,
    -- Set only when the label resolved to exactly one roster entry. An
    -- `unresolved`, `ambiguous`, or `placeholder` row carries NULL here and is
    -- never merged into a resolved person: a wrong attribution is worse than
    -- an absent one.
    participant_id     uuid REFERENCES participant (id) ON DELETE SET NULL,
    speaker_resolution text NOT NULL
                       CHECK (speaker_resolution IN
                              ('resolved', 'unresolved', 'ambiguous', 'placeholder')),
    -- Provenance to both inputs (AD-13). Labels and text come from
    -- `label_source_id`; the end timing from `timing_source_id`, which is the
    -- VTT where a cue matched and the label source otherwise; `stt_source_id`
    -- is the verification lane and is NULL when this row was not anchored.
    label_source_id    uuid NOT NULL REFERENCES transcript_source (id) ON DELETE CASCADE,
    timing_source_id   uuid NOT NULL REFERENCES transcript_source (id) ON DELETE CASCADE,
    stt_source_id      uuid REFERENCES transcript_source (id) ON DELETE CASCADE,
    -- The matched STT segment's start, the signed offset from this row's own
    -- start, and the token-overlap score that justified the match. All NULL on
    -- an unanchored row — never a fabricated zero.
    stt_start_ms       bigint CHECK (stt_start_ms >= 0),
    alignment_delta_ms bigint,
    match_score        numeric CHECK (match_score >= 0 AND match_score <= 1),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (end_ms >= start_ms),
    -- An anchored row carries all three anchor columns or none of them.
    CHECK (
        (stt_source_id IS NULL AND stt_start_ms IS NULL
         AND alignment_delta_ms IS NULL AND match_score IS NULL)
        OR (stt_source_id IS NOT NULL AND stt_start_ms IS NOT NULL
            AND alignment_delta_ms IS NOT NULL AND match_score IS NOT NULL)
    ),
    -- Only a resolved label may name a participant.
    CHECK (participant_id IS NULL OR speaker_resolution = 'resolved'),
    UNIQUE (meeting_id, ordinal)
);

-- `moments` (story 1.6) reads one meeting's segments in time order.
CREATE INDEX transcript_segment_meeting_start_idx
    ON transcript_segment (meeting_id, start_ms);
CREATE INDEX transcript_segment_participant_id_idx
    ON transcript_segment (participant_id);

CREATE TRIGGER transcript_segment_set_updated_at
    BEFORE UPDATE ON transcript_segment
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
