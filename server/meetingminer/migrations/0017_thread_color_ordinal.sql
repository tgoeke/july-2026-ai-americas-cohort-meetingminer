-- Story 10.3: a durable colour identity for every thread (closes B-40).
--
-- The Threads view colours a thread's band. Colouring by list position would
-- recolour every thread whenever the list is re-sorted, a thread is renamed,
-- or a rerun changes how many threads exist — so the colour has to be a
-- server-owned number the thread carries, not a rendering accident. That is
-- `color_ordinal`: a positive integer allocated once, unique, and never
-- changed or reused.
--
-- **Why one sequence and not one per corpus.** B-40 left the scope open
-- because `thread` has no corpus column and 0015's derivation is corpus-wide:
-- topics from a `scripted` meeting and a `real` meeting union into one thread
-- whenever they name the same subject. A thread therefore has no single
-- `meeting.corpus` value to be scoped by, and partitioning the allocator by
-- one would give a cross-corpus thread two colours. The corpus that owns the
-- ordinal is the MeetingMiner corpus — this database of record (AD-2) — and
-- one monotone sequence in it gives every thread exactly one colour.
--
-- **Why a SEQUENCE and not `max(color_ordinal) + 1`.** Two concurrent thread
-- derivations reading a maximum see the same answer under every isolation
-- level that does not serialize them outright, so both would claim the same
-- ordinal and the UNIQUE constraint below would turn a colour clash into a
-- failed derivation. `nextval` is exempt from transaction visibility: two
-- open transactions cannot receive the same value, and neither waits on the
-- other. It is transactional in the sense this story needs — allocation
-- happens inside the inserting transaction, so a thread and its ordinal
-- commit together or not at all — and deliberately not gap-free: a rolled
-- back insert burns its value rather than returning it, which is exactly
-- what "never recycled within the corpus" asks for.
--
-- `thread` itself remains WORKER-OWNED and MACHINE-DERIVED navigation
-- metadata (0015): this column is allocated by the record, read by the api,
-- and written by no one afterwards.

CREATE SEQUENCE thread_color_ordinal_seq AS bigint START WITH 1 MINVALUE 1 NO CYCLE;

-- A volatile default, so ADD COLUMN rewrites the table and evaluates
-- `nextval` once per existing row: threads derived before this migration each
-- get their own ordinal rather than sharing one backfilled constant.
ALTER TABLE thread
    ADD COLUMN color_ordinal bigint NOT NULL
        DEFAULT nextval('thread_color_ordinal_seq');

-- Positive, because the ordinal is a colour index a client maps into a
-- palette; zero and negatives have no meaning there and would silently
-- collapse onto one another under a modulo.
ALTER TABLE thread
    ADD CONSTRAINT thread_color_ordinal_positive CHECK (color_ordinal > 0);

-- Two threads sharing a colour is the failure this whole column exists to
-- prevent, so it is a constraint rather than an allocator convention. The
-- index it creates also serves the api's ordering.
ALTER TABLE thread
    ADD CONSTRAINT thread_color_ordinal_unique UNIQUE (color_ordinal);

-- An explicitly supplied ordinal — a restore, or an import of a corpus whose
-- ordinals were allocated elsewhere — must not leave the sequence behind its
-- own data, or the next derived thread would collide with an imported row and
-- fail. Advancing the sequence past the value keeps allocation monotone for
-- everything that follows. An explicit NULL still allocates: the DEFAULT is
-- bypassed by an explicit NULL, and a thread without a colour is not a row
-- this table should hold.
CREATE FUNCTION thread_color_ordinal_reserve() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.color_ordinal IS NULL THEN
        NEW.color_ordinal := nextval('thread_color_ordinal_seq');
    -- Equality matters for a fresh sequence: its first `last_value` is present
    -- while `is_called` is false, so leaving an explicit `1` untouched would
    -- let the next `nextval` return `1` again. Calling `setval` for equality
    -- marks that value consumed as well as keeping larger imports ahead.
    ELSIF NEW.color_ordinal >= (SELECT last_value FROM thread_color_ordinal_seq) THEN
        PERFORM setval('thread_color_ordinal_seq', NEW.color_ordinal);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER thread_color_ordinal_reserve_on_insert
    BEFORE INSERT ON thread
    FOR EACH ROW EXECUTE FUNCTION thread_color_ordinal_reserve();

-- Immutability is the half of "allocated once" that a UNIQUE constraint does
-- not give: without this, a merge could quietly hand the survivor the loser's
-- colour, or a rerun could renumber the whole corpus and recolour every band
-- a user has learned. Story 10.2a's merge renames the survivor and moves
-- memberships onto it — both `UPDATE`s — and neither may reach this column.
-- A split is a *new* `thread` row, so it takes a new ordinal from the
-- sequence by the ordinary insert path and needs no rule here.
CREATE FUNCTION thread_color_ordinal_is_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.color_ordinal IS DISTINCT FROM OLD.color_ordinal THEN
        RAISE EXCEPTION
            'thread.color_ordinal is allocated once and never changed'
            ' (thread %: % -> %)',
            OLD.id, OLD.color_ordinal, NEW.color_ordinal;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER thread_color_ordinal_immutable
    BEFORE UPDATE OF color_ordinal ON thread
    FOR EACH ROW EXECUTE FUNCTION thread_color_ordinal_is_immutable();
