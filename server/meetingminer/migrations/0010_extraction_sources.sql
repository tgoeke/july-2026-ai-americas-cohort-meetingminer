-- Story 4.1a: the documents whole-transcript extraction read (AD-11, AD-17).
--
-- Extraction operates on the whole meeting transcript and produces two
-- documents per meeting: the architecture summary and the owner-grouped action
-- items. Either can *arrive* in the source drop (the puller's summariser wrote
-- it) or be *generated* here through the `Llm` port when the drop carries none.
--
-- AD-17: an adopted document is arrived material, so it gets a row naming its
-- drops-root-relative path, `sha256` and `byte_size` exactly like every other
-- evidence file — this is the same shape `transcript_source` uses. A generated
-- document has no drop file, so its path is NULL and the checksum describes the
-- bytes the model produced.
--
-- The row is also where the no-silent-zero check records what it parsed:
-- `layout` says which of the two markdown layouts matched and `artifact_count`
-- says how many artifacts the document yielded, so "this document parsed to
-- nothing" is a fact in the data rather than only a log line.
CREATE TABLE extraction_source (
    id                 uuid PRIMARY KEY DEFAULT uuidv7(),
    meeting_id         uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    -- The two documents the proven summariser pair produces. Widening this
    -- CHECK is a new document kind, which is a story, not a config edit.
    kind               text NOT NULL
                       CHECK (kind IN ('arch-summary', 'action-items')),
    -- Whether this document arrived in the drop or was produced here. The
    -- adopt path makes zero model calls, which is the whole point of recording
    -- the distinction: a corpus mixing the two stays interpretable.
    origin             text NOT NULL CHECK (origin IN ('adopted', 'generated')),
    -- Path relative to MM_DROPS_ROOT: <drop-dir>/<filename>. Never absolute.
    -- NULL for a generated document, which is not a drop file.
    drop_relative_path text,
    -- Identity of the exact bytes that were parsed — the drop file's for an
    -- adopted document, the model's reply for a generated one — so a rerun can
    -- prove whether the input changed.
    sha256             text NOT NULL,
    byte_size          bigint NOT NULL CHECK (byte_size >= 0),
    -- Which markdown layout the parser matched: 'table', 'bullet', 'mixed', or
    -- 'none' when the document yielded no items at all. The
    -- `retrieval-prior-art.md` §8 failure was a parser that understood one of
    -- two layouts and reported success; recording the match makes a corpus-wide
    -- skew visible in one query.
    layout             text NOT NULL
                       CHECK (layout IN ('table', 'bullet', 'mixed', 'none')),
    -- What the parser found, and what actually became a row. They differ when
    -- an item anchored onto a moment a human has already acted on, or onto a
    -- superseded one. Recording only the second made a document that parsed
    -- five decisions and inserted none indistinguishable from one that parsed
    -- nothing at all -- in exactly the query this column exists for.
    item_count         integer NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    artifact_count     integer NOT NULL DEFAULT 0 CHECK (artifact_count >= 0),
    CONSTRAINT extraction_source_inserted_within_parsed
        CHECK (artifact_count <= item_count),
    -- The model and prompt that produced a *generated* document. NULL for an
    -- adopted one: it was written by the puller's summariser, whose model this
    -- side does not observe and must not guess at.
    model              text,
    prompt_version     integer,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    -- One document per kind per meeting: a rerun replaces the row rather than
    -- accumulating a second description of the same document.
    UNIQUE (meeting_id, kind)
);

-- The anchor rule, enforced (migration 0008): a root-relative path may not be
-- empty or absolute, may not use root aliases or duplicate/trailing separators,
-- may not contain a `..` segment, and must carry both a drop-directory
-- component and a filename. Copied verbatim from `transcript_source`'s
-- constraint — and VALID rather than NOT VALID, because this table has no
-- legacy rows predating the rule.
ALTER TABLE extraction_source
    ADD CONSTRAINT extraction_source_drop_relative_path_is_root_relative
    CHECK (
        drop_relative_path IS NULL
        OR (
            drop_relative_path <> ''
            AND drop_relative_path NOT LIKE '/%'
            AND drop_relative_path !~ '(^|/)\.\.(/|$)'
            AND drop_relative_path !~ '(^|/)\.(/|$)'
            AND drop_relative_path !~ '//'
            AND drop_relative_path !~ '/$'
            AND drop_relative_path ~ '^[^/]+/[^/]+.*$'
        )
    );

-- An adopted document names a drop file; a generated one cannot. Stating it as
-- a constraint keeps the two origins from drifting into a third, undefined
-- shape (a "generated" row carrying a drop path describes a file nothing wrote).
ALTER TABLE extraction_source
    ADD CONSTRAINT extraction_source_path_matches_origin
    CHECK ((origin = 'adopted') = (drop_relative_path IS NOT NULL));

CREATE TRIGGER extraction_source_set_updated_at
    BEFORE UPDATE ON extraction_source
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
