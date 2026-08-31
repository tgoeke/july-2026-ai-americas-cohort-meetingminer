-- Story 12.1: retain the extraction documents.
--
-- Measured on the live corpus 2026-08-31: 15 meetings, 45 extraction runs, 193
-- artifacts, and zero retained documents. 0010 recorded everything *about* each
-- run — kind, origin, model, prompt hash, sha256, byte size, layout, counts —
-- and nothing of what the model actually wrote, so the document was parsed into
-- artifacts and discarded. The run whose text somebody needs to read is exactly
-- the run that yielded nothing worth approving, and that run left no readable
-- trace at all.
--
-- Why a Postgres column rather than a file under the content root: AD-4, not
-- economy. Every extraction document must be searchable (story 12.4), and
-- `projections/` never opens an evidence file — it reads Postgres values only,
-- and `rebuild` regenerates both stores from Postgres plus `config.yaml` alone.
-- Text living only in a drop could not be indexed without turning the
-- projection module into a filesystem reader, and it would fall out of search
-- on every rebuild. AD-3's anti-copy rule governs material the system *serves
-- but does not retrieve over* — the recording is never indexed, and everything
-- searchable derived from it is already rows — so it does not reach here (AD-3
-- as amended 2026-08-31). `artifact.body` is the standing precedent for
-- extraction text in a column.
--
-- Both origins store it, for that same reason: an adopted document's bytes are
-- permanent in a write-once drop, but a drop is not a place the projections can
-- read from.
ALTER TABLE extraction_source
    ADD COLUMN document_text text;

-- Nullable, and the NULL means one specific thing: this row describes a run
-- that completed before documents were retained. It is NOT "the document was
-- empty" — an empty document is the empty string, with `byte_size = 0`. A
-- reader must be able to tell "nothing was kept" from "nothing was written",
-- because those call for different actions (re-extract vs. read the zero-item
-- signal), and collapsing them into `''` would be exactly the silent
-- degradation AD-18 forbids. Every run from this migration forward writes the
-- column; a pre-existing row gets its text when the meeting is extracted
-- again, since a rerun replaces the row wholesale.
COMMENT ON COLUMN extraction_source.document_text IS
    'The exact document text that was parsed, both origins. NULL means the run '
    'predates story 12.1 retention, never that the document was empty.';

-- The story's own requirement, enforced by the database rather than trusted to
-- a call site: the stored text must be the exact bytes the parser read, so the
-- `sha256` this table already records verifies against them. `octet_length` on
-- a UTF-8 database counts the stored bytes, which is what `byte_size` counts,
-- so any path that stored a re-rendered, re-wrapped, trimmed or
-- lossily-decoded document would have to disagree with the length it also
-- recorded — and is refused here instead of becoming a row whose checksum
-- silently describes bytes nobody has.
--
-- It is a length equality rather than a digest equality because Postgres has
-- no built-in sha256 over text without pgcrypto, and a length mismatch is the
-- shape every realistic re-rendering takes. The digest itself is verified in
-- the test suite, against the stored text, for both origins.
ALTER TABLE extraction_source
    ADD CONSTRAINT extraction_source_text_matches_byte_size
    CHECK (
        document_text IS NULL
        OR octet_length(document_text) = byte_size
    );
